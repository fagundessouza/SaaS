"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export function CommercialProfileForm({
  initialRegions,
  initialProducts,
  initialServices,
}: {
  initialRegions: string[];
  initialProducts: string[];
  initialServices: string[];
}) {
  const router = useRouter();
  const [regions, setRegions] = useState(initialRegions.join(", "));
  const [products, setProducts] = useState(initialProducts.join(", "));
  const [services, setServices] = useState(initialServices.join(", "));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSaved(false);
    try {
      await proxyFetch("/v1/company-profile/commercial", {
        method: "PUT",
        body: {
          regions: parseList(regions).map((r) => r.toUpperCase()),
          products: parseList(products),
          services: parseList(services),
        },
      });
      setSaved(true);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-700">
          Regiões de atuação (UFs, separadas por vírgula — vazio = sem restrição)
        </label>
        <input
          value={regions}
          onChange={(e) => setRegions(e.target.value)}
          placeholder="RN, PB, PE"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-700">
          Produtos que vende (separados por vírgula)
        </label>
        <input
          value={products}
          onChange={(e) => setProducts(e.target.value)}
          placeholder="material de escritório, mobiliário"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-700">
          Serviços que presta (separados por vírgula)
        </label>
        <input
          value={services}
          onChange={(e) => setServices(e.target.value)}
          placeholder="manutenção predial, limpeza"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <p className="text-xs text-slate-400">
        Sem produtos/serviços declarados, o Radar não encontra nenhuma oportunidade (ver
        docs/adr — o matching precisa de algo para comparar contra o objeto do edital).
      </p>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {saved && <p className="text-sm text-emerald-600">Salvo.</p>}

      <button
        type="submit"
        disabled={loading}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {loading ? "Salvando..." : "Salvar"}
      </button>
    </form>
  );
}
