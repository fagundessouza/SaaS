import Link from "next/link";
import { notFound } from "next/navigation";

import { ExplainRequirementButton } from "@/components/ExplainRequirementButton";
import { GenerateAnalysisButton } from "@/components/GenerateAnalysisButton";
import { StatusSelector } from "@/components/StatusSelector";
import { ApiError, pageFetch } from "@/lib/api";
import type {
  Analysis,
  Opportunity,
  Requirement,
  RequirementCategory,
  Tender,
  TenderItem,
} from "@/lib/types";

const CATEGORY_LABELS: Record<RequirementCategory, string> = {
  fiscal: "Regularidade fiscal",
  tecnica: "Qualificação técnica",
  economico_financeira: "Qualificação econômico-financeira",
  juridica: "Habilitação jurídica",
};

const FINDING_STATUS_LABELS: Record<string, string> = {
  met: "Atendido",
  missing: "Faltando",
  expired: "Vencido",
  needs_review: "Revisão manual",
};

const SEVERITY_STYLE: Record<string, string> = {
  blocking: "bg-red-50 text-red-700",
  warning: "bg-amber-50 text-amber-700",
  info: "bg-emerald-50 text-emerald-700",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("pt-BR");
}

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let opportunity: Opportunity;
  try {
    opportunity = await pageFetch<Opportunity>(`/v1/opportunities/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const [tender, items, requirements] = await Promise.all([
    pageFetch<Tender>(`/v1/tenders/${opportunity.tender_id}`),
    pageFetch<TenderItem[]>(`/v1/tenders/${opportunity.tender_id}/items`),
    pageFetch<Requirement[]>(`/v1/tenders/${opportunity.tender_id}/requirements`),
  ]);

  let analysis: Analysis | null = null;
  try {
    analysis = await pageFetch<Analysis>(`/v1/opportunities/${id}/analysis`);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error;
  }

  const requirementsByCategory = requirements.reduce<Record<string, Requirement[]>>(
    (acc, req) => {
      (acc[req.category] ??= []).push(req);
      return acc;
    },
    {},
  );

  return (
    <div className="space-y-8">
      <div>
        <Link href="/radar" className="text-sm text-slate-500 hover:underline">
          ← Radar
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">{tender.objeto}</h1>
        <p className="text-sm text-slate-500">
          {tender.orgao_nome} {tender.unidade_nome ? `— ${tender.unidade_nome}` : ""}
          {tender.uf ? ` — ${tender.municipio}/${tender.uf}` : ""}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-600 sm:grid-cols-4">
          <div>
            <dt className="text-xs text-slate-400">Modalidade</dt>
            <dd>{tender.modalidade}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">Valor estimado</dt>
            <dd>{tender.valor_estimado ? `R$ ${tender.valor_estimado}` : "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">Abertura</dt>
            <dd>{formatDate(tender.data_abertura_proposta)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">Encerramento</dt>
            <dd>{formatDate(tender.data_encerramento_proposta)}</dd>
          </div>
        </dl>
      </div>

      <section className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4">
        <span className="text-sm font-medium capitalize">
          Status: {opportunity.status.replace("_", " ")}
        </span>
        <StatusSelector opportunityId={opportunity.id} currentStatus={opportunity.status} />
      </section>

      {items.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-medium">Itens ({items.length})</h2>
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Descrição</th>
                  <th className="px-4 py-2 font-medium">Qtd.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.slice(0, 20).map((item) => (
                  <tr key={item.id}>
                    <td className="px-4 py-2">{item.item_number}</td>
                    <td className="px-4 py-2">{item.description}</td>
                    <td className="px-4 py-2">
                      {item.quantity ?? "—"} {item.unit_of_measure ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Dossiê (requisitos de habilitação)</h2>
          <GenerateAnalysisButton opportunityId={opportunity.id} />
        </div>

        {!analysis && (
          <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
            Nenhum dossiê gerado ainda para esta oportunidade. Clique em &quot;Gerar dossiê&quot;
            para cruzar os requisitos do edital contra suas certidões/atestados cadastrados.
          </p>
        )}

        {analysis && analysis.findings.length === 0 && (
          <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
            Nenhum requisito de habilitação foi identificado neste edital ainda.
          </p>
        )}

        {analysis && analysis.findings.length > 0 && (
          <ul className="space-y-3">
            {analysis.findings.map((finding) => (
              <li key={finding.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span className="text-xs font-medium text-slate-500">
                      {CATEGORY_LABELS[finding.category]}
                    </span>
                    <p className="text-sm">{finding.summary}</p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${SEVERITY_STYLE[finding.severity]}`}
                  >
                    {FINDING_STATUS_LABELS[finding.status] ?? finding.status}
                  </span>
                </div>
                {finding.evidence.length > 0 && (
                  <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2 text-xs text-slate-500">
                    {finding.evidence.map((ev, index) => (
                      <li key={index}>
                        {ev.description}
                        {ev.section && ` — ${ev.section}`}
                        {ev.page_start && ` (p. ${ev.page_start})`}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {Object.keys(requirementsByCategory).length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-medium">Requisitos extraídos do edital</h2>
          <div className="space-y-4">
            {Object.entries(requirementsByCategory).map(([category, reqs]) => (
              <div key={category}>
                <h3 className="mb-2 text-sm font-medium text-slate-500">
                  {CATEGORY_LABELS[category as RequirementCategory] ?? category}
                </h3>
                <ul className="space-y-2">
                  {reqs.map((req) => (
                    <li key={req.id} className="rounded-md border border-slate-200 p-3 text-sm">
                      <p>{req.description}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        {req.section} {req.page_start ? `— p. ${req.page_start}` : ""}
                      </p>
                      <ExplainRequirementButton
                        opportunityId={opportunity.id}
                        requirementId={req.id}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
