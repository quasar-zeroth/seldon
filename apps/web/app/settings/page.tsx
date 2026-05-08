import { revalidatePath } from "next/cache";
import { PageHeader, Card, EndpointList, StatusBadge, MetricCard, EmptyState } from "../../src/components/ui";
import { settingsApi } from "../../src/lib/api";
import type { ModelConfig } from "../../src/lib/api/types";

const profiles = ["fast", "balanced", "reasoning", "embedding"] as const;

async function updateProfilesAction(formData: FormData) {
  "use server";
  await settingsApi.patchModelConfig({
    profiles: Object.fromEntries(profiles.map((profile) => [profile, String(formData.get(profile) || "").trim()]).filter(([, model]) => model)),
    fallback_models: String(formData.get("fallback_models") || "").split("\n").map((item) => item.trim()).filter(Boolean),
  });
  revalidatePath("/settings");
}

async function updateAgentAction(formData: FormData) {
  "use server";
  const agent = String(formData.get("agent") || "");
  if (!agent) return;
  const maxTokens = String(formData.get("max_tokens") || "").trim();
  const temperature = String(formData.get("temperature") || "").trim();
  await settingsApi.patchModelConfig({
    agents: {
      [agent]: {
        model_profile: String(formData.get("model_profile") || "balanced"),
        model: String(formData.get("model") || "").trim() || null,
        temperature: temperature ? Number(temperature) : null,
        max_tokens: maxTokens ? Number(maxTokens) : null,
      },
    },
  });
  revalidatePath("/settings");
}

function pretty(value: unknown) {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function StatusRows({ title, rows }: { title: string; rows?: Record<string, unknown> }) {
  return <Card title={title}>{rows ? Object.entries(rows).map(([key, value]) => <div className="row" key={key}><span>{key.replaceAll("_", " ")}</span><span className="muted">{pretty(value)}</span></div>) : <EmptyState detail="Backend did not return status for this setting." />}</Card>;
}

function AgentOverrideForm({ config }: { config: ModelConfig }) {
  const firstAgent = Object.keys(config.agents)[0] ?? "";
  return <form action={updateAgentAction} className="form-stack">
    <select name="agent" defaultValue={firstAgent}>{Object.keys(config.agents).map((agent) => <option key={agent} value={agent}>{agent}</option>)}</select>
    <select name="model_profile" defaultValue="balanced">{profiles.map((profile) => <option key={profile} value={profile}>{profile}</option>)}</select>
    <input name="model" placeholder="Optional direct model override, e.g. openrouter/auto" />
    <input name="temperature" type="number" min="0" max="2" step="0.05" placeholder="Optional temperature 0-2" />
    <input name="max_tokens" type="number" min="1" step="1" placeholder="Optional max tokens" />
    <button className="button" type="submit">Update agent override</button>
  </form>;
}

export default async function SettingsPage() {
  const [health, config, status] = await Promise.all([settingsApi.health(), settingsApi.modelConfig(), settingsApi.configStatus()]);
  const effectiveStatus = config.status ?? status;
  return <>
    <PageHeader title="Settings" subtitle="Runtime-editable model profiles, agent overrides, source/backend status, and secret-safe configuration visibility." status={<StatusBadge status={health.ok} />} />
    <EndpointList endpoints={["GET /health", "GET /config/models", "PATCH /config/models", "GET /config/status"]} />
    <section className="grid">
      <MetricCard label="Backend service" value={health.service} hint={`Default model ${health.llm_default_model}`} />
      <MetricCard label="Auth required" value={pretty(effectiveStatus.auth?.api_key_required)} hint="Secret values are never exposed." />
      <MetricCard label="Persistence" value={pretty(effectiveStatus.persistence_backend?.kind)} hint={pretty(effectiveStatus.persistence_backend?.sqlite_path)} />
      <MetricCard label="Vector backend" value={pretty(effectiveStatus.vector_backend?.kind)} hint={pretty(effectiveStatus.vector_backend?.index_path)} />
    </section>

    <section className="wide-grid">
      <Card title="Runtime-editable model profiles">
        <form action={updateProfilesAction} className="form-stack">
          {profiles.map((profile) => <label key={profile} className="form-stack"><span className="muted">{profile}</span><input name={profile} defaultValue={config.profiles[profile]} required /></label>)}
          <label className="form-stack"><span className="muted">Fallback models, one per line</span><textarea name="fallback_models" defaultValue={config.fallback_models.join("\n")} rows={4} /></label>
          <button className="button" type="submit">Save model profiles</button>
        </form>
      </Card>
      <Card title="Agent-specific overrides">
        <AgentOverrideForm config={config} />
        <div className="settings-table">{Object.entries(config.agents).map(([agent, settings]) => <div className="row" key={agent}><span>{agent}</span><span className="muted">profile {settings.model_profile}{settings.model ? ` · ${settings.model}` : ""}{settings.temperature != null ? ` · temp ${settings.temperature}` : ""}{settings.max_tokens != null ? ` · max ${settings.max_tokens}` : ""}</span></div>)}</div>
      </Card>
      <StatusRows title="Source configuration/status" rows={effectiveStatus.source_configuration} />
      <StatusRows title="Persistence backend status" rows={effectiveStatus.persistence_backend} />
      <StatusRows title="Vector backend status" rows={effectiveStatus.vector_backend} />
      <StatusRows title="Auth/API-key status" rows={effectiveStatus.auth} />
      <Card title="Runtime vs deploy-time settings">
        <h3>Runtime editable</h3>
        <div className="pill-row">{effectiveStatus.runtime_editable.map((item) => <span className="pill" key={item}>{item}</span>)}</div>
        <h3>Deploy-time / environment controlled</h3>
        <div className="pill-row">{effectiveStatus.deploy_time.map((item) => <span className="pill warning" key={item}>{item}</span>)}</div>
      </Card>
    </section>
  </>;
}
