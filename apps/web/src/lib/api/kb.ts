import { getJson } from "./client";
import type { KBEntry } from "./types";
export const kbApi = { search: (query = "") => getJson<KBEntry[]>(`/kb/search${query ? `?q=${encodeURIComponent(query)}` : ""}`), get: (id: string) => getJson<KBEntry>(`/kb/entries/${id}`), versions: (id: string) => getJson<Record<string, unknown>[]>(`/kb/entries/${id}/versions`) };
