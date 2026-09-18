import Link from "next/link";

import { apiFetch, pageFetch } from "@/lib/api";
import type { Opportunity, OpportunityStatus, Tender } from "@/lib/types";

const STATUS_LABELS: Record<OpportunityStatus, string> = {
  discovered: "Descoberta",
  under_review: "Em análise",
  qualified: "Qualificada",
  pursuing: "Em andamento",
  submitted: "Proposta enviada",
  won: "Ganha",
  lost: "Perdida",
  withdrawn: "Retirada",
};

const STATUS_FILTERS: OpportunityStatus[] = [
  "discovered",
  "under_review",
  "qualified",
  "pursuing",
  "submitted",
  "won",
  "lost",
  "withdrawn",
];

export default async function RadarPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const query = status ? `?status=${status}` : "";
  const opportunities = await pageFetch<Opportunity[]>(`/v1/opportunities${query}`);

  const tenders = await Promise.all(
    opportunities.map((opportunity) =>
      apiFetch<Tender>(`/v1/tenders/${opportunity.tender_id}`).catch(() => null),
    ),
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Radar</h1>
        <p className="text-sm text-slate-500">
          Editais compatíveis com o seu perfil, encontrados pelo funil determinístico + semântico.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link
          href="/radar"
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            !status ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"
          }`}
        >
          Todas
        </Link>
        {STATUS_FILTERS.map((s) => (
          <Link
            key={s}
            href={`/radar?status=${s}`}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              status === s ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"
            }`}
          >
            {STATUS_LABELS[s]}
          </Link>
        ))}
      </div>

      {opportunities.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
          Nenhuma oportunidade encontrada{status ? " para este status" : ""}.
        </p>
      ) : (
        <ul className="space-y-3">
          {opportunities.map((opportunity, index) => {
            const tender = tenders[index];
            const keywordMatch = opportunity.compatibility?.keyword as
              | { matched_terms?: string[] }
              | undefined;
            const semanticMatch = opportunity.compatibility?.semantic as
              | { score?: number; best_term?: string }
              | undefined;

            return (
              <li key={opportunity.id}>
                <Link
                  href={`/radar/${opportunity.id}`}
                  className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium">{tender?.objeto ?? "(edital indisponível)"}</p>
                      <p className="text-sm text-slate-500">
                        {tender?.orgao_nome} {tender?.uf ? `— ${tender.uf}` : ""}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium capitalize">
                      {STATUS_LABELS[opportunity.status]}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                    {keywordMatch?.matched_terms?.map((term) => (
                      <span key={term} className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">
                        {term}
                      </span>
                    ))}
                    {semanticMatch?.best_term && (
                      <span className="rounded-full bg-sky-50 px-2 py-0.5 text-sky-700">
                        semântico: {semanticMatch.best_term} ({(semanticMatch.score ?? 0).toFixed(2)})
                      </span>
                    )}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
