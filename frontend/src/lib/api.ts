import "server-only";

import { redirect } from "next/navigation";

import { clearSession, getSession, setSession, updateAccessToken } from "@/lib/session";

/**
 * Cliente HTTP server-side para a API FastAPI (ver backend/api/main.py). Nunca chamado do
 * navegador — todo componente que precisa de dado da API é um Server Component, ou passa por um
 * Route Handler (ver app/api/*) quando precisa reagir a uma ação do usuário (formulário,
 * assistente). O token de acesso nunca trafega para o cliente.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** Levantada quando o access token expirou e o refresh também falhou — quem chama deve
 * redirecionar para /login (a sessão não pode ser renovada silenciosamente). */
export class SessionExpiredError extends Error {}

async function refreshAccessToken(refreshToken: string): Promise<string | null> {
  const response = await fetch(`${BACKEND_URL}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });

  if (!response.ok) return null;

  const body = (await response.json()) as {
    access_token: string;
    refresh_token: string;
  };
  // O refresh token é rotacionado a cada uso (revogado no uso, ver
  // backend/core/auth — nunca reaproveitável) — grava o par novo inteiro, não só o access token.
  await setSession({ accessToken: body.access_token, refreshToken: body.refresh_token });
  return body.access_token;
}

type ApiFetchOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Quando true, não anexa Authorization nem tenta renovar sessão (ex.: signup/login). */
  anonymous?: boolean;
};

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { method = "GET", body, anonymous = false } = options;

  const doFetch = async (accessToken: string | null): Promise<Response> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  };

  if (anonymous) {
    const response = await doFetch(null);
    return parseResponse<T>(response);
  }

  const session = await getSession();
  if (!session) throw new SessionExpiredError();

  let response = await doFetch(session.accessToken);

  if (response.status === 401) {
    const newAccessToken = await refreshAccessToken(session.refreshToken);
    if (!newAccessToken) {
      await clearSession();
      throw new SessionExpiredError();
    }
    await updateAccessToken(newAccessToken);
    response = await doFetch(newAccessToken);
  }

  return parseResponse<T>(response);
}

/** Para uso em Server Components de página (nunca em Route Handlers — lá o chamador precisa do
 * throw para devolver 401 em JSON). redirect() é o mecanismo do próprio Next para abortar a
 * renderização e navegar; ele não aparece como erro não tratado no log do servidor, diferente de
 * deixar SessionExpiredError propagar sem captura. */
export async function pageFetch<T>(path: string, options?: ApiFetchOptions): Promise<T> {
  try {
    return await apiFetch<T>(path, options);
  } catch (error) {
    if (error instanceof SessionExpiredError) redirect("/login");
    throw error;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // corpo não-JSON (ex.: erro de proxy) — mantém o statusText.
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}
