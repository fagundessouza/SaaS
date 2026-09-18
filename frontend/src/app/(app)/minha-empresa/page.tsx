import { CnpjForm } from "@/components/CnpjForm";
import { CommercialProfileForm } from "@/components/CommercialProfileForm";
import { pageFetch } from "@/lib/api";
import type { CompanyProfile } from "@/lib/types";

const ENRICHMENT_LABELS: Record<CompanyProfile["enrichment_status"], string> = {
  not_attempted: "Sem CNPJ informado",
  pending: "Enriquecendo…",
  enriched: "Enriquecido via CNPJ",
  failed: "Falha ao enriquecer",
};

export default async function CompanyProfilePage() {
  const profile = await pageFetch<CompanyProfile>("/v1/company-profile");

  return (
    <div className="space-y-8">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Minha Empresa</h1>
        <p className="text-sm text-slate-500">{profile.legal_name}</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Dados cadastrais</h2>
        <CnpjForm currentCnpj={profile.cnpj} />
        <p className="text-xs text-slate-500">
          {ENRICHMENT_LABELS[profile.enrichment_status]}
          {profile.enrichment_error && ` — ${profile.enrichment_error}`}
        </p>
        {profile.trade_name && (
          <p className="text-sm text-slate-600">Nome fantasia: {profile.trade_name}</p>
        )}
        {profile.cnaes.length > 0 && (
          <p className="text-sm text-slate-600">
            CNAEs: {profile.cnaes.map((c) => String(c.text ?? c.code ?? "")).join(", ")}
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Perfil comercial (alimenta o Radar)</h2>
        <CommercialProfileForm
          initialRegions={profile.regions}
          initialProducts={profile.products}
          initialServices={profile.services}
        />
      </section>
    </div>
  );
}
