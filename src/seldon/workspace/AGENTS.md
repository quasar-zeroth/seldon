# External-agent research workspace

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) covers storage ownership. [agent-workflow.md](../../../docs/agent-workflow.md) is the operational handoff.

Agents with shell or HTTP tools supply research and semantic reasoning using their existing sessions. Seldon validates/persists submissions without calling a model provider, using the existing scenario/KB/ERG/run/prediction tables and shared entity UUIDs.

| File/directory | Logic |
| --- | --- |
| `schemas.py` | Start/apply contracts, evidence/research/node/edge/forecast structures, graph scope and validation bounds. |
| `cases.py` | Shared bounds-first hot-take instructions, conditional stress-bound contracts and Markdown rendering. |
| `service.py` | Question creation, revision/replay checks, transactional mutations, DAG/forecast gates, JSON and Markdown exports. |
| `cli.py`, `api.py`, `__init__.py` | `seldon research` commands, HTTP routes sharing host sessions/authentication, package boundary. |
| `knowledge.py` | Tagged/paginated library search, bounded upstream dependency scope, knowledge revision and frozen graph/evidence snapshots. |
| `pipeline.py` | Shared stage/history/output projection across built-in and external-agent runs. |
| `reruns.py` | Durable external-agent forecast requests, completion and history combining external forecasts with Python prediction versions. |
| `reports.py` | Immutable summary/detailed report bundles and optional text attachments stored in `AgentRun` rows. |
| [perspectives/](perspectives/AGENTS.md) | Attributed claims, topic/source graphs, scoped trust/leaning and explained cross-layer connections. |
| [cycles/](cycles/AGENTS.md) | Cycle factors, dated series, deterministic harmonic/oscillator fits, composites, SVG charts and linked forecast priors. |

Start questions with `StartRequest` through CLI, HTTP or the GUI proxy. Exports include a derived handoff identifying the scenario and actual database; host-specific instructions stay outside the knowledge revision. Markdown leads with recorded findings, gaps and node assessments before the complete audit payload. Current-state investigations may stop with sourced findings and gaps without fabricating a forecast.

Influence edges run upstream driver to downstream effect. Reject cycles, dangling references, stale revisions, invalid probabilities and out-of-scope citations. Bounded research saturation is not omniscience; budget stops retain gaps. Preserve fact/assumption distinctions, source dates, unknowns, node forecasts, synthesis and adversarial checks. Replays must not duplicate evidence/predictions, and detachments preserve shared records/history while removing incident scenario edges explicitly.

New research forecasts construct evidence-backed lower/upper hot takes before central cases. Conditional stress bounds have assumptions and scoped citations, not additional probability mass or guaranteed coverage; tail branches still cover outcomes beyond them. Legacy submissions may omit bounds, and replay hashes/history remain compatible. Reports display saved bounds before central branches.

Search the library and reuse UUIDs/provenance before creating records; tag creates/updates and distinguish physical campuses from programmes. Shared factual edits use `allow_shared_updates` after affected uses are reviewed. This is an auditable intent flag, not an extra user-approval requirement. Preserve memberships and frozen forecast snapshots. GUI and prediction agents use the same scoped view; take scope bounds from `GraphScope`.

Accepted external stages are recorded atomically; older runs are projected from recorded input/output. Never invent completion or duration. Pending rerun requests need an executing agent and are not completed forecasts. Reports derive only from saved scoped research, preserve dated forecast versions/unknowns, and do not claim fresh searches. Generated report history is independent of submitted attachment limits and must not be truncated to fit them. New perspective assessments enter current context/new snapshots without overwriting old reports or establishing truth automatically.

`knowledge.scoped_graph` adds cycle priors for factors/composites linked to scoped entity UUIDs or selected by the topic relevance lookup; snapshots and revisions omit the key when nothing applies. Handoffs and rerun prompts include the shared cycle guidance: use every inherited cycle, and add cycles when patterns emerge. New workspace capabilities ship as skills (CLI + HTTP + `skills/<name>/SKILL.md`); see the [skill contract](../../../skills/AGENTS.md).

Verification: [test_agent_workspace.py](../../../tests/unit/test_agent_workspace.py), [test_workspace_reports.py](../../../tests/unit/test_workspace_reports.py) and perspective tests exercise real local database transactions without providers/network.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep this map concise; move growing procedures into focused linked docs or child maps instead of expanding contracts/settings here.
