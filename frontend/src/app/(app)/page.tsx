import Link from "next/link";

import { apiFetch, pageFetch } from "@/lib/api";
import type { Alert, Opportunity, Tender } from "@/lib/types";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("pt-BR");
}

export default async function OverviewPage() {
  const opportunities = await pageFetch<Opportunity[]>("/v1/opportunities?only_active=true");
  const recentOpportunities = opportunities.slice(0, 10);

  // N+1 deliberado por enquanto (edital não vem embutido na resposta de Opportunity, ver
  // api/v1/opportunities.py) — aceitável no volume atual de um piloto, candidato a endpoint de
  // agregação se o volume crescer. Nunca dado fabricado: se a busca falhar, o item some da
  // lista em vez de mostrar um "objeto" inventado.
  const tenders = await Promise.all(
    recentOpportunities.map((opportunity) =>
      apiFetch<Tender>(`/v1/tenders/${opportunity.tender_id}`).catch(() => null),
    ),
  );

  const alerts = await pageFetch<Alert[]>("/v1/notifications");

  return (
    <div className="space-y-8">
      <section>
        <h1 className="mb-1 text-2xl font-semibold">Visão Geral</h1>
        <p className="text-sm text-slate-500">O que mudou desde a última vez que você abriu isso.</p>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">Prazos e oportunidades ativas</h2>
        {recentOpportunities.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
            Nenhuma oportunidade ativa ainda. Declare produtos/serviços em{" "}
            <Link href="/minha-empresa" className="underline">
              Minha Empresa
            </Link>{" "}
            para o radar começar a encontrar editais compatíveis.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Edital</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Encerramento da proposta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recentOpportunities.map((opportunity, index) => {
                  const tender = tenders[index];
                  return (
                    <tr key={opportunity.id}>
                      <td className="px-4 py-3">
                        <Link href={`/radar/${opportunity.id}`} className="font-medium hover:underline">
                          {tender?.objeto ?? "(edital indisponível)"}
                        </Link>
                        <p className="text-xs text-slate-500">{tender?.orgao_nome}</p>
                      </td>
                      <td className="px-4 py-3 capitalize">{opportunity.status.replace("_", " ")}</td>
                      <td className="px-4 py-3">{formatDate(tender?.data_encerramento_proposta ?? null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">Notificações recentes</h2>
        {alerts.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 p-6 text-sm text-slate-500">
            Nenhuma notificação ainda.
          </p>
        ) : (
          <ul className="space-y-2">
            {alerts.slice(0, 5).map((alert) => (
              <li key={alert.id} className="rounded-md border border-slate-200 p-3 text-sm">
                <span className="font-medium">{alert.topic}</span>{" "}
                <span className="text-slate-500">— {formatDate(alert.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
