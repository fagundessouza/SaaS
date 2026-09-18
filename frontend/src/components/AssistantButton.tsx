"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";
import type { AssistantAction, AssistantMessage } from "@/lib/types";

// O assistente é "onipresente" (ver docs/UX_AND_ASSISTANT_SPEC.md) mas toda ação exige
// opportunity_id (contexto obrigatório no backend, ver domains/assistant/service.py) — extraído
// da própria rota quando o usuário está numa página de detalhe de oportunidade (/radar/<id>),
// sem precisar de um Context Provider dedicado só para isso.
const OPPORTUNITY_ROUTE = /^\/radar\/([0-9a-f-]{36})$/;

const ACTIONS: { action: AssistantAction; label: string }[] = [
  { action: "missing_requirements", label: "O que está faltando?" },
  { action: "understand_tender", label: "Entender edital" },
];

export function AssistantButton() {
  const pathname = usePathname();
  const opportunityMatch = pathname.match(OPPORTUNITY_ROUTE);
  const opportunityId = opportunityMatch?.[1] ?? null;

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function runAction(action: AssistantAction) {
    if (!opportunityId) return;
    setLoading(true);
    setError(null);
    try {
      const message = await proxyFetch<AssistantMessage>("/v1/assistant/actions", {
        method: "POST",
        body: { opportunity_id: opportunityId, action },
      });
      setMessages((prev) => [...prev, message]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {open && (
        <div className="mb-3 w-96 rounded-lg border border-slate-200 bg-white p-4 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Assistente</h2>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700">
              ✕
            </button>
          </div>

          {!opportunityId && (
            <p className="text-sm text-slate-500">
              Abra uma oportunidade no Radar para conversar sobre ela.
            </p>
          )}

          {opportunityId && (
            <>
              <div className="mb-3 flex gap-2">
                {ACTIONS.map(({ action, label }) => (
                  <button
                    key={action}
                    onClick={() => runAction(action)}
                    disabled={loading}
                    className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="max-h-80 space-y-3 overflow-y-auto">
                {messages.map((message) => (
                  <div key={message.id} className="rounded-md bg-slate-50 p-3 text-sm">
                    <p className="whitespace-pre-wrap">{message.content}</p>
                    {message.evidence_refs.length > 0 && (
                      <p className="mt-2 text-xs text-slate-500">
                        {message.evidence_refs.length} citação(ões) — ver dossiê para detalhes.
                      </p>
                    )}
                  </div>
                ))}
                {loading && <p className="text-xs text-slate-400">Pensando...</p>}
                {error && <p className="text-xs text-red-600">{error}</p>}
              </div>
            </>
          )}
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-900 text-white shadow-lg hover:bg-slate-800"
        aria-label="Abrir assistente"
      >
        💬
      </button>
    </div>
  );
}
