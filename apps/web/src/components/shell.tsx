import Link from "next/link";
import type { ReactNode } from "react";
const nav = [["/", "Mission Control"], ["/scenarios", "Scenarios"], ["/kb", "KB"], ["/graph", "Graph"], ["/runs", "Runs"], ["/calibration", "Calibration"], ["/settings", "Settings"]] as const;
export function AppShell({ children }: { children: ReactNode }) {
  return <><aside className="app-shell"><Link className="brand" href="/">Seldon</Link><nav>{nav.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}</nav></aside><main>{children}</main></>;
}
