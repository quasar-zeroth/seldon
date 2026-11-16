# Topics, attributed claims and source assessments

Parallax's **Topics** and **Sources** pages expose two shared graphs in the configured Seldon database. They are independent of the causal forecast DAG and are reused across research questions. Code in `src/seldon/workspace/perspectives/` defines the contract.

A topic is a subject such as oil passing through Hormuz. Its claims are individual attributed propositions, with publication/retrieval dates, optional validity interval, evidence IDs and source identities. Preserve incompatible reports instead of collapsing them into one current-state sentence. A publication being observed is not verification of its content.

Topic hierarchy edges point **parent → subtopic** and must be acyclic. `related` edges are symmetric cross-links, separate from the DAG and never interpreted as causal influence. Source edges represent `owns` (owner → owned), `writes_for` (writer → publication), `funds` (funder → recipient), `affiliated_with` (symmetric) and `syndicates_from` (republisher → origin). Source networks can contain reciprocal affiliations. Record citations, relationship status and effective dates; do not infer political alignment from ownership alone.

## Assessments and uncertainty

Claim confidence and source reliability are separate, nullable percentages on an assessment. An absent score means **unassessed**, not zero or fifty. Percentages are an assessor's judgments, not statistically calibrated probabilities. Seldon does not multiply, average, propagate or inherit them. A highly reliable source can be wrong; a generally unreliable source can provide verifiable evidence.

Each assessment records its assessor, assessment time, server recording time, scope, rationale and cited grounds. Claim statuses include reported, fact, disputed, refuted and retracted. **Fact** is an assessor-verified label requiring citations and a verification method, not an irreversible truth declaration or an automatic result of a high score. Explain the measurement, time period, primary records and independent corroboration where available. Never claim verification just because several sites repeat the same story. Unresolved conflicts should appear explicitly in forecasts and reports.

Source leaning is a list of contextual judgments: **dimension, position, regional/political frame, issue/context, citations**. For example, fiscal policy, labor, regional security and energy policy may differ for the same source. Western, East Asian and Middle Eastern political vocabularies are not mapped onto a universal left/right number. A source may have multiple assessments by different reviewers, times and scopes; the GUI's latest dated score is labelled with its scope and retains the full history. Assessment date governs the displayed latest judgment; recorded date breaks ties. Review differing scopes before using a score.

`origin_id` groups shared original reports; `derived_from_claim_ids` records known derivation. A repeated wire story, common press release or shared eyewitness must not count as several independent observations. Unknown independence stays unknown. Claim links express supports, contradicts and supersedes (new → old). Check that apparent conflicts concern the same definition, place and time before marking contradictions.

Claims retain their original statement, source and dates. Add a new claim and a supersedes link for a correction; only adding topic/evidence associations is allowed on an existing claim. Assessments are append-only. Profile and relationship edits retain their previous values in downloadable change events. There is no delete operation in this interface.

## Agent workflow (no model API required)

From Parallax, its installed service settings select the shared database:

```bash
uv run parallax research perspectives export --out /tmp/perspectives.json
uv run parallax research perspectives schema --out /tmp/perspectives-schema.json
uv run parallax research perspectives export --topic TOPIC_ID --depth 3 --format markdown
uv run parallax research perspectives export --source SOURCE_ID --depth 2
uv run parallax research perspectives apply /tmp/review.json
uv run parallax research perspectives index SCENARIO_ID
```

From Seldon use `uv run seldon research --db /absolute/path/to/shared.db perspectives ...`; put `--db` before the subcommand. Existing coding agents use their own search/reasoning and submit the JSON contract. No provider client is created by these commands.

Read the graph first, reuse stable IDs, then submit `PerspectiveApply` with `request_id`, the fresh **global** `base_revision`, `agent`, `reason` and any of `topics`, `sources`, `claims`, `topic_links`, `source_links`, `claim_links`, `assessments`. IDs can be stable strings or UUIDs. Omitted collections make no changes. An exact request replay is idempotent; a changed payload under the same request ID is rejected. Stale revisions must be reconciled, not blindly replaced. The schema command is authoritative for required fields and bounds.

Before researching or predicting:

1. Inspect topic claims, their temporal scope, original sources, common origins, counterclaims and corrections.
2. Resolve source identities carefully. A byline, publisher and parent company are distinct identities; a generic imported label can remain `unknown` until verified. Search aliases before creating another profile. Do not silently merge homonymous writers or companies.
3. Add supported affiliation/ownership links and scoped reliability/leaning reviews where there is evidence. Leave gaps explicit.
4. Explain how disputes affect node assessments, scenario branches and uncertainty. A review never automatically reruns a forecast.

HTTP equivalents (under the existing API authentication):

- `GET /workspace/perspectives` with optional `topic_id`, `source_id`, `depth` and `format=markdown`.
- `GET /workspace/perspectives/schema`.
- `POST /workspace/perspectives/apply`.
- `POST /workspace/perspectives/index/{scenario_id}`.
- `GET /workspace/perspectives/history/{run_id}` for the exact change event.

Parallax proxies these under `/api/research/perspectives`. Filtered views still return the global write revision. Topic neighborhood depth applies to related/hierarchy links in either direction; it does not imply causal dependence. Counterclaims/corrections remain visible across topic boundaries so filtering cannot conceal a known dispute. Source context includes bounded ownership/affiliations without pulling every unrelated claim by an owner. The GUI caps drawn nodes and says when it does so; the full exported context is retained.

## Moving between graph layers

Parallax's **Connections** page (`/connections`) starts from an entity, evidence item, topic, claim or source. Choose a maximum number of steps, then optionally another record to explain a shortest recorded path. Graph selections offer links back to Topics, Sources, the exact Knowledge entity and its research questions. Each step explains its recorded relationship. The traversal works in either direction while retaining the original edge direction and historical/disputed relationship status. No path within a bound means only that no such recorded path was found.

Source profiles can explicitly match shared research entities through `entity_ids`. Document source profiles use `kind: document` and `published_by` (document → publisher) or `authored_by` (document → writer). Keep these separate from publisher ownership and writer affiliations; a company announcement is not an independent news report. Only add an identity match after verifying it. Unreviewed imported labels stay unknown.

```bash
uv run parallax research perspectives catalog
uv run parallax research perspectives connections entity ENTITY_UUID --depth 4
uv run parallax research perspectives connections topic TOPIC_ID --depth 6 --to-kind source --to-id SOURCE_ID
```

HTTP routes are `GET /workspace/perspectives/catalog` and `GET /workspace/perspectives/connections?kind=entity&id=UUID&depth=4`, with optional `to_kind` and `to_id`. Parallax proxies both under `/api/research/perspectives`. The schema, CLI help and connections implementation define limits. Dense neighborhoods report truncation and retain a requested path at the default display limit. This navigation depth is separate from a question's upstream prediction scope.

## Existing research and predictions

The indexer creates question/entity topics and attributed claim snapshots from saved research. Shared entity/evidence IDs are reused. Source labels start as `unknown` identities; existing confidence values remain in the original evidence and are not promoted to calibrated trust or fact labels. Reindexing unchanged evidence is a no-op; evidence revisions preserve earlier claims and link replacements. Existing reports remain immutable.

Workspace applies index their scoped evidence atomically. The Python prediction coordinator indexes before forecasting and provides claim/source context to node and synthesis agents. For earlier Python pipeline stages or legacy data, run `perspectives index` after gathering evidence. External agents receive the same context in workspace exports. New forecast snapshots and knowledge revisions include relevant assessments, so a later review can make an earlier forecast's knowledge stale while its saved snapshot remains unchanged. New reports include the attributed claims and assessment history; report generation is not a fresh investigation.

Storage uses append-only `AgentRun` events with phase `perspective_graph`, plus a dedicated `Source` lock row for concurrent writers. No migration is needed. The lock row is internal bookkeeping, not a publication. Reads reconstruct records from events; this preserves complete history but is a linear scan suitable for the current local installation. If the event history grows substantially, add an indexed materialized projection while retaining events as the authoritative history. All writes share the caller's transaction and rollback behavior.
