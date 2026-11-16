/** Published CATEGORY-03A wire contract, PR #26 c05746d. Validation is additive. */
type Decoder<T> = (value: unknown) => T;
const invalid = (): never => {
  throw new Error(
    "A paraméter-API válasza nem értelmezhető. Töltsd újra a friss adatokat; a művelet eredménye nem igazolható.",
  );
};
const text: Decoder<string> = (v) => (typeof v === "string" ? v : invalid());
const bool: Decoder<boolean> = (v) => (typeof v === "boolean" ? v : invalid());
const count: Decoder<number> = (v) =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : invalid();
const id: Decoder<number> = (v) => {
  const n = count(v);
  return n > 0 ? n : invalid();
};
const decimal: Decoder<string | number> = (v) =>
  typeof v === "number" && Number.isFinite(v) && v > 0
    ? v
    : typeof v === "string" &&
        /^\d+(?:\.\d+)?$/.test(v) &&
        Number.isFinite(Number(v)) &&
        Number(v) > 0
      ? v
      : invalid();
const nullable =
  <T>(decode: Decoder<T>): Decoder<T | null> =>
  (v) =>
    v === null ? null : decode(v);
const optional =
  <T>(decode: Decoder<T>): Decoder<T | undefined> =>
  (v) =>
    v === undefined ? undefined : decode(v);
const enumeration =
  <T extends string>(...choices: T[]): Decoder<T> =>
  (v) =>
    typeof v === "string" && choices.includes(v as T) ? (v as T) : invalid();
const array =
  <T>(decode: Decoder<T>, max = 10000): Decoder<T[]> =>
  (v) =>
    Array.isArray(v) && v.length <= max ? v.map(decode) : invalid();
const shape =
  <T extends Record<string, Decoder<unknown>>>(
    fields: T,
  ): Decoder<{ [K in keyof T]: ReturnType<T[K]> }> =>
  (value) => {
    if (typeof value !== "object" || !value || Array.isArray(value))
      return invalid();
    const obj = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [key, decode] of Object.entries(fields))
      out[key] = decode(obj[key]);
    return out as { [K in keyof T]: ReturnType<T[K]> };
  };
export const slotStates = [
  "present",
  "missing",
  "review",
  "conflict",
  "invalid",
  "source_only",
  "detached",
] as const;
export const profileState = enumeration(
  "ready",
  "choice_required",
  "pending_review",
  "none",
);
const slotState = enumeration(...slotStates);
const source = shape({
  key: text,
  kind: enumeration("attribute", "field"),
  header: text,
  label: text,
  unit: nullable(text),
  raw: nullable(text),
  run_id: id,
  line: count,
  present: bool,
});
const candidate: Decoder<{
  slot_key?: string;
  emag_parameter_id?: number;
  name?: string;
  reason?: string;
  source_key?: string;
  header?: string;
  raw?: string | null;
  value?: string | null;
  unit?: string | null;
}> = (value) => {
  if (typeof value !== "object" || !value) return invalid();
  if ("source_key" in value && "raw" in value)
    return shape({ source_key: text, header: text, raw: nullable(text) })(
      value,
    );
  if ("source_key" in value)
    return shape({
      source_key: text,
      value: nullable(text),
      unit: nullable(text),
    })(value);
  return shape({
    slot_key: text,
    emag_parameter_id: id,
    name: text,
    reason: text,
  })(value);
};
export const decodeSlot = shape({
  slot_key: text,
  emag_parameter_id: nullable(id),
  name: text,
  label: nullable(text),
  target_unit: nullable(text),
  mandatory: bool,
  is_filter: nullable(bool),
  allow_new_value: nullable(bool),
  state: slotState,
  state_label: text,
  origin: enumeration("source", "alias", "added_slot", "user"),
  reason_codes: array(text, 100),
  value: nullable(text),
  unit: nullable(text),
  value_id: nullable(id),
  unit_conversion: nullable(
    shape({ from: text, to: text, factor: decimal, raw_number: text }),
  ),
  sources: array(source, 1000),
  candidates: array(candidate, 1000),
  alias: nullable(
    shape({ id, version: id, scope: enumeration("tenant", "global") }),
  ),
  locked: bool,
  donor_emag_category_id: nullable(id),
  catalog_version_id: nullable(id),
  rule_version: nullable(text),
  updated_by: nullable(id),
  updated_at: nullable(text),
  pending_source: optional(array(source, 1000)),
});
const summaryFields = {
  create: count,
  update: count,
  remove: count,
  keep: count,
  blocked_locked: count,
};
const parameterFields = {
  product_id: id,
  revision: id,
  classification: shape({
    navigation_node_id: nullable(text),
    donor_emag_category_id: nullable(id),
    parameter_profile_state: profileState,
  }),
  catalog_version_id: nullable(id),
  rule_version: nullable(text),
  slots: array(decodeSlot),
  capabilities: shape({ edit: bool }),
};
export const decodeParameters = shape(parameterFields);
const short = nullable(
  shape({ state: slotState, value: nullable(text), unit: nullable(text) }),
);
export const decodePreview = shape({
  ...parameterFields,
  summary: shape(summaryFields),
  changes: array(
    shape({
      slot_key: text,
      change: enumeration(
        "create",
        "update",
        "remove",
        "keep",
        "blocked_locked",
      ),
      before: short,
      after: short,
    }),
  ),
});
export const decodeApplied = shape({
  ...parameterFields,
  applied: shape(summaryFields),
});
const countsFields = Object.fromEntries(
  slotStates.map((k) => [k, count]),
) as Record<(typeof slotStates)[number], Decoder<number>>;
export const decodeOverview = shape({
  items: array(
    shape({
      product_id: id,
      revision: id,
      name: nullable(text),
      sku: nullable(text),
      navigation_node_id: nullable(text),
      navigation_path: nullable(array(text, 50)),
      donor_emag_category_id: nullable(id),
      parameter_profile_state: profileState,
      counts: shape(countsFields),
      mandatory_missing: count,
      prepared: bool,
      rule_version: nullable(text),
      catalog_version_id: nullable(id),
    }),
    100,
  ),
  next_cursor: nullable(id),
  state_labels: shape(
    Object.fromEntries(slotStates.map((k) => [k, text])) as Record<
      (typeof slotStates)[number],
      Decoder<string>
    >,
  ),
});
export const decodeAlias = shape({
  id,
  version: id,
  scope: enumeration("tenant", "global"),
  state: enumeration("approved", "revoked"),
  label: text,
  label_key: text,
  unit: nullable(text),
  emag_parameter_id: id,
  scope_emag_category_id: id,
  reason: nullable(text),
  decided_by: nullable(id),
  decided_at: nullable(text),
});
export const decodeAliases = shape({
  items: array(decodeAlias, 100),
  next_cursor: nullable(id),
});
export const decodeScope = shape({
  source_category_id: nullable(id),
  navigation_node_id: nullable(text),
  supplier_id: nullable(id),
});
// Early jobs return an empty states dictionary. Decode its known counters without inventing missing zeros.
const jobStates: Decoder<
  Partial<Record<(typeof slotStates)[number], number>>
> = (v) => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return invalid();
  const out: Partial<Record<(typeof slotStates)[number], number>> = {};
  for (const key of slotStates)
    if (key in v) out[key] = count((v as Record<string, unknown>)[key]);
  return out;
};
const runLimit: Decoder<number> = (v) => {
  const n = id(v);
  return n <= 50000 ? n : invalid();
};
export const decodeJob = shape({
  id,
  kind: enumeration("parameter_slots"),
  state: enumeration("pending", "running", "completed", "failed", "superseded"),
  stalled: bool,
  mode: enumeration("preview", "apply"),
  scope: decodeScope,
  start_after_product_id: count,
  processed: count,
  limit: runLimit,
  has_more: bool,
  next_start_after_product_id: nullable(id),
  products_changed: count,
  products_not_ready: count,
  slots: shape(summaryFields),
  states: jobStates,
  error: nullable(text),
  created_at: nullable(text),
  updated_at: nullable(text),
});
export const decodeRun = shape({
  job: decodeJob,
  enqueue_failed: optional(bool),
});
export type Slot = ReturnType<typeof decodeSlot>;
export type Parameters = ReturnType<typeof decodeParameters>;
export type ServerPreview = ReturnType<typeof decodePreview>;
export type Overview = ReturnType<typeof decodeOverview>;
export type Alias = ReturnType<typeof decodeAlias>;
export type Job = ReturnType<typeof decodeJob>;
export type RunScope = ReturnType<typeof decodeScope>;
export type ParameterAccess = {
  bulk?: boolean;
  approve?: boolean;
  edit: boolean;
  globalAliases: boolean;
  classify: boolean;
};
export type SlotAction = {
  expected_revision: number;
  action: "set" | "accept_candidate" | "lock" | "unlock" | "reset";
  value?: string;
  unit?: string | null;
  value_id?: number | null;
  source_key?: string;
  reason: string;
};
export type AliasInput = {
  scope: "tenant" | "global";
  label: string;
  unit: string | null;
  emag_parameter_id: number;
  scope_emag_category_id: number;
  reason: string;
};

const nullableRecord: Decoder<Record<string, unknown> | null> = (v) =>
  v === null
    ? null
    : typeof v === "object" && !Array.isArray(v)
      ? (v as Record<string, unknown>)
      : invalid();
export const decodeProductContext = shape({
  id,
  revision: id,
  supplier_id: id,
  source_category: nullable(shape({ id, path: text })),
  classification: shape({
    navigation_node_id: nullable(text),
    navigation_path: nullable(array(text, 50)),
    donor_emag_category_id: nullable(id),
    donor_name: nullable(text),
    parameter_profile_state: profileState,
    donor_choices: array(
      shape({
        emag_category_id: id,
        name: text,
        review_state: optional(enumeration("reviewed", "pending_review")),
        enrichment_ready: optional(bool),
      }),
      100,
    ),
  }),
  source_attributes: array(
    shape({
      key: text,
      header: text,
      label: text,
      unit: nullable(text),
      raw: nullable(text),
      run_id: id,
      line: count,
      present: bool,
    }),
    10000,
  ),
  capabilities: shape({ classify: bool }),
  events: array(
    shape({
      id,
      kind: text,
      revision: nullable(id),
      actor_id: nullable(id),
      reason: nullable(text),
      before: nullableRecord,
      after: nullableRecord,
      created_at: text,
    }),
    50,
  ),
});

/** Shared strict decoders for the additive 03C wire contract. */
export const parameterWire = {
  shape,
  text,
  bool,
  count,
  id,
  nullable,
  optional,
  enumeration,
  array,
};
