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
  label?: string;
  instance?: number;
  order?: number;
  header?: string;
  parameter?: Parameter;
};
export type Field = {
  key: string;
  label: string;
  required: boolean;
  multiple: "instances" | "ordered" | null;
  type: string;
  unas_header?: string | null;
  min_instance?: number | null;
  max_instance?: number | null;
  added_in?: string;
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
  | { state: "mapped"; target: Target }
  | { state: "unused" }
  | { state: null };
export type SourceColumn = {
  index: number;
  header: string;
  occurrence: number;
  sample: string | null;
  sample_source: "file" | "analysis";
  warnings: string[];
  suggestion: {
    target: Target;
    confidence: number;
    method: string;
    label?: string;
  } | null;
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
  approved_parameters: { name: string; header: string; label?: string }[];
  defaults: Defaults;
  warnings: Issue[];
};
type ParameterInput = Pick<Parameter, "name"> &
  Partial<Omit<Parameter, "name">>;
type TargetInput = Omit<Target, "label" | "parameter"> & {
  parameter?: ParameterInput;
};
export type TemplateBody = {
  engine: string;
  currency: string;
  columns: ({ index: number } & (
    | Exclude<Assignment, { state: "mapped" }>
    | { state: "mapped"; target: TargetInput }
  ))[];
  new_parameters: (ParameterInput & { approved: true })[];
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
export type DeletionTarget =
  | { kind: "supplier" | "run" | "template"; id: number; name: string }
  | { kind: "version"; id: number; templateId: number; name: string };
export type DeletionPlan = {
  deletable: boolean;
  reason: string | null;
  references: Record<string, number | number[]>;
  deletes: {
    source_file_bytes?: number;
    generated_templates?: number;
    template_versions?: number;
    approved_parameters_in_deleted_versions?: number;
  };
  detaches?: { matched_uploads: number; run_ids: number[] };
};
export type Deleted = { deleted: true; version_ids?: number[] };

function deletionPath(target: DeletionTarget) {
  switch (target.kind) {
    case "supplier":
      return `/imports/suppliers/${target.id}`;
    case "run":
      return `/imports/runs/${target.id}`;
    case "template":
      return `/imports/import-templates/${target.id}`;
    case "version":
      return `/imports/import-templates/${target.templateId}/versions/${target.id}`;
  }
}

export const previewDeletion = (api: Request, target: DeletionTarget) =>
  api<DeletionPlan>(`${deletionPath(target)}/deletion`);
export const deleteImportItem = (api: Request, target: DeletionTarget) =>
  api<Deleted>(deletionPath(target), "DELETE");

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

export type ResultIssue = { code: string; target?: string };
export type TemplateResultPage = {
  template: { id: number | null; name: string; version: number | null; currency: string };
  columns: {
    header: string;
    label?: string;
    target: Target;
    source_columns: number[];
  }[];
  rows: {
    line: number;
    values: string[];
    status: "ok" | "warning" | "error";
    errors: ResultIssue[];
    warnings: ResultIssue[];
  }[];
  offset: number;
  limit: number;
  total: number;
  summary: { rows: number; exportable: number; excluded: number };
  excluded_columns: { header: string; code: string }[];
  missing_source_columns: string[];
};

const resultPath = (id: number) => `/imports/import-templates/${id}/result`;
export const loadResult = (
  api: Request,
  id: number,
  run: number,
  offset: number,
) =>
  api<TemplateResultPage>(
    `${resultPath(id)}?run_id=${run}&offset=${offset}&limit=50`,
  );
export const resultDownload = (
  id: number,
  run: number,
  format: "csv" | "xlsx",
) => `/api/v1${resultPath(id)}.${format}?run_id=${run}`;
