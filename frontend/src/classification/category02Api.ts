import { ApiHttpError } from "../apiResponse";
import type {
  CategoryMap,
  InternalCategory,
  InternalPage,
  Maps,
  ProductDetail,
  ProductItem,
  Products,
  Request,
} from "./category02Contract";
import {
  ClassificationConflict,
  type Choice,
  type ClassificationPresentation,
  type EditIntent,
  type MappingCard,
  type ProductCard,
} from "./presentation";

const origins: Record<string, string> = {
  category_map: "Jóváhagyott kategóriatérkép",
  manual: "Kézi döntés",
  suggestion: "Gépi javaslat",
  none: "Nincs besorolási alap",
};
const reasons: Record<string, string> = {
  approved_category_map: "Jóváhagyott saját kategóriatérkép alapján.",
  manual_decision: "Védett kézi döntés.",
  uncalibrated_suggestion: "A javaslat módszere még nem kalibrált.",
  ambiguous_candidates: "Több lehetséges belső kategória.",
  no_candidate: "Nincs megfelelő jelölt.",
  no_source_category: "Nincs saját kategória.",
  category_map_rejected: "A kategóriatérképet elutasították.",
  category_map_target_unavailable: "A térkép célkategóriája nem érhető el.",
  parameter_profile_choice_required: "Paraméterprofil kiválasztása szükséges.",
  calibrated_rule: "Kalibrált szerveroldali szabály.",
  not_classified_yet: "Még nincs besorolás.",
};
function choice(
  key: string,
  path: string[],
  donors?: InternalCategory["donors"],
): Choice {
  return {
    key,
    path,
    title: path.at(-1) || key,
    selectable: true,
    hasChildren: false,
    donors: donors?.map((d) => ({
      key: String(d.emag_category_id),
      title: d.name,
    })),
  };
}
function product(
  item: ProductItem,
  labels: Record<string, string>,
  detail?: ProductDetail,
): ProductCard {
  const c = item.classification;
  return {
    key: String(item.id),
    title: String(item.fields.name || "Név nélküli termék"),
    identifier: String(
      item.fields.sku || item.fields.gtin || item.fields.ean || "–",
    ),
    source: item.supplier_name,
    originalCategory: item.source_category?.path || "",
    ownCategory: item.source_category?.path || "",
    internalCategory:
      c.navigation_node_id && c.navigation_path
        ? choice(c.navigation_node_id, c.navigation_path, c.donor_choices)
        : null,
    group: c.status === "auto_classified" ? "assigned" : "review",
    explanation: c.reason_codes.map((r) => reasons[r] || r).join(" "),
    confidencePercent: c.confidence === null ? null : c.confidence * 100,
    alternatives: c.alternatives
      .slice(0, 3)
      .map((a) => choice(a.navigation_node_id, a.path)),
    origin: origins[c.origin] || c.origin,
    protectedEdit: c.locked,
    auditText: `Revízió: ${item.revision} · Szabály: ${c.rule_version} · Döntés: ${c.decided_at || "–"} · Döntéshozó: ${c.decided_by ?? "rendszer"}`,
    donorText: c.donor_name
      ? `${c.donor_name} (${c.donor_emag_category_id})`
      : "Nincs kiválasztott paraméterprofil",
    canEdit: detail?.capabilities.classify ?? false,
    editContext: item,
    fields: detail
      ? [
          ...Object.entries(item.fields).map(([k, v]) => ({
            label: labels[k] || k,
            value: typeof v === "object" ? JSON.stringify(v) : String(v ?? "–"),
          })),
          ...detail.source_attributes.map((a) => ({
            label: `${a.label || a.header}${a.unit ? ` (${a.unit})` : ""}`,
            value: `${a.raw ?? "–"}${a.present ? "" : " · A legutóbbi fájlból hiányzott"}`,
          })),
        ]
      : undefined,
    history: detail?.events.map(
      (e) =>
        `${e.created_at} · ${e.kind === "classification_manual" ? "Kézi besorolás" : e.kind === "classification_reset" ? "Automatikus besorolás visszaállítása" : "Automatikus besorolás"} · Revízió: ${e.revision} · ${e.reason || ""}`,
    ),
  };
}
function mapping(item: CategoryMap): MappingCard {
  const m = item.map;
  return {
    key: String(item.source_category.id),
    title: item.source_category.path,
    originalCategory: item.source_category.path,
    internalCategory:
      m?.navigation_node_id && m.navigation_path
        ? choice(m.navigation_node_id, m.navigation_path)
        : null,
    profileText: m?.donor_emag_category_id
      ? `Paraméterprofil: ${m.donor_emag_category_id}`
      : "Nincs kiválasztott paraméterprofil",
    approved: m?.state === "approved",
    protectedEdit: false,
    affectedProducts: item.product_count,
    auditText: m
      ? `Revízió: ${m.revision} · ${m.decided_at || "–"} · ${m.reason || ""}`
      : "Még nincs mentett kategóriatérkép.",
    editContext: item,
  };
}
export function createCategory02Presentation(
  api: Request,
  workspaceKey: string,
  canClassify: boolean,
  initial: Products,
): ClassificationPresentation {
  let bootstrap: Products | null = initial;
  let labels = initial.field_labels;
  let serial = 0;
  // Local confirmation handles are never sent as server tokens. Revisions remain authoritative.
  const confirmations = new Map<string, EditIntent>();
  const nodes = new Map<string, InternalCategory>();
  async function readChoices(
    search: string,
    cursor: string | null,
    signal: AbortSignal,
  ) {
    const offset = Number(cursor || 0);
    const result = await api<InternalPage>(
      `/workspace/internal-categories?${new URLSearchParams({ q: search, offset: String(offset), limit: "100" })}`,
      "GET",
      undefined,
      signal,
    );
    result.items.forEach((n) => nodes.set(n.navigation_node_id, n));
    return {
      items: result.items.map((n) =>
        choice(n.navigation_node_id, n.path, n.donors),
      ),
      next:
        offset + result.items.length < result.total
          ? String(offset + result.items.length)
          : null,
      total: result.total,
    };
  }
  async function conflictAware<T>(run: () => Promise<T>): Promise<T> {
    try {
      return await run();
    } catch (e) {
      if (e instanceof ApiHttpError && e.status === 409)
        throw new ClassificationConflict(e.message);
      throw e;
    }
  }
  return {
    workspaceKey,
    access: {
      editProducts: canClassify,
      editMappings: canClassify,
      bulkEdit: false,
      manageThreshold: false,
    },
    ports: {
      features: { productSearch: true, mappingSearch: false },
      mappingPropagation: "always",
      resetSupported: true,
      products: async (filters, cursor, signal) => {
        const q = new URLSearchParams({ cursor: cursor || "0", limit: "25" });
        if (filters.search.trim()) q.set("q", filters.search);
        if (filters.group !== "all")
          q.set(
            "status",
            filters.group === "assigned" ? "auto_classified" : "needs_review",
          );
        if (filters.category) q.set("navigation_node_id", filters.category);
        if (filters.source) q.set("origin", filters.source);
        const result =
          bootstrap &&
          !cursor &&
          !filters.search.trim() &&
          filters.group === "all" &&
          !filters.category &&
          !filters.source
            ? bootstrap
            : await api<Products>(
                `/workspace/products?${q}`,
                "GET",
                undefined,
                signal,
              );
        bootstrap = null;
        labels = result.field_labels;
        const counts = result.status_counts;
        return {
          items: result.items.map((i) => product(i, labels)),
          next: result.next_cursor === null ? null : String(result.next_cursor),
          total:
            filters.group === "assigned"
              ? counts.auto_classified
              : filters.group === "review"
                ? counts.needs_review
                : counts.auto_classified + counts.needs_review,
          categories: [...nodes.values()].map((n) => ({
            key: n.navigation_node_id,
            title: n.path.join(" / "),
          })),
          sources: Object.entries(origins).map(([key, title]) => ({
            key,
            title,
          })),
        };
      },
      details: async (key, signal) => {
        const d = await api<ProductDetail>(
          `/workspace/products/${encodeURIComponent(key)}`,
          "GET",
          undefined,
          signal,
        );
        const card = product(d, labels, d);
        // Resolve only the selected detail's alternatives, never every product in a page.
        for (const alt of card.alternatives) {
          if (!nodes.has(alt.key))
            await readChoices(alt.path.join(" > "), null, signal);
          const n = nodes.get(alt.key);
          alt.donors = n?.donors.map((x) => ({
            key: String(x.emag_category_id),
            title: x.name,
          }));
        }
        return card;
      },
      choices: (search, _parent, cursor, signal) =>
        readChoices(search, cursor, signal),
      mappings: async (search, cursor, signal) => {
        if (search)
          throw new Error(
            "A szerződés még nem tartalmaz kategóriatérkép-keresési API-t.",
          );
        const result = await api<Maps>(
          `/workspace/category-maps?${new URLSearchParams({ cursor: cursor || "0", limit: "50" })}`,
          "GET",
          undefined,
          signal,
        );
        return {
          items: result.items.map(mapping),
          next: result.next_cursor === null ? null : String(result.next_cursor),
          total: null,
        };
      },
      preview: canClassify
        ? async (intent, signal) => {
            if ((!intent.action || intent.action === "set") && !intent.category)
              throw new Error("Válassz belső kategóriát.");
            let affected: number;
            let before: string;
            let donorBefore: string;
            if (intent.target.kind === "product") {
              const old = intent.target.context as ProductItem;
              const fresh = await api<ProductDetail>(
                `/workspace/products/${old.id}`,
                "GET",
                undefined,
                signal,
              );
              if (!fresh.capabilities.classify)
                throw new Error("Nincs jogosultság a besorolás módosításához.");
              if (fresh.revision !== old.revision)
                throw new ClassificationConflict(
                  "A termék megváltozott. Töltsd újra a friss adatokat.",
                );
              donorBefore =
                fresh.classification.donor_name ||
                String(
                  fresh.classification.donor_emag_category_id ??
                    "Nincs kiválasztva",
                );
              affected = 1;
              before =
                fresh.classification.navigation_path?.join(" / ") ||
                "Nincs besorolás";
            } else if (intent.target.kind === "mapping") {
              const old = intent.target.context as CategoryMap;
              if (intent.action === "reset" && !old.map)
                throw new Error("Nincs törölhető kategóriatérkép.");
              donorBefore = String(
                old.map?.donor_emag_category_id ?? "Nincs kiválasztva",
              );
              affected = old.product_count;
              before =
                old.map?.navigation_path?.join(" / ") || "Nincs jóváhagyva";
            } else
              throw new Error(
                "Tetszőleges termékhalmaz tömeges módosítására még nincs API.",
              );
            const handle = String(++serial);
            confirmations.clear();
            confirmations.set(handle, intent);
            return {
              handle,
              summary:
                "A saját kategória és az eredeti értékek változatlanok maradnak.",
              affected,
              locked: null,
              conflicts: null,
              canApply: true,
              localOnly: true,
              changes: [
                {
                  label: "Paraméterprofil",
                  before: donorBefore,
                  after:
                    intent.action === "reset" || intent.action === "reject"
                      ? "Szerveroldali újraértékelés"
                      : intent.donorKey
                        ? intent.category?.donors?.find(
                            (d) => d.key === intent.donorKey,
                          )?.title || intent.donorKey
                        : "Egyetlen profil esetén automatikus; több profilnál még kiválasztandó",
                },
                {
                  label: "Belső kategória",
                  before,
                  after:
                    intent.action === "reset"
                      ? "Automatikus újrabesorolás"
                      : intent.action === "reject"
                        ? "Elutasított térkép"
                        : intent.category!.path.join(" / "),
                },
              ],
            };
          }
        : undefined,
      apply: canClassify
        ? (preview, signal) =>
            conflictAware(async () => {
              const intent = confirmations.get(preview.handle);
              if (!intent)
                throw new Error(
                  "A helyi összesítő lejárt. Készíts új előnézetet.",
                );
              confirmations.delete(preview.handle);
              const donor = intent.donorKey ? Number(intent.donorKey) : null;
              if (intent.target.kind === "product") {
                const old = intent.target.context as ProductItem;
                await api<ProductDetail>(
                  `/workspace/products/${old.id}/classification`,
                  "PATCH",
                  {
                    expected_revision: old.revision,
                    action: intent.action === "reset" ? "reset" : "set",
                    ...(intent.action !== "reset"
                      ? {
                          navigation_node_id: intent.category!.key,
                          donor_emag_category_id: donor,
                        }
                      : {}),
                    reason: intent.reason,
                  },
                  signal,
                );
                return intent.action === "reset"
                  ? "A kézi védelem feloldva, az automatikus besorolás frissült."
                  : "A kézi besorolás mentve és zárolva.";
              }
              if (intent.target.kind !== "mapping")
                throw new Error("A művelet nem támogatott.");
              const old = intent.target.context as CategoryMap;
              const result = await api<{
                products_changed: number;
                locked_skipped: number;
              }>(
                `/workspace/category-maps/${old.source_category.id}${intent.action === "reset" ? `?expected_revision=${old.map!.revision}` : ""}`,
                intent.action === "reset" ? "DELETE" : "PUT",
                intent.action === "reset"
                  ? undefined
                  : {
                      expected_revision: old.map?.revision ?? null,
                      state:
                        intent.action === "reject" ? "rejected" : "approved",
                      ...(intent.action !== "reject"
                        ? {
                            navigation_node_id: intent.category!.key,
                            donor_emag_category_id: donor,
                          }
                        : {}),
                      reason: intent.reason,
                    },
                signal,
              );
              return `Kategóriatérkép mentve. Újrabesorolt termékek: ${result.products_changed.toLocaleString("hu-HU")}; védett, kihagyott: ${result.locked_skipped.toLocaleString("hu-HU")}.`;
            })
        : undefined,
    },
  };
}
