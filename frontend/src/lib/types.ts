/**
 * Tipos espelhando as respostas reais da API (ver backend/api/v1/*.py) — mantidos em sincronia
 * manual com os Pydantic response models. Só os campos realmente usados pela UI, não uma cópia
 * 1:1 de cada schema.
 */

export type SignupResponse = {
  access_token: string;
  refresh_token: string;
  tenant_id: string;
  user_id: string;
  company_profile_id: string;
};

export type LoginResponse = {
  access_token: string;
  refresh_token: string;
};

export type CurrentUser = {
  id: string;
  email: string;
  role: "owner" | "admin" | "member";
  is_active: boolean;
};

export type OpportunityStatus =
  | "discovered"
  | "under_review"
  | "qualified"
  | "pursuing"
  | "submitted"
  | "won"
  | "lost"
  | "withdrawn";

export type Opportunity = {
  id: string;
  tender_id: string;
  status: OpportunityStatus;
  assigned_to_user_id: string | null;
  created_at: string;
  compatibility: Record<string, unknown>;
  confidence: Record<string, number>;
};

export type Tender = {
  id: string;
  orgao_nome: string;
  unidade_nome: string | null;
  uf: string | null;
  municipio: string | null;
  modalidade: string;
  objeto: string;
  valor_estimado: string | null;
  data_publicacao: string | null;
  data_abertura_proposta: string | null;
  data_encerramento_proposta: string | null;
  situacao: string | null;
};

export type TenderItem = {
  id: string;
  item_number: number;
  description: string;
  material_or_service: string | null;
  quantity: number | null;
  unit_of_measure: string | null;
  unit_estimated_value: number | null;
  total_estimated_value: number | null;
};

export type RequirementCategory = "fiscal" | "tecnica" | "economico_financeira" | "juridica";

export type Requirement = {
  id: string;
  category: RequirementCategory;
  description: string;
  confidence: number;
  document_version_id: string;
  section: string | null;
  page_start: number;
  page_end: number;
};

export type FindingStatus = "met" | "missing" | "expired" | "needs_review";
export type FindingSeverity = "blocking" | "warning" | "info";
export type EvidenceKind = "requirement_text" | "certificate_data" | "attestation_data";

export type Evidence = {
  kind: EvidenceKind;
  description: string;
  document_version_id: string | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  excerpt: string | null;
  certificate_id: string | null;
  attestation_id: string | null;
};

export type Finding = {
  id: string;
  category: RequirementCategory;
  status: FindingStatus;
  severity: FindingSeverity;
  summary: string;
  evidence: Evidence[];
};

export type Analysis = {
  id: string;
  opportunity_id: string;
  generated_at: string;
  findings: Finding[];
};

export type CompanyProfile = {
  id: string;
  cnpj: string | null;
  legal_name: string;
  trade_name: string | null;
  cnaes: Array<Record<string, unknown>>;
  regions: string[];
  products: string[];
  services: string[];
  enrichment_status: "not_attempted" | "pending" | "enriched" | "failed";
  enrichment_error: string | null;
};

export type Certificate = {
  id: string;
  category: RequirementCategory;
  name: string;
  issued_at: string | null;
  expires_at: string | null;
  notes: string | null;
};

export type Attestation = {
  id: string;
  issuing_org: string;
  object_description: string;
  contract_value: string | null;
  period_start: string | null;
  period_end: string | null;
};

export type AssistantAction = "missing_requirements" | "understand_tender" | "explain_requirement";

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  action: AssistantAction | null;
  content: string;
  evidence_refs: Array<Record<string, unknown>>;
  created_at: string;
};

export type NotificationDelivery = {
  channel: "email" | "web_push";
  status: "pending" | "sent" | "delivered" | "failed" | "bounced";
  sent_at: string | null;
  error: string | null;
};

export type Alert = {
  id: string;
  topic: string;
  payload: Record<string, unknown>;
  created_at: string;
  deliveries: NotificationDelivery[];
};
