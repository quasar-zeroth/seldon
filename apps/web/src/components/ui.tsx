import Link from "next/link";
import type { ReactNode } from "react";

export function PageHeader({ eyebrow = "The Seldon Project", title, subtitle, status, action }: { eyebrow?: string; title: string; subtitle?: string; status?: ReactNode; action?: ReactNode }) {
  return <section className="header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle ? <p className="muted">{subtitle}</p> : null}</div><div className="header-actions">{action}{status}</div></section>;
}
export function StatusBadge({ status }: { status?: string | boolean | null }) {
  const value = typeof status === "boolean" ? (status ? "online" : "offline") : (status ?? "unknown");
  const bad = ["failed", "offline", "error", "archived"].includes(value);
  return <span className={bad ? "status bad" : "status"}>{value}</span>;
}
export function MetricCard({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) { return <div className="card metric"><span className="muted">{label}</span><strong>{value}</strong>{hint ? <small>{hint}</small> : null}</div>; }
export function EvidencePill({ id, href }: { id: string; href?: string }) { const content = <span className="pill">KB {id.slice(0, 8)}</span>; return href ? <Link href={href}>{content}</Link> : content; }
export function RunStatus({ status }: { status: string }) { return <span className={`run-status ${status}`}>{status}</span>; }
export function EmptyState({ title = "Nothing here yet", detail, action }: { title?: string; detail?: string; action?: ReactNode }) { return <div className="empty"><strong>{title}</strong>{detail ? <p className="muted">{detail}</p> : null}{action}</div>; }
export function ErrorState({ message }: { message?: string }) { return <div className="card error-card"><strong>Could not load this view.</strong><p className="muted">{message ?? "The backend did not return data for this route."}</p></div>; }
export function LoadingSkeleton({ lines = 4 }: { lines?: number }) { return <div className="card skeleton-block">{Array.from({ length: lines }).map((_, i) => <span key={i} />)}</div>; }
export function ConfirmMutationDialog({ label, children }: { label: string; children?: ReactNode }) { return <details className="confirm"><summary>{label}</summary><div className="muted">Confirm before applying a persisted backend mutation.</div>{children}</details>; }
export function AuditTrail({ items = [] }: { items?: Array<{ id?: string; action?: string; created_at?: string; entity_type?: string }> }) { return <div className="audit"><h3>Audit trail</h3>{items.length ? items.map((item, i) => <p key={item.id ?? i} className="muted">{item.created_at ?? "recorded"}: {item.entity_type ?? "record"} {item.action ?? "changed"}</p>) : <p className="muted">No audit records loaded for this view yet.</p>}</div>; }
export function SourceLink({ url, name }: { url?: string | null; name?: string | null }) { if (!url) return <span>{name ?? "No source URL"}</span>; return <a className="source-link" href={url} rel="noreferrer" target="_blank">{name ?? url}</a>; }
export function EndpointList({ endpoints }: { endpoints: string[] }) { return <p className="endpoint-note">Consumes {endpoints.map((e) => <code key={e}>{e}</code>).reduce<ReactNode[]>((acc, item, i) => i ? [...acc, ", ", item] : [item], [])}</p>; }
export function Card({ title, children }: { title: string; children: ReactNode }) { return <div className="card"><h2>{title}</h2>{children}</div>; }
