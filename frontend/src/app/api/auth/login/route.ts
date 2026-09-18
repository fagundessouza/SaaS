import { NextResponse } from "next/server";

import { setSession } from "@/lib/session";
import type { LoginResponse } from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: Request) {
  const { email, password } = (await request.json()) as {
    email: string;
    password: string;
  };

  const response = await fetch(`${BACKEND_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    return NextResponse.json(
      { detail: body.detail ?? "Falha ao entrar" },
      { status: response.status },
    );
  }

  const body = (await response.json()) as LoginResponse;
  await setSession({ accessToken: body.access_token, refreshToken: body.refresh_token });

  return NextResponse.json({ ok: true });
}
