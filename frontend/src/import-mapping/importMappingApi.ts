export type Request = <T>(
  path: string,
  method?: string,
  body?: unknown,
) => Promise<T>;

export type ParameterType = "text" | "num" | "enum" | "enummore" | "link_text";
export type ParameterDraft = {
  name: string;
  param_type: ParameterType;
  group_name: string;
  unit: string | null;
  approved: boolean;
};
export type Target =
  | { kind: "field"; key: string; header: string }
  | { kind: "parameter"; header: string };
export type SuggestedTarget =
  | Target
  | {
      kind: "new_parameter";
      header: string;
      parameter: Omit<ParameterDraft, "approved">;
    };
export type Registry = {
  engine_key: string;
  name: string;
  fields: {
    key: string;
    kind: "standard" | "parameter" | "auxiliary";
    label: string;
    header: string;
    required: boolean;
    internal_field: string | null;
  }[];
};
export type MappingView = {
  rows: { data_rows: number | null };
  columns: {
    index: number;
    header: string;
    samples: string[];
    warnings: string[];
    suggestion: { target: SuggestedTarget; confidence: number } | null;
    current: Target | null;
  }[];
  approved_parameters: { header: string; name: string }[];
  saved_profile: {
    version: number;
    requires_review: boolean;
    missing_headers: string[];
    new_headers: string[];
  } | null;
};
export type MappingInput = {
  engine_key: string;
  columns: { index: number; target: Target | null }[];
  new_parameters: ParameterDraft[];
  identity_target: string | null;
  financial_approved: boolean;
  vat_rate: number | null;
};
type ValidationIssue = {
  code: string;
  columns?: number[];
  count?: number;
  values?: string[];
};
export type Validation = {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  required: {
    key: string;
    header: string;
    status: "mapped" | "partial" | "fallback" | "missing";
    rule: string | null;
    rows_missing: number;
  }[];
};
export type SavedMapping = {
  profile_id: number;
  version: number;
  import_mapping: Record<string, string>;
  approval_defaults: { tax_basis?: string };
};
export type DonorCategories = {
  source_categories: {
    source_category_id: number;
    path: string | null;
    products: number;
  }[];
  products_without_source_category: number;
  donors: { emag_category_id: number; name: string | null; products: number }[];
  reference_suggestions: {
    navigation_node_id: string;
    path: string[];
    emag_category_ids: number[];
    products: number;
  }[];
};
export type DonorDiff = {
  total: number;
  covered: number;
  missing: number;
  selected: number;
  previous_selection: number[] | null;
  parameters: {
    emag_parameter_id: number;
    name: string;
    label: string;
    unit: string | null;
    mandatory: boolean;
    status: "missing" | "covered";
    covered_by: { header: string; column: number } | null;
    selected: boolean;
  }[];
};
type PreparedFields = {
  donor_parameters: { emag_category_id: number; emag_parameter_id: number }[];
};

export const mappingPath = (id: number) => `/imports/runs/${id}/column-mapping`;
const donorPath = (id: number) => `/imports/runs/${id}/donor-parameters`;
export const loadRegistry = (api: Request) =>
  api<Registry>("/imports/engines/unas/registry");
export const loadMapping = (api: Request, id: number, engine: string) =>
  api<MappingView>(`${mappingPath(id)}?engine=${encodeURIComponent(engine)}`);
export const validateMapping = (api: Request, id: number, body: MappingInput) =>
  api<Validation>(`${mappingPath(id)}/validate`, "POST", body);
export const saveMapping = (
  api: Request,
  id: number,
  body: MappingInput,
  name: string,
) => api<SavedMapping>(mappingPath(id), "POST", { ...body, name });
export const loadDonors = (api: Request, id: number) =>
  api<DonorCategories>(`/imports/runs/${id}/donor-categories`);
export const loadDiff = (api: Request, id: number, donor: number) =>
  api<DonorDiff>(`${donorPath(id)}?emag_category_id=${donor}`);
export const saveSelection = (
  api: Request,
  id: number,
  donor: number,
  mode: "set" | "all" | "none",
  ids: number[] = [],
) =>
  api<DonorDiff>(`${donorPath(id)}/selection`, "PUT", {
    emag_category_id: donor,
    mode,
    emag_parameter_ids: ids,
  });
export const loadPrepared = (api: Request, id: number) =>
  api<PreparedFields>(`/imports/runs/${id}/prepared-fields`);

// A4/A5 refer to a newly approved parameter by its UNAS header. The server
// independently regenerates and checks it against the submitted definition.
const settings: Record<ParameterType, string> = {
  text: "1|0|1|0|0|0",
  num: "1|0|0|0|0|0",
  enum: "0|0|0|0|0|0",
  enummore: "1|0|1|0|0|0",
  link_text: "2|0|0|0|0|1",
};

export function parameterHeader(draft: Omit<ParameterDraft, "approved">) {
  return `Paraméter: ${draft.name.trim()}|${draft.group_name}|${draft.param_type}|${settings[draft.param_type]}||${draft.unit ?? ""}|0|1|1`;
}

export function parseParameterHeader(header: string) {
  const prefix = "Paraméter: ";
  if (!header.startsWith(prefix)) return;
  const parts = header.slice(prefix.length).split("|");
  const [name, group = "", type = ""] = parts;
  if (!name.trim() || !Object.hasOwn(settings, type.trim())) return;
  return {
    name: name.trim(),
    group_name: group.trim(),
    param_type: type.trim() as ParameterType,
    unit: parts[10]?.trim() || null, // UNAS header position used by unas_schema.py.
  };
}

export const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "A művelet sikertelen. Próbáld újra.";
