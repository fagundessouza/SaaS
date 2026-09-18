import { AttestationForm } from "@/components/AttestationForm";
import { CertificateForm } from "@/components/CertificateForm";
import { DeleteButton } from "@/components/DeleteButton";
import { pageFetch } from "@/lib/api";
import type { Attestation, Certificate, RequirementCategory } from "@/lib/types";

const CATEGORY_LABELS: Record<RequirementCategory, string> = {
  fiscal: "Regularidade fiscal",
  tecnica: "Qualificação técnica",
  economico_financeira: "Qualificação econômico-financeira",
  juridica: "Habilitação jurídica",
};

function formatDate(value: string | null): string {
  if (!value) return "sem vencimento";
  return new Date(value).toLocaleDateString("pt-BR");
}

function isExpired(value: string | null): boolean {
  if (!value) return false;
  return new Date(value) < new Date();
}

export default async function DocumentsPage() {
  const [certificates, attestations] = await Promise.all([
    pageFetch<Certificate[]>("/v1/company-profile/certificates"),
    pageFetch<Attestation[]>("/v1/company-profile/attestations"),
  ]);

  return (
    <div className="space-y-10">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Documentos</h1>
        <p className="text-sm text-slate-500">
          Certidões e atestados usados pelo dossiê (Análises) para cruzar contra os requisitos de
          cada edital.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Certidões</h2>
        <CertificateForm />
        {certificates.length === 0 ? (
          <p className="text-sm text-slate-500">Nenhuma certidão cadastrada ainda.</p>
        ) : (
          <ul className="space-y-2">
            {certificates.map((cert) => (
              <li
                key={cert.id}
                className="flex items-center justify-between rounded-md border border-slate-200 p-3 text-sm"
              >
                <div>
                  <p className="font-medium">{cert.name}</p>
                  <p className="text-xs text-slate-500">
                    {CATEGORY_LABELS[cert.category]} —{" "}
                    <span className={isExpired(cert.expires_at) ? "text-red-600" : ""}>
                      {isExpired(cert.expires_at) ? "vencida em " : "válida até "}
                      {formatDate(cert.expires_at)}
                    </span>
                  </p>
                </div>
                <DeleteButton path={`/v1/company-profile/certificates/${cert.id}`} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Atestados de capacidade técnica</h2>
        <AttestationForm />
        {attestations.length === 0 ? (
          <p className="text-sm text-slate-500">Nenhum atestado cadastrado ainda.</p>
        ) : (
          <ul className="space-y-2">
            {attestations.map((att) => (
              <li
                key={att.id}
                className="flex items-center justify-between rounded-md border border-slate-200 p-3 text-sm"
              >
                <div>
                  <p className="font-medium">{att.issuing_org}</p>
                  <p className="text-xs text-slate-500">{att.object_description}</p>
                </div>
                <DeleteButton path={`/v1/company-profile/attestations/${att.id}`} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
