import Link from "next/link";
import { redirect } from "next/navigation";
import { PageHeader, Card, EmptyState, EndpointList, SourceLink, StatusBadge } from "../../src/components/ui";
import { kbApi, type KBSearchParams } from "../../src/lib/api/kb";

function splitTags(value: FormDataEntryValue | null) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

async function createKBEntryAction(formData: FormData) {
  "use server";
  const content = String(formData.get("content") || "").trim();
  if (!content) return;
  const entry = await kbApi.create({
    content,
    original_snippet: String(formData.get("original_snippet") || ""),
    source_type: String(formData.get("source_type") || "user_input"),
    source_name: String(formData.get("source_name") || "Unknown"),
    source_url: String(formData.get("source_url") || "") || null,
    topics: splitTags(formData.get("topics")),
    entities: splitTags(formData.get("entities")),
    scenario_ids: splitTags(formData.get("scenario_ids")),
    perspective_tags: {
      sentiment: Number(formData.get("sentiment") || 0),
      confidence: Number(formData.get("confidence") || 0.5),
      geopolitical_lens: String(formData.get("geopolitical_lens") || "") || null,
    },
  });
  redirect(`/kb/${entry.id}`);
}

export default async function KBPage({ searchParams }: { searchParams?: KBSearchParams }) {
  const params = searchParams ?? {};
  const entries = await kbApi.search(params);

  return <>
    <PageHeader title="Knowledge Base" subtitle="Search persisted facts by semantics, provenance, time, perspective, scenario links, and supersession state." action={<a className="button" href="#create-kb-entry">Create KB entry</a>} />
    <EndpointList endpoints={["GET /kb/search?filters", "POST /kb/entries"]} />
    <Card title="Search and filters">
      <form className="kb-filter-grid">
        <input name="q" defaultValue={params.q ?? ""} placeholder="Keyword search" />
        <select name="semantic" defaultValue={params.semantic ?? ""}>
          <option value="">Keyword mode</option>
          <option value="true">Semantic search</option>
        </select>
        <input name="topic" defaultValue={params.topic ?? ""} placeholder="Topic" />
        <input name="entity" defaultValue={params.entity ?? ""} placeholder="Entity" />
        <input name="source" defaultValue={params.source ?? ""} placeholder="Source name or URL" />
        <input name="source_type" defaultValue={params.source_type ?? ""} placeholder="Source type" />
        <input name="scenario_id" defaultValue={params.scenario_id ?? ""} placeholder="Scenario ID" />
        <input name="valid_at" defaultValue={params.valid_at ?? ""} placeholder="Valid at (ISO datetime)" />
        <input name="created_since" defaultValue={params.created_since ?? ""} placeholder="Created since" />
        <input name="updated_since" defaultValue={params.updated_since ?? ""} placeholder="Updated since" />
        <input name="geopolitical_lens" defaultValue={params.geopolitical_lens ?? ""} placeholder="Geopolitical lens" />
        <input name="min_sentiment" defaultValue={params.min_sentiment ?? ""} placeholder="Min sentiment -1..1" />
        <input name="max_sentiment" defaultValue={params.max_sentiment ?? ""} placeholder="Max sentiment -1..1" />
        <input name="min_confidence" defaultValue={params.min_confidence ?? ""} placeholder="Min confidence 0..1" />
        <input name="max_confidence" defaultValue={params.max_confidence ?? ""} placeholder="Max confidence 0..1" />
        <select name="current_only" defaultValue={params.current_only ?? ""}>
          <option value="">All entries</option>
          <option value="true">Current only</option>
        </select>
        <select name="sort" defaultValue={params.sort ?? "updated_at"}>
          <option value="updated_at">Sort by updated</option>
          <option value="created_at">Sort by created</option>
          <option value="confidence">Sort by confidence</option>
          <option value="sentiment">Sort by sentiment</option>
          <option value="version">Sort by version</option>
        </select>
        <select name="order" defaultValue={params.order ?? "desc"}>
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
        <button className="button" type="submit">Apply filters</button>
        <Link className="button" href="/kb">Reset</Link>
      </form>
    </Card>
    <section className="wide-grid">
      <Card title="KB entries">
        {entries.length ? entries.map((entry) => {
          const confidence = Number(entry.perspective_tags?.confidence ?? 0);
          const sentiment = Number(entry.perspective_tags?.sentiment ?? 0);
          return <div className="stack-row" key={entry.id}>
            <div>
              <Link href={`/kb/${entry.id}`}><strong>{entry.content.slice(0, 160)}</strong></Link>
              <p className="muted">{entry.topics?.join(", ") || "untagged"} · {entry.entities?.join(", ") || "no entities"}</p>
              <p className="muted">Confidence {Math.round(confidence * 100)}% · sentiment {sentiment.toFixed(2)} · decay {Math.round((entry.decay_score ?? 0) * 100)}%</p>
              <SourceLink url={entry.source_url} name={entry.source_name} />
              <div className="pill-row">
                {entry.open_contradiction_count ? <span className="pill warning">{entry.open_contradiction_count} open contradiction(s)</span> : null}
                {entry.superseded_by ? <span className="pill warning">superseded</span> : <span className="pill">current</span>}
              </div>
            </div>
            <div className="stack-mini"><StatusBadge status={entry.superseded_by ? "superseded" : "current"} /><span className="muted">v{entry.version}</span></div>
          </div>;
        }) : <EmptyState detail="No KB entries matched the current backend filters." />}
      </Card>
      <Card title="Create KB entry">
        <form id="create-kb-entry" action={createKBEntryAction} className="form-stack">
          <textarea name="content" placeholder="Fact, observation, or summary" rows={4} required />
          <textarea name="original_snippet" placeholder="Original source snippet" rows={3} />
          <input name="source_name" placeholder="Source name" />
          <input name="source_url" placeholder="Source URL" />
          <input name="source_type" placeholder="Source type" defaultValue="user_input" />
          <input name="topics" placeholder="Topics, comma-separated" />
          <input name="entities" placeholder="Entities, comma-separated" />
          <input name="scenario_ids" placeholder="Scenario IDs, comma-separated" />
          <input name="geopolitical_lens" placeholder="Geopolitical lens" />
          <input name="sentiment" type="number" min="-1" max="1" step="0.1" defaultValue="0" />
          <input name="confidence" type="number" min="0" max="1" step="0.05" defaultValue="0.5" />
          <button className="button" type="submit">Create and inspect</button>
        </form>
      </Card>
    </section>
  </>;
}
