export const API_BASE = process.env.SELDON_API_URL ?? process.env.NEXT_PUBLIC_SELDON_API_URL ?? "http://localhost:8000";

export const BROWSER_API_BASE = process.env.NEXT_PUBLIC_SELDON_BROWSER_API_URL ?? process.env.NEXT_PUBLIC_SELDON_API_URL ?? "http://localhost:8000";

function authHeaders(): HeadersInit {
  const apiKey = process.env.SELDON_API_KEY ?? process.env.NEXT_PUBLIC_SELDON_API_KEY;
  return apiKey ? { "x-seldon-api-key": apiKey } : {};
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) throw new Error(`Seldon API ${path} failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export async function sendJson<T>(method: "POST" | "PATCH", path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Seldon API ${method} ${path} failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export async function safe<T>(loader: () => Promise<T>): Promise<{ data?: T; error?: string }> {
  try { return { data: await loader() }; } catch (error) { return { error: error instanceof Error ? error.message : String(error) }; }
}
