/** CATEGORY-02A contract, PR #18 / 8c5db11. No tenant identifiers are sent. */
export type Request = <T>(
  path: string,
  method?: string,
  body?: unknown,
  signal?: AbortSignal,
) => Promise<T>;
export type InternalCategory = {
  navigation_node_id: string;
  name: string;
  path: string[];
  donors: { emag_category_id: number; name: string }[];
};
export type InternalPage = {
  items: InternalCategory[];
  total: number;
  offset: number;
  limit: number;
};
export type SourceCategory = {
  id: number;
  path: string;
  origin: string;
  supplier_id: number | null;
};
export type ProductItem = {
  id: number;
  revision: number;
  fields: Record<string, unknown>;
  supplier_name: string;
  source_line: number;
  source_category: SourceCategory | null;
  classification: {
    status: "auto_classified" | "needs_review";
    origin: string;
    method: string | null;
    reason_codes: string[];
    navigation_node_id: string | null;
    navigation_path: string[] | null;
    donor_emag_category_id: number | null;
    donor_name: string | null;
    donor_choices: { emag_category_id: number; name: string }[];
    confidence: number | null;
    alternatives: {
      navigation_node_id: string;
      path: string[];
      score: number | null;
    }[];
    locked: boolean;
    rule_version: string | null;
    decided_by: number | null;
    decided_at: string | null;
  };
};
export type ProductDetail = ProductItem & {
  capabilities: { classify: boolean };
  source_attributes: {
    key: string;
    header: string;
    label: string;
    unit: string | null;
    raw: string | null;
    present: boolean;
  }[];
  events: {
    id: number;
    kind: string;
    revision: number;
    actor_id: number | null;
    reason: string | null;
    created_at: string;
  }[];
};
export type Products = {
  items: ProductItem[];
  next_cursor: number | null;
  field_labels: Record<string, string>;
  status_counts: { auto_classified: number; needs_review: number };
};
export type CategoryMap = {
  source_category: SourceCategory;
  product_count: number;
  map: null | {
    state: string;
    navigation_node_id: string | null;
    navigation_path: string[] | null;
    donor_emag_category_id: number | null;
    revision: number;
    reason: string | null;
    decided_by: number | null;
    decided_at: string | null;
  };
};
export type Maps = { items: CategoryMap[]; next_cursor: number | null };
