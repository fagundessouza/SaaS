export default function LegalPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Jurídico</h1>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center">
        <p className="font-medium text-slate-700">Ainda não implementado</p>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
          Esta tela depende da Fase 12 do roadmap (Legal Intelligence + Pricing Engine), que
          exige uma base jurídica curada e versionada antes de existir — sem isso, mostrar
          qualquer conteúdo aqui seria risco de alucinação sem mitigação (ver ADR-0006). Nenhum
          conteúdo jurídico é exibido até essa base existir de verdade.
        </p>
      </div>
    </div>
  );
}
