import { NextResponse } from "next/server";

import { ApiError, SessionExpiredError, apiFetch } from "@/lib/api";
import type { AssistantAction, AssistantMessage } from "@/lib/types";

export async function POST(request: Request) {
  const payload = (await request.json()) as {
    opportunity_id: string;
    action: AssistantAction;
    requirement_id?: string;
  };

  try {
    const message = await apiFetch<AssistantMessage>("/v1/assistant/actions", {
      method: "POST",
      body: payload,
    });
    return NextResponse.json(message);
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
