/** CATEGORY-03B presentation props/callbacks, NOT HTTP DTOs or proposed endpoints.
 * Real adapters, permissions, server snapshots and revisions await CATEGORY-03A.
 */
export type ParameterStatus =
  | "present"
  | "missing"
  | "conflict"
  | "invalid"
  | "review"
  | "source_only"
  | "detached";
export const parameterLabels: Record<ParameterStatus, string> = {
  present: "Meglévő",
  review: "Ellenőrzést igényel",
  source_only: "Csak forrásban",
  detached: "Korábbi profilból",
  missing: "Hiányzó hely",
  conflict: "Ütközés",
  invalid: "Érvénytelen",
};
export type MatchKind = "confirmed" | "ambiguous" | "none";
export type ParameterValue = {
  raw: string | null;
  rawUnit: string | null;
  normalized: string | null;
  unit: string | null;
  source: string;
  conversionNote: string;
};
export type ParameterRow = {
  key: string;
  status: ParameterStatus;
  match: MatchKind;
  explanation: string;
  own: {
    key: string;
    title: string;
    required: boolean;
    value: ParameterValue;
  } | null;
  donor: {
    key: string;
    title: string;
    type: string;
    unit: string | null;
    required: boolean;
    constraint: string;
  } | null;
  additionalSources?: { key: string; title: string; value: ParameterValue }[];
  correction: string | null;
  aliasSuggestion: string | null;
  locked: boolean;
  canEdit: boolean;
  history: {
    when: string;
    actor: string;
    reason: string;
    before: string;
    after: string;
  }[];
};
export type ParameterProfile = {
  key: string;
  title: string;
  path: string;
  review: "approved" | "pending_review" | "unknown";
};
export type ParameterFilters = {
  search: string;
  status: "all" | ParameterStatus;
  match: "all" | MatchKind;
};
export type DiffPage = {
  rows: ParameterRow[];
  next: string | null;
  total: number;
  totalProducts: number | null;
  context: unknown;
  versionLabel: string;
  profiles: ParameterProfile[];
  activeProfileKey: string | null;
  preparation: {
    state: "unprepared" | "review" | "approved" | "stale";
    canApprove: boolean;
    explanation: string;
    audit: string;
  };
};
export type ParameterSelection = {
  handle: unknown;
  count: number;
  description: string;
};
export type ParameterIntent = {
  action:
    | "add_missing"
    | "approve_alias"
    | "edit"
    | "unlock"
    | "select_profile"
    | "approve_preparation";
  productKey: string;
  context: unknown;
  rowKey?: string;
  profileKey?: string;
  correction?: string;
  unit?: string;
  reason: string;
  selection?: ParameterSelection;
};
export type ParameterPreview = {
  origin: "server" | "local";
  handle: unknown;
  summary: string;
  canApply: boolean;
  eligible: number;
  preserved: number;
  addedEmpty: number;
  locked: number;
  conflicts: number;
  blocked: number;
  sourceOverwrites: number;
  changes: { label: string; before: string; after: string }[];
  runs: { label: string; count: number }[];
};
export type ParameterJob = {
  key: string;
  context: unknown;
  state:
    | "queued"
    | "running"
    | "paused"
    | "partial"
    | "completed"
    | "failed"
    | "cancelled"
    | "superseded";
  progressPercent: number | null;
  processed: number;
  total: number | null;
  changed: number;
  skipped: number;
  failed: number;
  message: string;
  errors: { label: string; message: string }[];
  canResume: boolean;
  canCancel: boolean;
};
export class ParameterRevisionConflict extends Error {}
export type ParameterPorts = {
  read: (
    productKey: string,
    filters: ParameterFilters,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<DiffPage>;
  values?: (
    rowKey: string,
    search: string,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<{ hasList: boolean; items: string[]; next: string | null }>;
  preview?: (
    intent: ParameterIntent,
    signal: AbortSignal,
  ) => Promise<ParameterPreview>;
  apply?: (
    preview: ParameterPreview,
    signal: AbortSignal,
  ) => Promise<{ message: string; job: ParameterJob | null }>;
  snapshot?: (
    productKey: string,
    signal: AbortSignal,
  ) => Promise<ParameterSelection>;
  job?: (key: string, signal: AbortSignal) => Promise<ParameterJob>;
  resume?: (job: ParameterJob, signal: AbortSignal) => Promise<ParameterJob>;
  cancel?: (job: ParameterJob, signal: AbortSignal) => Promise<ParameterJob>;
};
export type ParameterServices = {
  ports: ParameterPorts;
  access: {
    edit: boolean;
    unlock: boolean;
    approve: boolean;
    bulk: boolean;
    manageJobs: boolean;
  };
};
export type ParameterWorkspaceProps = ParameterServices & {
  workspaceKey: string;
  product: {
    key: string;
    title: string;
    ownCategory: string;
    internalPath: string;
  };
};
