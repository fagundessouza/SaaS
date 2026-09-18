"use client";

import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";
import type { AssistantMessage } from "@/lib/types";

export function ExplainRequirementButton({
  opportunityId,
  requirementId,
}: {
  opportunityId: string;
  requirementId: string;
}) {
  const [loading, setLoading] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      const message = await proxyFetch<AssistantMessage>("/v1/assistant/actions", {
        method: "POST",
        body: {
          opportunity_id: opportunityId,
          action: "explain_requirement",
          requirement_id: requirementId,
        },
      });
      setExplanation(message.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  if (explanation) {
    return <p className="mt-2 rounded-md bg-slate-50 p-2 text-xs text-slate-700">{explanation}</p>;
  }

  return (
    <div>
      <button
        onClick={handleClick}
        disabled={loading}
        className="text-xs font-medium text-slate-500 underline hover:text-slate-800 disabled:opacity-50"
      >
        {loading ? "Explicando..." : "Explicar com o assistente"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
