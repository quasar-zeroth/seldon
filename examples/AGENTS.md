# Reproducible research examples

See the [root AGENTS.md](../AGENTS.md) for the project-wide lookup table. Implementation, schemas, migrations, CLI help, and executable tests are the source of truth; example narratives are dated illustrations.

The maintained example is [gold/AGENTS.md](gold/AGENTS.md): frozen external-agent research batches applied through normal workspace services without provider calls. It demonstrates evidence, dependency graphs, research rounds, and probabilistic forecasts rather than supplying refreshed market data.

For a new research question, follow [the agent workflow](../docs/agent-workflow.md), search existing shared knowledge, and reuse entity UUIDs. The gold replay's explicitly selected demo database is a reproduction fixture, not a pattern for creating a database per live question. Keep generated databases and reports outside the source example directory.

Update relevant AGENTS.md files when examples or supported behavior make guidance missing, stale, or incorrect. Keep maps short; put reproduction details in each example's README and link them rather than duplicating them here.
