# Legacy file graph facade

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) explains the two storage generations.

This directory preserves the original file-backed graph/extraction API consumed by Parallax through `client.py`. It is separate from the database ERG.

- `knowledge_graph.py`: load/save a NetworkX directed graph as JSON; entity/relation updates, name/alias search, bounded related-node traversal, statistics and export.
- `entity_extractor.py`: use an injected LLM protocol to extract entities/relations from article, prediction and bet payloads, then write them to the file graph.
- `__init__.py`: public `KnowledgeGraph` and `EntityExtractor` exports.

Keep the legacy API compatible while callers migrate, preserve existing artifacts, and distinguish its graph path from database state. New database graph operations belong in [data](../data/AGENTS.md), provider-backed relationship construction in [agents](../agents/AGENTS.md), and scenario influence DAG validation in [workspace](../workspace/AGENTS.md). Test legacy behavior in [test_knowledge_graph.py](../../../tests/unit/test_knowledge_graph.py) and baseline compatibility tests.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps rather than duplicating implementation.
