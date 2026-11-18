export type Request = <T>(
  path: string,
  method?: string,
  body?: unknown,
) => Promise<T>;
export type Engine = { key: string; name: string };
export type Defaults = { statusz: string; afa: string };
export type ParameterType = "text" | "num" | "enum" | "enummore" | "link_text";
export type Parameter = {
  name: string;
  param_type: ParameterType;
  group_name: string;
  unit: string | null;
};
export type Target = {
  key: string;
  instance?: number;
  order?: number;
  parameter?: Parameter;
};
export type Field = {
  key: string;
  label: string;
  required: boolean;
  multiple: "instances" | "ordered" | null;
  type: string;
};
export type Catalog = {
  engine: Engine;
  engines: Engine[];
  currencies: string[];
  default_currency: string;
  defaults: Defaults;
  targets: Field[];
};
export type Assignment =
  { state: "mapped"; target: Target } | { state: "unused" } | { state: null };
export type SourceColumn = {
  index: number;
  header: string;
  occurrence: number;
  sample: string | null;
  sample_source: "file" | "analysis";
  warnings: string[];
  suggestion: { target: Target; confidence: number; method: string } | null;
  assignment: Assignment | null;
  assignment_source: "template" | "auto" | null;
  status: "from_template" | "new" | "suggested" | "unmapped";
};
export type Issue = {
  code: string;
  columns?: number[];
  count?: number;
  values?: string[];
};
export type TemplateVersion = {
  id: number;
  name: string;
  version: number;
  currency?: string;
};
export type TemplateEntry = TemplateVersion & {
  template_key: string;
  versions: number;
};
export type Preparation = {
  run_id: number;
  supplier_id: number;
  engine: string;
  currency: string;
  file: {
    format: string;
    data_rows: number | null;
    source_available: boolean;
    sheet?: string | null;
    record_path?: string | null;
  };
  columns: SourceColumn[];
  template:
    | (TemplateVersion & { missing_headers: string[]; new_headers: string[] })
    | null;
  template_candidates: TemplateVersion[];
  approved_parameters: { name: string; header: string }[];
  defaults: Defaults;
  warnings: Issue[];
};
export type TemplateBody = {
  engine: string;
  currency: string;
  columns: ({ index: number } & Assignment)[];
  new_parameters: (Parameter & { approved: true })[];
  defaults: Defaults;
};
export type Validation = {
  valid: boolean;
  errors: Issue[];
  warnings: Issue[];
  fields: { key: string; status: string; rule?: string }[];
  price_missing: boolean;
};
export type Saved = TemplateVersion & {
  template_key: string;
  validation: Validation;
};
export type Supplier = { id: number; name: string };
export type Run = {
  id: number;
  supplier_id: number;
  filename: string;
  state: string;
  error: string | null;
  analysis?: { headers?: string[] };
};
type LegacyProfile = TemplateVersion & {
  kind: "import_profile" | "engine_mapping";
};
export type TemplateList = {
  templates: TemplateEntry[];
  legacy: LegacyProfile[];
};
export const loadCatalog = (api: Request, engine = "unas") =>
  api<Catalog>(
    `/imports/template-targets?engine=${encodeURIComponent(engine)}`,
  );
export const loadSuppliers = (api: Request) =>
  api<Supplier[]>("/imports/suppliers");
export const createSupplier = (api: Request, name: string) =>
  api<Supplier>("/imports/suppliers", "POST", { name });
export const loadRuns = (api: Request, offset = 0) =>
  api<Run[]>(`/imports/runs?offset=${offset}`);
export const loadRun = (api: Request, id: number) =>
  api<Run>(`/imports/runs/${id}`);
export async function uploadRun(api: Request, supplier: number, file: File) {
  const data = new FormData();
  data.append("supplier_id", String(supplier));
  data.append("purpose", "template");
  data.append("file", file);
  return api<Run>("/imports/runs", "POST", data);
}
export async function loadTemplates(
  api: Request,
  supplier: number,
): Promise<TemplateList> {
  const result = await api<TemplateEntry[] | TemplateList>(
    `/imports/suppliers/${supplier}/import-templates`,
  );
  return Array.isArray(result) ? { templates: result, legacy: [] } : result;
}
export async function loadVersions(
  api: Request,
  id: number,
): Promise<TemplateVersion[]> {
  const result = await api<TemplateVersion[] | { versions: TemplateVersion[] }>(
    `/imports/import-templates/${id}/versions`,
  );
  return Array.isArray(result) ? result : result.versions;
}
export function loadPreparation(
  api: Request,
  run: number,
  engine: string,
  currency: string,
  templateId?: number,
) {
  const query = new URLSearchParams({ engine, currency });
  if (templateId !== undefined) query.set("template_id", String(templateId));
  return api<Preparation>(`/imports/runs/${run}/template-preparation?${query}`);
}
export const validateTemplate = (
  api: Request,
  run: number,
  body: TemplateBody,
) =>
  api<Validation>(
    `/imports/runs/${run}/template-preparation/validate`,
    "POST",
    body,
  );
export const saveTemplate = (
  api: Request,
  run: number,
  name: string,
  body: TemplateBody,
  templateId?: number,
) =>
  api<Saved>("/imports/import-templates", "POST", {
    ...body,
    run_id: run,
    name,
    ...(templateId ? { template_id: templateId } : {}),
  });
export const message = (error: unknown) =>
  error instanceof Error ? error.message : "A művelet nem sikerült.";
