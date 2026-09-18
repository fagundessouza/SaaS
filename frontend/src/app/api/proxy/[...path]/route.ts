import { NextResponse } from "next/server";

import { ApiError, SessionExpiredError, apiFetch } from "@/lib/api";

/**
 * Proxy genérico para mutações disparadas por Client Components (formulários de
 * certidão/atestado, preferências de notificação, mudança de status de oportunidade, etc.) — em
 * vez de um Route Handler dedicado por endpoint. Sempre passa pelo `apiFetch` server-side (ver
 * lib/api.ts), então o token nunca é exposto ao navegador. Só usado para mutação; leituras de
 * página acontecem direto em Server Components via `apiFetch`.
 */

async function handle(request: Request, path: string[]) {
  const backendPath = `/${path.join("/")}`;
  const method = request.method as "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  const hasBody = method !== "GET" && method !== "DELETE";
  const body = hasBody ? await request.json().catch(() => undefined) : undefined;

  try {
    const data = await apiFetch<unknown>(backendPath, { method, body });
    return NextResponse.json(data ?? { ok: true });
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      return NextResponse.json({ detail: "Sessão expirada" }, { status: 401 });
    }
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Erro inesperado" }, { status: 500 });
  }
}

export async function GET(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return handle(request, (await params).path);
}
export async function POST(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return handle(request, (await params).path);
}
export async function PUT(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return handle(request, (await params).path);
}
export async function PATCH(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return handle(request, (await params).path);
}
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return handle(request, (await params).path);
}
