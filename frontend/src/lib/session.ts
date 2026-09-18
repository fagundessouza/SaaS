import "server-only";

import { cookies } from "next/headers";

/**
 * Sessão guardada em cookies httpOnly — o access/refresh token da API (JWT Bearer, ver
 * backend/core/auth) nunca é exposto ao JavaScript do navegador. Toda chamada à API acontece
 * server-side (Server Components / Route Handlers), nunca diretamente do cliente — ver
 * lib/api.ts. Isso também elimina a necessidade de CORS no backend: o navegador só fala com o
 * próprio Next.js, nunca diretamente com o FastAPI.
 */

const ACCESS_TOKEN_COOKIE = "licitacoes_access_token";
const REFRESH_TOKEN_COOKIE = "licitacoes_refresh_token";

const COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

export type Session = {
  accessToken: string;
  refreshToken: string;
};

export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  const accessToken = store.get(ACCESS_TOKEN_COOKIE)?.value;
  const refreshToken = store.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!accessToken || !refreshToken) return null;
  return { accessToken, refreshToken };
}

export async function setSession(session: Session): Promise<void> {
  const store = await cookies();
  // access_token expira em 15min (ver backend core/config.py:
  // jwt_access_token_expire_minutes) — o cookie em si dura mais (refresh cuida da renovação),
  // maxAge aqui é só housekeeping do navegador, não a fonte de verdade da expiração.
  store.set(ACCESS_TOKEN_COOKIE, session.accessToken, {
    ...COOKIE_OPTIONS,
    maxAge: 60 * 60 * 24, // 1 dia
  });
  store.set(REFRESH_TOKEN_COOKIE, session.refreshToken, {
    ...COOKIE_OPTIONS,
    maxAge: 60 * 60 * 24 * 30, // 30 dias (jwt_refresh_token_expire_days)
  });
}

export async function clearSession(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_TOKEN_COOKIE);
  store.delete(REFRESH_TOKEN_COOKIE);
}

export async function updateAccessToken(accessToken: string): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_TOKEN_COOKIE, accessToken, {
    ...COOKIE_OPTIONS,
    maxAge: 60 * 60 * 24,
  });
}

export async function getRefreshTokenValue(): Promise<string | null> {
  const store = await cookies();
  return store.get(REFRESH_TOKEN_COOKIE)?.value ?? null;
}
