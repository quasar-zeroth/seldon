# External retrieval adapters

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table; [agents map](../AGENTS.md) explains pipeline integration.

Adapters implement `ExternalRetrievalProvider` from [retrieval.py](../retrieval.py). They supply search metadata and fetched documents to context gathering; semantic interpretation and KB persistence live in the parent pipeline.

- `__init__.py`: provider registry and configuration-based factories. DuckDuckGo and Google News RSS are registered; names mentioned as future examples in docstrings are not implemented adapters. Construction failures currently skip that provider.
- `duckduckgo.py`: DDGS search with HTML fallback, per-domain throttling, fetch retries and readable-text extraction through trafilatura/BeautifulSoup.
- `news.py`: Google News RSS queries and article extraction, retaining publication/source metadata and falling back to the RSS headline/snippet when full text is unavailable.

Keep failed fetches distinct from empty evidence, preserve source URLs/dates and raw provenance, and derive budgets/timeouts from [config.py](../../config.py). A credential-free search provider does not remove the built-in semantic pipeline's model requirement. Use the static retrieval provider or mocked HTTP in `test_followup_c11_external_retrieval.py`, `test_followup_c11_retrieval_depth.py` and context-gathering tests under [tests/unit](../../../../tests/unit/).

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps rather than duplicating settings.
