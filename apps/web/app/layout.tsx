import type { Metadata } from "next";
import { AppShell } from "../src/components/shell";
import "./styles.css";

export const metadata: Metadata = { title: "The Seldon Project", description: "Prediction intelligence mission control" };
export default function RootLayout({ children }: { children: React.ReactNode }) { return <html lang="en"><body><AppShell>{children}</AppShell></body></html>; }
