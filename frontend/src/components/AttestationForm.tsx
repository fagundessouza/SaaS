"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";

export function AttestationForm() {
  const router = useRouter();
  const [issuingOrg, setIssuingOrg] = useState("");
  const [objectDescription, setObjectDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await proxyFetch("/v1/company-profile/attestations", {
        method: "POST",
        body: { issuing_org: issuingOrg, object_description: objectDescription },
      });
      setIssuingOrg("");
      setObjectDescription("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-white p-4">
      <div className="space-y-1">
        <label className="text-xs font-medium text-slate-700">Órgão/cliente emissor</label>
        <input
          required
          value={issuingOrg}
          onChange={(e) => setIssuingOrg(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <div className="min-w-64 flex-1 space-y-1">
        <label className="text-xs font-medium text-slate-700">O que foi atestado</label>
        <input
          required
          value={objectDescription}
          onChange={(e) => setObjectDescription(e.target.value)}
          placeholder="Desenvolvimento de sistema de software sob medida"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={loading}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {loading ? "Adicionando..." : "Adicionar"}
      </button>
      {error && <p className="w-full text-sm text-red-600">{error}</p>}
    </form>
  );
}
