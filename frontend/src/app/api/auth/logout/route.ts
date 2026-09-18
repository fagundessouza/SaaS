import { NextResponse } from "next/server";

import { clearSession, getRefreshTokenValue } from "@/lib/session";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST() {
  const refreshToken = await getRefreshTokenValue();

  if (refreshToken) {
    // Revoga o refresh token no backend (best-effort — mesmo se falhar, a sessão local é
    // limpa de qualquer forma, o usuário não pode ficar preso "logado" no navegador).
    await fetch(`${BACKEND_URL}/v1/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    }).catch(() => undefined);
  }

  await clearSession();
  return NextResponse.json({ ok: true });
}
