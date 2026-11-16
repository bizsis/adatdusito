/** Frontend presentation ports only. These are NOT CATEGORY-02A HTTP DTOs.
 * A production adapter must map the published contract, authorization and revisions.
 * There are deliberately no URLs, fetch defaults or sample responses here.
 */
export type ClassificationGroup = "assigned" | "review";
export const classificationLabels: Record<ClassificationGroup, string> = {
  assigned: "Automatikusan besorolt",
  review: "Ellenőrzést igényel",
};
export type Choice = {
  key: string;
  title: string;
  path: string[];
  selectable: boolean;
  hasChildren: boolean;
  donors?: { key: string; title: string }[];
};
export type ProductCard = {
  key: string;
  title: string;
  identifier: string;
  source: string;
  originalCategory: string;
  ownCategory: string;
  internalCategory: Choice | null;
  group: ClassificationGroup;
  explanation: string;
  confidencePercent: number | null;
  alternatives: Choice[];
  origin: string;
  protectedEdit: boolean;
  auditText: string;
  donorText: string;
  canEdit?: boolean;
  fields?: { label: string; value: string }[];
  history?: string[];
  editContext: unknown;
};
export type MappingCard = {
  key: string;
  title: string;
  originalCategory: string;
  internalCategory: Choice | null;
  profileText: string;
  approved: boolean;
  protectedEdit: boolean;
  affectedProducts: number;
  auditText: string;
  editContext: unknown;
};
export type ProductFilters = {
  search: string;
  group: "all" | ClassificationGroup;
  category: string;
  source: string;
};
export type Page<T> = {
  items: T[];
  next: string | null;
  total: number | null;
};
export type FilterChoice = { key: string; title: string };
export type ProductPage = Page<ProductCard> & {
  categories: FilterChoice[];
  sources: FilterChoice[];
};
export type Selection =
  | { kind: "page"; keys: string[] }
  | { kind: "matching"; handle: string; count: number };
export type EditIntent = {
  target:
    | { kind: "product"; key: string; context: unknown }
    | { kind: "mapping"; key: string; context: unknown; inherit: boolean }
    | { kind: "bulk"; selection: Selection };
  category: Choice | null;
  action?: "set" | "reset" | "reject";
  reason: string;
  donorKey?: string;
};
export type ChangePreview = {
  handle: string;
  summary: string;
  affected: number;
  locked: number | null;
  conflicts: number | null;
  localOnly?: boolean;
  canApply: boolean;
  changes: { label: string; before: string; after: string }[];
};
export class ClassificationConflict extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClassificationConflict";
  }
}
export type PresentationPorts = {
  features?: { productSearch: boolean; mappingSearch: boolean };
  mappingPropagation?: "always";
  resetSupported?: boolean;
  details?: (key: string, signal: AbortSignal) => Promise<ProductCard>;
  products: (
    filters: ProductFilters,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<ProductPage>;
  mappings?: (
    search: string,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<Page<MappingCard>>;
  choices?: (
    search: string,
    parent: string | null,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<Page<Choice>>;
  selectMatching?: (
    filters: ProductFilters,
    signal: AbortSignal,
  ) => Promise<{ handle: string; count: number }>;
  preview?: (intent: EditIntent, signal: AbortSignal) => Promise<ChangePreview>;
  apply?: (
    preview: ChangePreview,
    signal: AbortSignal,
  ) => Promise<void | string>;
  threshold?: (signal: AbortSignal) => Promise<number>;
  saveThreshold?: (percent: number, signal: AbortSignal) => Promise<number>;
};
export type PresentationAccess = {
  editProducts: boolean;
  editMappings: boolean;
  bulkEdit: boolean;
  manageThreshold: boolean;
};
export type ClassificationPresentation = {
  workspaceKey: string;
  ports: PresentationPorts;
  access: PresentationAccess;
};
