from __future__ import annotations

import json

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from seldon.agents.base import AgentBase
from seldon.config import AgentModelConfig, OpenRouterConfig, SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentMessage, ModelInvocation
from seldon.llm.openrouter import OpenRouterClient


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


class PromptInput(BaseModel):
    prompt: str


class PromptOutput(BaseModel):
    answer: str
    confidence: float


class HelperAgent(AgentBase[PromptInput, PromptOutput]):
    agent_id = "information_summarizer"
    phase = "test"
    model_profile = "fast"

    def _run(self, payload: PromptInput, *, run_id: str, parent_run_id: str | None) -> PromptOutput:
        result = self.llm_complete_json(
            [{"role": "user", "content": payload.prompt}],
            run_id=run_id,
            schema=PromptOutput,
            repair_retries=1,
        )
        return PromptOutput.model_validate(result)


class DirectAgent(AgentBase[PromptInput, PromptOutput]):
    agent_id = "pairwise_relationship_detector"
    phase = "test"
    model_profile = "balanced"

    def _run(self, payload: PromptInput, *, run_id: str, parent_run_id: str | None) -> PromptOutput:
        assert self.llm_client is not None
        result = self.llm_client.complete_json(
            [{"role": "user", "content": payload.prompt}],
            schema=PromptOutput,
            agent=self.agent_id,
        )
        return PromptOutput.model_validate(result)


def response(content: dict, *, model: str = "test/model") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "provider": "mock-provider",
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "cost": 0.001},
            "choices": [{"message": {"content": json.dumps(content)}}],
        },
    )


def test_agent_llm_helper_records_invocations_and_repairs_invalid_structured_output():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return response({"answer": "missing confidence"})
        return response({"answer": "repaired", "confidence": 0.82}, model=body["model"])

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = SeldonConfig(
        llm=OpenRouterConfig(default_model="balanced-model", fast_model="fast-model", reasoning_model="reasoning-model", fallback_models=[]),
    )
    cfg.agents.information_summarizer = AgentModelConfig(model_profile="fast", temperature=0.15, max_tokens=200)

    factory = session_factory()
    with factory() as db:
        with db.begin():
            run_id, output = HelperAgent(db, config=cfg, llm_client=OpenRouterClient(cfg.llm, http_client=http_client)).run(PromptInput(prompt="summarize"))

        assert output.answer == "repaired"
        assert [call["model"] for call in calls] == ["fast-model", "fast-model"]
        assert calls[0]["temperature"] == 0.15
        assert calls[0]["max_tokens"] == 200
        assert "failed structured validation" in calls[1]["messages"][-1]["content"]

        invocations = list(db.scalars(select(ModelInvocation).order_by(ModelInvocation.created_at)))
        assert len(invocations) == 2
        assert {row.agent_run_id for row in invocations} == {run_id}
        assert [row.ok for row in invocations] == [False, True]
        assert invocations[0].agent == "information_summarizer"
        assert invocations[1].raw_metadata["repair_attempt"] == 1


def test_agent_run_wraps_app_created_openrouter_client_with_db_recorder_for_direct_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return response({"answer": body["model"], "confidence": 0.9}, model=body["model"])

    cfg = SeldonConfig(llm=OpenRouterConfig(default_model="balanced-model", fast_model="fast-model", fallback_models=[]))
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app_created_client = OpenRouterClient(cfg.llm, http_client=http_client)

    factory = session_factory()
    with factory() as db:
        with db.begin():
            run_id, output = DirectAgent(db, config=cfg, llm_client=app_created_client).run(PromptInput(prompt="detect"))

        assert output.answer == "balanced-model"
        invocation = db.scalar(select(ModelInvocation))
        assert invocation is not None
        assert invocation.agent_run_id == run_id
        assert invocation.agent == "pairwise_relationship_detector"
        assert invocation.ok is True


def test_agent_llm_helper_escalates_low_confidence_outputs():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["model"] == "fast-model":
            return response({"answer": "weak", "confidence": 0.2}, model=body["model"])
        return response({"answer": "strong", "confidence": 0.91}, model=body["model"])

    class EscalatingAgent(AgentBase[PromptInput, PromptOutput]):
        agent_id = "query_decomposer"
        phase = "test"
        model_profile = "fast"

        def _run(self, payload: PromptInput, *, run_id: str, parent_run_id: str | None) -> PromptOutput:
            result = self.llm_complete_json(
                [{"role": "user", "content": payload.prompt}],
                run_id=run_id,
                schema=PromptOutput,
                min_confidence=0.5,
                escalation_profiles=("reasoning",),
            )
            return PromptOutput.model_validate(result)

    cfg = SeldonConfig(llm=OpenRouterConfig(default_model="balanced-model", fast_model="fast-model", reasoning_model="reasoning-model", fallback_models=[]))
    factory = session_factory()
    with factory() as db:
        with db.begin():
            _run_id, output = EscalatingAgent(db, config=cfg, llm_client=OpenRouterClient(cfg.llm, http_client=httpx.Client(transport=httpx.MockTransport(handler)))).run(PromptInput(prompt="plan"))

        assert output.answer == "strong"
        assert [call["model"] for call in calls] == ["fast-model", "reasoning-model"]
        message = db.scalar(select(AgentMessage).where(AgentMessage.agent_run_id == _run_id, AgentMessage.content.contains("Escalating query_decomposer")))
        assert message is not None
        assert "Escalating query_decomposer" in message.content
