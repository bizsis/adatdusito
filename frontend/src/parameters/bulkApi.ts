import type { Request } from "../classification/category02Contract";
import { parameterWire as w } from "./liveContract";
const { shape, text, bool, count, id, nullable, optional, enumeration, array } =
  w;
const bad = (): never => {
  throw new Error(
    "A tömeges paraméterművelet API-válasza nem értelmezhető. Kérj friss adatokat; mentési siker nem igazolható.",
  );
};
const token = (v: unknown) =>
  typeof v === "string" && /^[A-Za-z0-9_-]{43}$/.test(v) ? v : bad();
const millis = (s: string) =>
  Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(s) ? s : s + "Z");
const stamp = (v: unknown) => {
  const s = text(v);
  return /^\d{4}-\d{2}-\d{2}T/.test(s) && Number.isFinite(millis(s))
    ? s
    : bad();
};
const counters = (v: unknown): Record<string, number> => {
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    Object.keys(v).length > 100
  )
    return bad();
  return Object.fromEntries(Object.entries(v).map(([k, n]) => [k, count(n)]));
};
const summary = shape({
  create: count,
  update: count,
  remove: count,
  keep: count,
  blocked_locked: count,
});
const selectionMeta = shape({
  id,
  total: count,
  expires_at: stamp,
  excluded: count,
  mode: enumeration("filters", "product_ids"),
  catalog_version_id: nullable(id),
  rule_version: text,
  created_at: stamp,
  expired: bool,
});
export const decodeSelection = (v: unknown) => {
  const result = {
    ...selectionMeta(v),
    selection_token: shape({ selection_token: token })(v).selection_token,
  };
  if (!result.total || result.total > 250000) return bad();
  return result;
};
const operation = shape({
  id,
  kind: enumeration("bulk_preview", "bulk_apply", "preparation_check"),
  state: enumeration("pending", "running", "completed", "cancelled", "failed"),
  stalled: bool,
  selection_id: id,
  preview_id: optional(nullable(id)),
  expires_at: stamp,
  total: count,
  processed: count,
  runs: count,
  run_limit: id,
  outcomes: counters,
  slots: optional(summary),
  new_slots: optional(counters),
  accepted_present: optional(count),
  source_refresh: optional(count),
  source_overwrites: optional(count),
  revision_changed_since_selection: optional(count),
  blocked_reasons: optional(counters),
  research_targets: optional(count),
  mandatory_research_targets: optional(count),
  error_count: count,
  stopped_reason: optional(nullable(text)),
  error: nullable(text),
  created_by: id,
  created_at: nullable(stamp),
  updated_at: nullable(stamp),
  enqueue_failed: optional(bool),
});
export const decodeOperation = (v: unknown) => {
  const r = operation(v);
  if (r.run_limit > 50000 || r.total > 250000 || r.processed > r.total)
    return bad();
  if (r.kind === "preparation_check") {
    if (
      r.blocked_reasons === undefined ||
      r.research_targets === undefined ||
      r.mandatory_research_targets === undefined
    )
      return bad();
  } else if (
    !r.slots ||
    !r.new_slots ||
    r.source_overwrites === undefined ||
    r.accepted_present === undefined ||
    r.source_refresh === undefined ||
    r.revision_changed_since_selection === undefined
  )
    return bad();
  return r;
};
export const decodeApproval = shape({
  id,
  version: id,
  state: enumeration("active", "revoked"),
  check_id: id,
  selection_id: id,
  approved: count,
  skipped_stale: count,
  valid: count,
  invalid: count,
  research_targets: count,
  mandatory_research_targets: count,
  catalog_version_id: nullable(id),
  rule_version: text,
  schema_fingerprint: text,
  schema_current: nullable(bool),
  reason: nullable(text),
  approved_by: id,
  approved_at: stamp,
  revoked_by: nullable(id),
  revoked_at: nullable(stamp),
  revoke_reason: nullable(text),
  revalidated_at: nullable(stamp),
  replayed: optional(bool),
});
const detailApproval = (value: unknown) => {
  const a = decodeApproval(value);
  if (a.schema_current === null || a.valid + a.invalid !== a.approved)
    return bad();
  return a;
};
const item = shape({
  product_id: id,
  name: nullable(text),
  sku: nullable(text),
  outcome: text,
  apply_outcome: nullable(text),
  revision_before: id,
  revision_after: nullable(id),
  summary: counters,
  reasons: array(text, 100),
});
const items = shape({ items: array(item, 100), next_cursor: nullable(id) });
const approvalItems = shape({
  items: array(
    shape({
      product_id: id,
      product_revision: id,
      current_revision: id,
      valid: bool,
      invalid_reason: nullable(text),
      navigation_node_id: nullable(text),
      donor_emag_category_id: nullable(id),
      research_targets: count,
      mandatory_research_targets: count,
    }),
    100,
  ),
  next_cursor: nullable(id),
});
export type Selection = ReturnType<typeof decodeSelection>;
export type Operation = ReturnType<typeof decodeOperation>;
export type Approval = ReturnType<typeof decodeApproval>;
export type BulkFilters = {
  q?: string;
  state?: string;
  mandatory_missing?: boolean;
  parameter_profile_state?: string;
};
export type BulkAccess = { edit: boolean; bulk?: boolean; approve?: boolean };
export const expired = (stamp: string) => Date.now() >= millis(stamp);
const productPreparation = shape({
  product_id: id,
  revision: id,
  approval: nullable(
    shape({
      id,
      approved_at: stamp,
      product_revision: id,
      valid: bool,
      invalid_reason: nullable(text),
      research_targets: count,
      mandatory_research_targets: count,
    }),
  ),
});
export function bulkApi(api: Request) {
  async function request<T>(
    path: string,
    decode: (v: unknown) => T,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ) {
    return decode(
      await api<unknown>("/workspace/" + path, method, body, signal),
    );
  }
  return {
    productPreparation: (pid: string, s: AbortSignal) =>
      request(
        `products/${encodeURIComponent(pid)}/preparation`,
        productPreparation,
        "GET",
        undefined,
        s,
      ),
    selection: (
      body: { filters: BulkFilters } | { product_ids: number[] },
      s: AbortSignal,
    ) => request("product-selections", decodeSelection, "POST", body, s),
    preview: (selection_token: string, s: AbortSignal) =>
      request(
        "parameter-bulk-previews",
        shape({
          preview: decodeOperation,
          preview_token: token,
          enqueue_failed: optional(bool),
        }),
        "POST",
        { selection_token },
        s,
      ),
    check: (selection_token: string, s: AbortSignal) =>
      request(
        "preparation-checks",
        shape({
          check: decodeOperation,
          check_token: token,
          enqueue_failed: optional(bool),
        }),
        "POST",
        { selection_token },
        s,
      ),
    apply: (
      pid: number,
      body: {
        preview_token: string;
        confirm: true;
        expected_eligible: number;
        idempotency_key: string;
        reason: string;
      },
      s: AbortSignal,
    ) =>
      request(
        `parameter-bulk-previews/${pid}/apply`,
        shape({
          apply: decodeOperation,
          replayed: optional(bool),
          enqueue_failed: optional(bool),
        }),
        "POST",
        body,
        s,
      ),
    approve: (
      body: {
        check_id: number;
        check_token: string;
        confirm: true;
        expected_approvable: number;
        idempotency_key: string;
        reason: string;
      },
      s: AbortSignal,
    ) => request("preparation-approvals", detailApproval, "POST", body, s),
    job: (jid: number, s: AbortSignal) =>
      request(`product-jobs/${jid}`, decodeOperation, "GET", undefined, s),
    control: (jid: number, action: "cancel" | "resume", s: AbortSignal) =>
      request(`product-jobs/${jid}/${action}`, decodeOperation, "POST", {}, s),
    items: (jid: number, q: URLSearchParams, s: AbortSignal) =>
      request(`product-jobs/${jid}/items?${q}`, items, "GET", undefined, s),
    approvals: (q: URLSearchParams, s: AbortSignal) =>
      request(
        `preparation-approvals?${q}`,
        shape({ items: array(decodeApproval, 100), next_cursor: nullable(id) }),
        "GET",
        undefined,
        s,
      ),
    approval: (aid: number, s: AbortSignal) =>
      request(
        `preparation-approvals/${aid}`,
        detailApproval,
        "GET",
        undefined,
        s,
      ),
    approvalItems: (aid: number, q: URLSearchParams, s: AbortSignal) =>
      request(
        `preparation-approvals/${aid}/items?${q}`,
        approvalItems,
        "GET",
        undefined,
        s,
      ),
    revalidate: (aid: number, s: AbortSignal) =>
      request(
        `preparation-approvals/${aid}/revalidate`,
        detailApproval,
        "POST",
        {},
        s,
      ),
    revoke: (aid: number, version: number, reason: string, s: AbortSignal) =>
      request(
        `preparation-approvals/${aid}/revoke`,
        detailApproval,
        "POST",
        { expected_version: version, reason },
        s,
      ),
  };
}
export type BulkApi = ReturnType<typeof bulkApi>;
