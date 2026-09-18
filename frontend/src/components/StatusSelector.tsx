"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";
import type { OpportunityStatus } from "@/lib/types";

// Mesmas transicoes validadas no backend (ver domains/procurement/opportunities/service.py,
// _ALLOWED_TRANSITIONS) — replicado aqui só para desenhar os botões certos; a validação real
// (fonte da verdade) acontece no servidor, um clique num botão indevido simplesmente falha.
const NEXT_STATUS: Partial<Record<OpportunityStatus, OpportunityStatus[]>> = {
  discovered: ["under_review", "withdrawn"],
  under_review: ["qualified", "withdrawn"],
  qualified: ["pursuing", "withdrawn"],
  pursuing: ["submitted", "withdrawn"],
  submitted: ["won", "lost"],
};

const LABELS: Record<OpportunityStatus, string> = {
  discovered: "Descoberta",
  under_review: "Em análise",
  qualified: "Qualificada",
  pursuing: "Em andamento",
  submitted: "Proposta enviada",
  won: "Ganha",
  lost: "Perdida",
  withdrawn: "Retirada",
};

export function StatusSelector({
  opportunityId,
  currentStatus,
}: {
  opportunityId: string;
  currentStatus: OpportunityStatus;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextOptions = NEXT_STATUS[currentStatus] ?? [];

  async function transition(status: OpportunityStatus) {
    setLoading(true);
    setError(null);
    try {
      await proxyFetch(`/v1/opportunities/${opportunityId}/status`, {
        method: "PATCH",
        body: { status },
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  if (nextOptions.length === 0) return null;

  return (
    <div className="flex items-center gap-2">
      {nextOptions.map((status) => (
        <button
          key={status}
          onClick={() => transition(status)}
          disabled={loading}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          Marcar como {LABELS[status]}
        </button>
      ))}
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}
