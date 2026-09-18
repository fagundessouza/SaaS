import { NextResponse } from "next/server";

import { setSession } from "@/lib/session";
import type { SignupResponse } from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: Request) {
  const payload = (await request.json()) as {
    company_name: string;
    email: string;
    password: string;
    cnpj?: string;
  };

  const response = await fetch(`${BACKEND_URL}/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    return NextResponse.json(
      { detail: body.detail ?? "Falha ao criar conta" },
      { status: response.status },
    );
  }

  const body = (await response.json()) as SignupResponse;
  await setSession({ accessToken: body.access_token, refreshToken: body.refresh_token });

  return NextResponse.json({ ok: true });
}
