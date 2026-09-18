"use client";

/** Helper para Client Components chamarem o proxy (ver app/api/proxy/[...path]/route.ts) —
 * nunca chama o backend FastAPI diretamente, sempre o próprio Next.js (mesma origem, sem CORS,
 * token nunca chega ao navegador). */
export async function proxyFetch<T>(
  path: string,
  options: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(`/api/proxy${path}`, {
    method: options.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Erro ${response.status}`);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
