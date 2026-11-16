/** Validate consumed wire fields before rendering or acknowledging a write. Extra fields remain additive. */
import type {
  InternalPage,
  Maps,
  ProductDetail,
  ProductItem,
  Products,
} from "./category02Contract";
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string";
const texts = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const count = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const id = (v: unknown): v is number => count(v) && v > 0;
const nullable = (test: (v: unknown) => boolean, v: unknown) =>
  v === null || test(v);
const donor = (v: unknown) =>
  object(v) && id(v.emag_category_id) && text(v.name);
const source = (v: unknown) => object(v) && id(v.id) && text(v.path);
const target = (v: unknown) =>
  object(v) && text(v.navigation_node_id) && texts(v.path);
const labels = (v: unknown) => object(v) && Object.values(v).every(text);
const page = (
  v: unknown,
): v is Record<string, unknown> & { items: unknown[] } =>
  object(v) &&
  Array.isArray(v.items) &&
  v.items.length <= 100 &&
  nullable(id, v.next_cursor);
function validProduct(v: unknown): v is ProductItem {
  if (
    !object(v) ||
    !id(v.id) ||
    !id(v.revision) ||
    !object(v.fields) ||
    !text(v.supplier_name) ||
    !count(v.source_line) ||
    !nullable(source, v.source_category) ||
    !object(v.classification)
  )
    return false;
  const c = v.classification;
  return (
    ["auto_classified", "needs_review"].includes(String(c.status)) &&
    text(c.origin) &&
    texts(c.reason_codes) &&
    nullable(text, c.navigation_node_id) &&
    nullable(texts, c.navigation_path) &&
    nullable(id, c.donor_emag_category_id) &&
    nullable(text, c.donor_name) &&
    Array.isArray(c.donor_choices) &&
    c.donor_choices.every(donor) &&
    nullable(
      (n) => typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1,
      c.confidence,
    ) &&
    Array.isArray(c.alternatives) &&
    c.alternatives.length <= 3 &&
    c.alternatives.every(target) &&
    typeof c.locked === "boolean" &&
    nullable(text, c.rule_version) &&
    nullable(id, c.decided_by) &&
    nullable(text, c.decided_at)
  );
}
function requireValid(valid: boolean): asserts valid {
  if (!valid)
    throw new Error(
      "A kiszolgáló válasza nem értelmezhető. Töltsd újra az adatokat; a művelet eredményét nem lehetett igazolni.",
    );
}
export function validateProducts(v: unknown): asserts v is Products {
  requireValid(
    page(v) &&
      v.items.every(validProduct) &&
      labels(v.field_labels) &&
      object(v.status_counts) &&
      count(v.status_counts.auto_classified) &&
      count(v.status_counts.needs_review),
  );
}
export function validateProductEnvelope(v: unknown) {
  requireValid(page(v) && labels(v.field_labels));
  if (
    object(v) &&
    ("status_counts" in v ||
      (Array.isArray(v.items) &&
        v.items.some((i) => object(i) && "classification" in i)))
  )
    validateProducts(v);
  else if (page(v))
    requireValid(
      v.items.every(
        (i) =>
          object(i) && id(i.id) && object(i.fields) && text(i.supplier_name),
      ),
    );
}
export function validateDetail(v: unknown): asserts v is ProductDetail {
  requireValid(object(v));
  const d: Record<string, unknown> = v;
  requireValid(
    validProduct(v) &&
      object(d.capabilities) &&
      typeof d.capabilities.classify === "boolean" &&
      Array.isArray(d.source_attributes) &&
      d.source_attributes.every(
        (a) =>
          object(a) &&
          text(a.header) &&
          text(a.label) &&
          nullable(text, a.unit) &&
          nullable(text, a.raw) &&
          typeof a.present === "boolean",
      ) &&
      Array.isArray(d.events) &&
      d.events.every(
        (e) =>
          object(e) &&
          text(e.created_at) &&
          text(e.kind) &&
          id(e.revision) &&
          nullable(text, e.reason),
      ),
  );
}
export function validateInternalPage(v: unknown): asserts v is InternalPage {
  requireValid(
    object(v) &&
      Array.isArray(v.items) &&
      v.items.length <= 100 &&
      count(v.total) &&
      count(v.offset) &&
      id(v.limit) &&
      v.limit <= 100 &&
      v.items.every(
        (n) =>
          target(n) &&
          object(n) &&
          text(n.name) &&
          Array.isArray(n.donors) &&
          n.donors.every(donor),
      ),
  );
}
export function validateMaps(v: unknown): asserts v is Maps {
  requireValid(
    page(v) &&
      v.items.every(
        (i) =>
          object(i) &&
          source(i.source_category) &&
          count(i.product_count) &&
          nullable(
            (m) =>
              object(m) &&
              ["approved", "rejected"].includes(String(m.state)) &&
              id(m.revision) &&
              nullable(text, m.navigation_node_id) &&
              nullable(texts, m.navigation_path) &&
              nullable(id, m.donor_emag_category_id) &&
              nullable(text, m.reason) &&
              nullable(text, m.decided_at),
            i.map,
          ),
      ),
  );
}
export type MapWriteResult =
  | { products_changed: number; locked_skipped: number }
  | {
      products_changed: null;
      locked_skipped: null;
      reapply: {
        mode: "queued";
        state: "pending" | "running";
        job_id: number;
        total: number;
        enqueue_failed?: boolean;
      };
    };
export function validateMapWrite(v: unknown): asserts v is MapWriteResult {
  requireValid(object(v));
  if (v.products_changed === null) {
    requireValid(
      v.locked_skipped === null &&
        object(v.reapply) &&
        v.reapply.mode === "queued" &&
        ["pending", "running"].includes(String(v.reapply.state)) &&
        id(v.reapply.job_id) &&
        count(v.reapply.total) &&
        (v.reapply.enqueue_failed === undefined ||
          typeof v.reapply.enqueue_failed === "boolean"),
    );
  } else requireValid(count(v.products_changed) && count(v.locked_skipped));
}
