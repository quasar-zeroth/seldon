"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Scenario, ScenarioDraft } from "../lib/api";

const emptyDraft: ScenarioDraft = { name: "", target_question: "", time_horizon: "", description: "" };

function fallbackScenarioName(prompt: string) {
  const cleaned = prompt.trim().replace(/\s+/g, " ");
  const horizons = Array.from(cleaned.matchAll(/\b(?:in\s+)?(\d+\s*(?:months?|years?)|a\s+year)\b/gi))
    .map((match) => match[1].toLowerCase() === "a year" ? "12 months" : match[1].toLowerCase().replace(/\s+/g, " "))
    .filter((value, index, items) => items.indexOf(value) === index);
  const priceMatch = cleaned.match(/\bprice\s+of\s+([a-zA-Z][a-zA-Z\s-]{1,60}?)(?:\s+(?:would|will|could|in\b|over\b|after\b)|$)/i);
  if (priceMatch) return `${priceMatch[1].trim().replace(/\b\w/g, (char) => char.toUpperCase())} price outlook over ${horizons.join(" and ") || "the target horizon"}`;
  const summary = cleaned
    .replace(/^(i\s+want\s+to\s+(know|understand|forecast|explore)\s+|tell\s+me\s+|what\s+(would|will|does)\s+)/i, "")
    .replace(/\b(in|over)\s+\d+\s*(months?|years?)\b/gi, "")
    .replace(/\bin\s+a\s+year\b/gi, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .split(/\s+/)
    .slice(0, 10)
    .join(" ");
  return summary || "New scenario";
}

function fallbackScopeNotes(prompt: string, name: string) {
  const cleaned = prompt.trim().replace(/\s+/g, " ");
  const priceMatch = cleaned.match(/\bprice\s+of\s+([a-zA-Z][a-zA-Z\s-]{1,60}?)(?:\s+(?:would|will|could|in\b|over\b|after\b)|$)/i);
  if (priceMatch) {
    const asset = priceMatch[1].trim().replace(/\b\w/g, (char) => char.toUpperCase());
    return `Explore the outlook for ${asset} prices across the requested horizons (6 months / 1 year). Start by establishing the current spot price and recent trend, then investigate macro drivers such as real yields, Federal Reserve policy expectations, inflation, USD strength, central-bank and ETF demand, jewellery/industrial demand, geopolitical safe-haven flows, positioning, and technical support/resistance levels. Compare plausible bull/base/bear paths for the 6-month and 12-month horizons, and note the key indicators that would confirm or invalidate each path.`;
  }
  return `Explore the scenario '${name}' over the requested horizon (6 months / 1 year). Start by clarifying the current baseline, the most important entities and metrics, relevant historical context, key drivers, constraints, downside/upside cases, and concrete signals that would help resolve or update the forecast in later phases.`;
}

function fallbackDraft(prompt: string): ScenarioDraft {
  const trimmed = prompt.trim();
  const name = fallbackScenarioName(trimmed);
  return {
    name,
    target_question: trimmed.endsWith("?") ? trimmed : `What is the likely outcome of: ${trimmed}?`,
    time_horizon: "6 months / 1 year",
    description: fallbackScopeNotes(trimmed, name),
    source_prompt: prompt,
  };
}

export function ScenarioDraftChat() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<ScenarioDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function draftScenario() {
    const text = prompt.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/scenarios/draft", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt: text }),
      });
      if (!response.ok) throw new Error(`Scenario draft failed: ${response.status}`);
      setDraft((await response.json()) as ScenarioDraft);
    } catch (err) {
      setDraft(fallbackDraft(text));
      setError("Automatic drafting failed, so I opened editable fields with your prompt preserved.");
    } finally {
      setBusy(false);
    }
  }

  async function createScenario() {
    if (!draft?.name.trim() || !draft.target_question.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const response = await fetch("/api/scenarios", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: draft.name.trim(),
          target_question: draft.target_question.trim(),
          time_horizon: draft.time_horizon.trim(),
          description: draft.description.trim(),
          original_prompt: (draft.source_prompt || prompt).trim(),
        }),
      });
      if (!response.ok) throw new Error(`Scenario creation failed: ${response.status}`);
      const scenario = (await response.json()) as Scenario;
      router.push(`/scenarios/${scenario.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCreating(false);
    }
  }

  return <div className="chat-panel" id="create">
    <div className="chat-bubble assistant">
      <strong>Describe the forecast you want to set up.</strong>
      <p className="muted">Seldon will turn it into a short scenario summary, horizon, target question, and richer scope notes to seed exploration. You can edit before creating.</p>
    </div>
    <label className="sr-only" htmlFor="scenario-prompt">Scenario prompt</label>
    <textarea
      id="scenario-prompt"
      value={prompt}
      onChange={(event) => setPrompt(event.target.value)}
      placeholder="Example: I want to understand whether gold breaks above $2,800 in the next six months, including Fed cuts, dollar strength, and central-bank demand."
      rows={5}
    />
    <div className="chat-actions">
      <button className="button" type="button" onClick={draftScenario} disabled={busy || !prompt.trim()}>{busy ? "Drafting…" : "Draft scenario"}</button>
      {draft ? <button className="button" type="button" onClick={createScenario} disabled={creating || !draft.name.trim() || !draft.target_question.trim()}>{creating ? "Creating…" : "Create scenario"}</button> : null}
    </div>
    {error ? <p className="muted warning-text">{error}</p> : null}
    {draft ? <div className="chat-bubble assistant draft-card" aria-label="Draft scenario fields">
      <strong>Draft scenario</strong>
      <div className="draft-grid">
        <label>Short summary<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>Time horizon<input value={draft.time_horizon} onChange={(event) => setDraft({ ...draft, time_horizon: event.target.value })} placeholder="e.g. 6 months" /></label>
        <label className="wide-field">Target question<textarea value={draft.target_question} onChange={(event) => setDraft({ ...draft, target_question: event.target.value })} rows={3} /></label>
        <label className="wide-field">Scope notes / exploration context<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={5} /></label>
      </div>
    </div> : null}
  </div>;
}
