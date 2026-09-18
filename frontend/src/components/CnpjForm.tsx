"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";

export function CnpjForm({ currentCnpj }: { currentCnpj: string | null }) {
  const router = useRouter();
  const [cnpj, setCnpj] = useState(currentCnpj ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await proxyFetch("/v1/company-profile/cnpj", { method: "PUT", body: { cnpj } });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2">
      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-700">CNPJ</label>
        <input
          value={cnpj}
          onChange={(e) => setCnpj(e.target.value)}
          placeholder="00.000.000/0000-00"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={loading}
        className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
      >
        {loading ? "Enviando..." : "Atualizar e enriquecer"}
      </button>
      {error && <span className="text-sm text-red-600">{error}</span>}
    </form>
  );
}
