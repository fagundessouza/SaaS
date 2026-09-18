import Link from "next/link";

import { ApiError, apiFetch, pageFetch } from "@/lib/api";
import type { Analysis, Opportunity, Tender } from "@/lib/types";

// Sem endpoint de "listar todas as minhas Analysis" no backend ainda — lista as Opportunity e
// verifica quais já têm dossiê gerado (404 = ainda não gerado, tratado como "não aparece na
// lista", nunca como erro). N+1 aceitável no volume atual de um piloto, mesmo raciocínio já
// documentado em radar/page.tsx.
export default async function AnalisesPage() {
  const opportunities = await pageFetch<Opportunity[]>("/v1/opportunities?only_active=true");

  const analyses = await Promise.all(
    opportunities.map(async (opportunity) => {
      try {
        const analysis = await pageFetch<Analysis>(`/v1/opportunities/${opportunity.id}/analysis`);
        const tender = await apiFetch<Tender>(`/v1/tenders/${opportunity.tender_id}`).catch(
          () => null,
        );
        return { opportunity, analysis, tender };
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    }),
  );

  const withDossie = analyses.filter((item) => item !== null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Análises</h1>
        <p className="text-sm text-slate-500">
          Oportunidades com dossiê já gerado — acesso rápido, o conteúdo completo vive na página
          de cada oportunidade.
        </p>
      </div>

      {withDossie.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
          Nenhum dossiê gerado ainda. Abra uma oportunidade no Radar e clique em &quot;Gerar
          dossiê&quot;.
        </p>
      ) : (
        <ul className="space-y-3">
          {withDossie.map(({ opportunity, analysis, tender }) => {
            const pending = analysis.findings.filter((f) => f.status !== "met").length;
            return (
              <li key={opportunity.id}>
                <Link
                  href={`/radar/${opportunity.id}`}
                  className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400"
                >
                  <p className="font-medium">{tender?.objeto ?? "(edital indisponível)"}</p>
                  <p className="text-sm text-slate-500">
                    {analysis.findings.length} requisito(s) — {pending} pendente(s)
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
