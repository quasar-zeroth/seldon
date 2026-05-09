from __future__ import annotations

from sqlalchemy import select

from seldon.agents import ContextGatheringCoordinator, InformationRetriever
from seldon.agents.contracts import QueryPlan, Subquery
from seldon.agents.retrieval import RawDocument, StaticExternalRetrievalProvider
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import KBEntry, Source
from seldon.data.repositories import ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def provider_with_gold_documents() -> StaticExternalRetrievalProvider:
    return StaticExternalRetrievalProvider(
        [
            RawDocument(
                title="Rate cuts boost gold demand",
                url="https://example.test/gold-rate-cuts",
                source_name="Example Markets",
                source_type="news_article",
                content="Advertisement\nRate cuts can boost gold demand as real yields fall. Central banks remain buyers.\nSubscribe now",
                original_snippet="Rate cuts can boost gold demand as real yields fall.",
                metadata={"section": "markets"},
            ),
            RawDocument(
                title="Oil shipping update",
                url="https://example.test/oil-shipping",
                source_name="Example Energy",
                source_type="news_article",
                content="Oil shipping rates rose after port congestion.",
            ),
            # Duplicate URL should be collapsed even if a provider returns it for multiple query variations.
            RawDocument(
                title="Rate cuts boost gold demand duplicate",
                url="https://example.test/gold-rate-cuts",
                source_name="Example Markets",
                source_type="news_article",
                content="Rate cuts can boost gold demand as real yields fall.",
            ),
        ]
    )


def test_information_retriever_uses_external_provider_variations_and_persists_raw_document_provenance():
    provider = provider_with_gold_documents()
    factory = session_factory()
    with factory() as db:
        with db.begin():
            _run_id, output = InformationRetriever(db, config=SeldonConfig(), external_providers=[provider]).run(
                QueryPlan(
                    primary_topic="gold",
                    temporal_scope="6 months",
                    topics=["gold", "rates"],
                    entities=["Federal Reserve"],
                    subqueries=[Subquery(query="gold rate cuts", topic="gold")],
                )
            )

        assert len(provider.search_queries) == 3
        assert provider.search_queries == ["gold rate cuts", "gold rate cuts latest evidence", "gold rate cuts news analysis"]
        urls = [source.url for source in output.sources]
        assert urls.count("https://example.test/gold-rate-cuts") == 1
        assert urls[0] == "https://example.test/gold-rate-cuts"
        assert "Advertisement" not in output.sources[0].content
        assert output.sources[0].topics == ["gold", "rates"]
        assert output.sources[0].source_id is not None

        source_row = db.get(Source, output.sources[0].source_id)
        assert source_row is not None
        assert source_row.url == "https://example.test/gold-rate-cuts"
        assert source_row.metadata_["provider"] == "static"
        assert source_row.metadata_["raw_document"]["content"].startswith("Advertisement")
        assert source_row.metadata_["query_variation"] == "gold rate cuts"
        assert 0 <= source_row.metadata_["relevance_score"] <= 1


def test_context_gathering_coordinator_can_ingest_mocked_external_documents_into_kb():
    provider = provider_with_gold_documents()
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold outlook",
                target_question="Will gold rise if rates are cut?",
                time_horizon="6 months",
            )
            payload = ContextGatheringCoordinator.input_from_scenario(scenario, max_subqueries=2)
            _run_id, output = ContextGatheringCoordinator(db, config=SeldonConfig(), external_retrieval_providers=[provider]).run(payload)

        assert output.retrievals[0].sources
        assert any(source.url == "https://example.test/gold-rate-cuts" for source in output.retrievals[0].sources)
        assert output.kb_entry_ids
        entries = list(db.scalars(select(KBEntry)))
        external_entries = [entry for entry in entries if entry.source_url == "https://example.test/gold-rate-cuts"]
        assert len(external_entries) == 1
        assert scenario.id in external_entries[0].scenario_ids
        assert external_entries[0].source_id is not None
        assert "Rate cuts can boost gold demand" in external_entries[0].content

        source_rows = list(db.scalars(select(Source).where(Source.url == "https://example.test/gold-rate-cuts")))
        assert source_rows
        assert any(row.metadata_.get("raw_document") for row in source_rows)
