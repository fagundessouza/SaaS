export default function CompetitiveIntelligencePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Inteligência Competitiva</h1>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center">
        <p className="font-medium text-slate-700">Ainda não implementado</p>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
          Esta tela depende da Fase 13 do roadmap (Competitive Intelligence —{" "}
          <code>Competitor</code>/<code>CompetitorHistory</code>), que exige dado real de
          histórico de licitações de pelo menos um cliente piloto para ter algum valor. Nenhum
          dado é mostrado aqui até essa fase existir — nunca um número inventado.
        </p>
      </div>
    </div>
  );
}
