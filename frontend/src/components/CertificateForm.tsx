"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";
import type { RequirementCategory } from "@/lib/types";

const CATEGORY_OPTIONS: { value: RequirementCategory; label: string }[] = [
  { value: "fiscal", label: "Regularidade fiscal" },
  { value: "juridica", label: "Habilitação jurídica" },
  { value: "economico_financeira", label: "Qualificação econômico-financeira" },
];

export function CertificateForm() {
  const router = useRouter();
  const [category, setCategory] = useState<RequirementCategory>("fiscal");
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await proxyFetch("/v1/company-profile/certificates", {
        method: "POST",
        body: { category, name, expires_at: expiresAt || null },
      });
      setName("");
      setExpiresAt("");
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
        <label className="text-xs font-medium text-slate-700">Categoria</label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as RequirementCategory)}
          className="rounded-md border border-slate-300 px-2 py-2 text-sm"
        >
          {CATEGORY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
      <div className="min-w-48 flex-1 space-y-1">
        <label className="text-xs font-medium text-slate-700">Nome da certidão</label>
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Certidão Negativa de Débitos Federais"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-slate-700">Vence em (opcional)</label>
        <input
          type="date"
          value={expiresAt}
          onChange={(e) => setExpiresAt(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
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
