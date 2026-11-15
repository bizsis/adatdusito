import React, { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import { CategoryPicker } from "./CategoryPicker";
import { ClassificationSummary } from "./ClassificationSummary";
import {
  ClassificationEditor,
  type EditorTarget,
} from "./ClassificationEditor";
import { ClassificationThreshold } from "./ClassificationThreshold";
import {
  classificationLabels,
  type ClassificationPresentation,
  type Choice,
  type MappingCard,
  type ProductCard,
  type ProductFilters,
  type Selection,
} from "./presentation";
import {
  usePresentationRead,
  usePresentationSearch,
} from "./usePresentationRead";
import "./classification.css";

// The workspace key is presentation context, not a backend tenant DTO.
export function ClassificationWorkspace(props: ClassificationPresentation) {
  return <Workspace key={props.workspaceKey} {...props} />;
}
const initialFilters: ProductFilters = {
  search: "",
  group: "all",
  category: "",
  source: "",
};

function Workspace({ ports, access }: ClassificationPresentation) {
  const [tab, setTab] = useState<"products" | "mappings">("products");
  const [filters, setFilters] = useState<ProductFilters>(initialFilters);
  const search = usePresentationSearch(filters.search);
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [matching, setMatching] = useState<Extract<
    Selection,
    { kind: "matching" }
  > | null>(null);
  const [focused, setFocused] = useState<ProductCard | null>(null);
  const [filterPicker, setFilterPicker] = useState(false);
  const [filterChoice, setFilterChoice] = useState<Choice | null>(null);
  const detailLoad = useCallback(
    (signal: AbortSignal) => {
      if (!focused || !ports.details)
        return Promise.reject(new Error("Nincs kiválasztott termék."));
      return ports.details(focused.key, signal);
    },
    [focused, ports],
  );
  const detail = usePresentationRead(
    focused && ports.details ? detailLoad : null,
  );
  const active = ports.details ? detail.data : focused;
  const [editor, setEditor] = useState<{
    target: EditorTarget;
    own: string;
    suggested?: Choice;
  } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selecting, setSelecting] = useState(false);
  const selectionRequest = useRef<AbortController | null>(null);
  useEffect(() => () => selectionRequest.current?.abort(), []);
  const query = useCallback(
    () => ({
      search,
      group: filters.group,
      category: filters.category,
      source: filters.source,
    }),
    [search, filters.group, filters.category, filters.source],
  );
  const load = useCallback(
    (signal: AbortSignal) => {
      // revision invalidates a read only after a confirmed write or explicit refresh.
      void revision;
      return ports.products(query(), cursor, signal);
    },
    [ports, query, cursor, revision],
  );
  const page = usePresentationRead(load);
  const [mappingSearch, setMappingSearch] = useState("");
  const mappingQuery = usePresentationSearch(mappingSearch);
  const [mappingCursor, setMappingCursor] = useState<string | null>(null);
  const [mappingHistory, setMappingHistory] = useState<(string | null)[]>([]);
  const readMappings = useCallback(
    (signal: AbortSignal) => {
      void revision;
      if (!ports.mappings)
        return Promise.reject(
          new Error("A kategóriatérkép API-kapcsolata még nem érhető el."),
        );
      return ports.mappings(mappingQuery, mappingCursor, signal);
    },
    [ports, mappingQuery, mappingCursor, revision],
  );
  const mappings = usePresentationRead(
    tab === "mappings" ? readMappings : null,
  );
  const pendingSearch = search !== filters.search;
  const writable = !!ports.choices && !!ports.preview && !!ports.apply;
  const editable = access.editProducts && writable;
  const bulk = access.bulkEdit && editable;
  function clearSelection() {
    selectionRequest.current?.abort();
    setSelecting(false);
    setSelected([]);
    setMatching(null);
    setEditor(null);
  }
  function filter(next: ProductFilters) {
    clearSelection();
    setFocused(null);
    setCursor(null);
    setHistory([]);
    setMessage("");
    setError("");
    setFilters(next);
  }
  function refresh() {
    setError("");
    clearSelection();
    setFocused(null);
    setCursor(null);
    setHistory([]);
    setMappingCursor(null);
    setMappingHistory([]);
    setRevision((r) => r + 1);
  }
  function applied(message?: string) {
    setMessage(
      message || "A módosítás mentve. A friss állapot betöltése folyamatban.",
    );
    refresh();
  }
  function editProduct(product: ProductCard) {
    setMessage("");
    setEditor({
      target: {
        kind: "product",
        key: product.key,
        context: product.editContext,
      },
      own: product.ownCategory,
    });
  }
  function editMapping(mapping: MappingCard) {
    setMessage("");
    setEditor({
      target: {
        kind: "mapping",
        key: mapping.key,
        context: mapping.editContext,
        inherit: false,
      },
      own: mapping.originalCategory,
    });
  }
  async function selectAll() {
    if (
      !ports.selectMatching ||
      !bulk ||
      pendingSearch ||
      page.loading ||
      selecting
    )
      return;
    selectionRequest.current?.abort();
    const controller = new AbortController();
    selectionRequest.current = controller;
    setSelecting(true);
    setError("");
    setEditor(null);
    try {
      const snapshot = await ports.selectMatching(query(), controller.signal);
      if (!controller.signal.aborted) {
        setSelected([]);
        setMatching({ kind: "matching", ...snapshot });
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "A kijelölés sikertelen.");
    } finally {
      if (!controller.signal.aborted) setSelecting(false);
    }
  }
  const selection: Selection = matching || { kind: "page", keys: selected };
  const selectedCount = matching?.count ?? selected.length;
  return (
    <div className="classification-workspace">
      <Panel title="Beszállítói termékadatok">
        <p>
          A saját kategóriák és értékek megmaradnak. A belső besorolás külön
          kapcsolat.
        </p>
        <div className="tabs" role="tablist" aria-label="Termékadatok nézete">
          <button
            role="tab"
            aria-selected={tab === "products"}
            onClick={() => {
              clearSelection();
              setTab("products");
            }}
          >
            Terméklista
          </button>
          {ports.mappings && (
            <button
              role="tab"
              aria-selected={tab === "mappings"}
              onClick={() => {
                clearSelection();
                setTab("mappings");
              }}
            >
              Saját kategóriatérkép és profilok
            </button>
          )}
        </div>
        {message && <p role="status">{message}</p>}
        {error && <p role="alert">{error}</p>}
        {(page.error || mappings.error || detail.error) && (
          <button onClick={refresh}>Adatok újratöltése</button>
        )}
        {tab === "products" ? (
          <>
            <div className="filters">
              {ports.features?.productSearch !== false && (
                <label>
                  Termék keresése
                  <input
                    value={filters.search}
                    onChange={(e) =>
                      filter({ ...filters, search: e.target.value })
                    }
                    placeholder="Név, cikkszám vagy EAN"
                    maxLength={120}
                  />
                </label>
              )}
              {ports.features?.productSearch === false && (
                <p className="muted">
                  A terméknév-, cikkszám- és EAN-keresés a szerveroldali API
                  kiegészítésére vár.
                </p>
              )}
              <label>
                Besorolási státusz
                <select
                  aria-label="Besorolási státusz"
                  value={filters.group}
                  onChange={(e) =>
                    filter({
                      ...filters,
                      group: e.target.value as ProductFilters["group"],
                    })
                  }
                >
                  <option value="all">Mindkét státusz</option>
                  <option value="assigned">
                    {classificationLabels.assigned}
                  </option>
                  <option value="review">{classificationLabels.review}</option>
                </select>
              </label>
              {ports.features ? (
                <div>
                  <button onClick={() => setFilterPicker(!filterPicker)}>
                    Kategória szerinti szűrés:{" "}
                    {filterChoice?.path.join(" / ") || "Minden kategória"}
                  </button>
                  {filterChoice && (
                    <button
                      onClick={() => {
                        setFilterChoice(null);
                        filter({ ...filters, category: "" });
                      }}
                    >
                      Kategóriaszűrő törlése
                    </button>
                  )}
                  {filterPicker && ports.choices && (
                    <CategoryPicker
                      read={ports.choices}
                      selected={filterChoice}
                      onSelect={(c) => {
                        setFilterChoice(c);
                        setFilterPicker(false);
                        filter({ ...filters, category: c.key });
                      }}
                    />
                  )}
                </div>
              ) : (
                <label>
                  Kategória szerinti szűrés
                  <select
                    aria-label="Kategória szerinti szűrés"
                    value={filters.category}
                    onChange={(e) =>
                      filter({ ...filters, category: e.target.value })
                    }
                  >
                    <option value="">Minden kategória</option>
                    {page.data?.categories.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                {ports.features
                  ? "Besorolás eredete"
                  : "Forrás szerinti szűrés"}
                <select
                  aria-label="Forrás szerinti szűrés"
                  value={filters.source}
                  onChange={(e) =>
                    filter({ ...filters, source: e.target.value })
                  }
                >
                  <option value="">Minden forrás</option>
                  {page.data?.sources.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {page.error && <p role="alert">{page.error}</p>}
            {(page.loading || pendingSearch) && (
              <p role="status">Termékek betöltése…</p>
            )}
            {page.data && (
              <>
                {page.data.total !== null && (
                  <p>
                    Szűrt találatok: {page.data.total.toLocaleString("hu-HU")}
                  </p>
                )}
                {!page.data.items.length && (
                  <p>Nincs a szűrésnek megfelelő termék.</p>
                )}
                {bulk && (
                  <div className="actions">
                    <button
                      disabled={
                        !page.data.items.length ||
                        pendingSearch ||
                        page.loading ||
                        selecting
                      }
                      onClick={() => {
                        setEditor(null);
                        setMatching(null);
                        setSelected(page.data?.items.map((p) => p.key) || []);
                      }}
                    >
                      Aktuális oldal kijelölése
                    </button>
                    {ports.selectMatching && (
                      <button
                        disabled={
                          pendingSearch ||
                          page.loading ||
                          selecting ||
                          !page.data.items.length
                        }
                        onClick={selectAll}
                      >
                        Összes szűrt találat kijelölése
                      </button>
                    )}
                    {selectedCount > 0 && (
                      <>
                        <span>
                          Kijelölve: {selectedCount.toLocaleString("hu-HU")}
                        </span>
                        <button
                          onClick={() =>
                            setEditor({
                              target: { kind: "bulk", selection },
                              own: "A kiválasztott termékek saját kategóriái megmaradnak",
                            })
                          }
                        >
                          Tömeges besorolás előnézete
                        </button>
                        <button onClick={clearSelection}>
                          Kijelölés törlése
                        </button>
                      </>
                    )}
                  </div>
                )}
                <div className="table-wrap">
                  <table className="classification-products">
                    <thead>
                      <tr>
                        {bulk && <th>Kijelölés</th>}
                        <th>Termék / cikkszám</th>
                        <th>Eredeti / saját kategória</th>
                        <th>Belső besorolás</th>
                        <th>Státusz és védelem</th>
                        <th>Forrás</th>
                        <th>Művelet</th>
                      </tr>
                    </thead>
                    <tbody>
                      {page.data.items.map((p) => (
                        <tr key={p.key}>
                          {bulk && (
                            <td data-label="Kijelölés">
                              <input
                                type="checkbox"
                                aria-label={`${p.title} kijelölése`}
                                checked={!!matching || selected.includes(p.key)}
                                disabled={!!matching || pendingSearch}
                                onChange={(e) => {
                                  setEditor(null);
                                  setSelected(
                                    e.target.checked
                                      ? [...selected, p.key]
                                      : selected.filter((key) => key !== p.key),
                                  );
                                }}
                              />
                            </td>
                          )}
                          <td data-label="Termék / cikkszám">
                            <strong>{p.title}</strong>
                            <small>{p.identifier}</small>
                          </td>
                          <td data-label="Eredeti / saját kategória">
                            {p.ownCategory ||
                              p.originalCategory ||
                              "Nincs saját kategória"}
                          </td>
                          <td data-label="Belső besorolás">
                            {p.internalCategory?.path.join(" / ") ||
                              "Még nincs egyértelmű besorolás"}
                          </td>
                          <td data-label="Státusz és védelem">
                            <span
                              className={
                                "badge " +
                                (p.group === "assigned" ? "good" : "")
                              }
                            >
                              {classificationLabels[p.group]}
                            </span>
                            {p.protectedEdit && (
                              <small>Kézi javítás védett</small>
                            )}
                          </td>
                          <td data-label="Forrás">{p.source}</td>
                          <td data-label="Művelet">
                            <button
                              disabled={pendingSearch}
                              onClick={() => setFocused(p)}
                              aria-label={`${p.title} részletei`}
                            >
                              Megnyitás
                            </button>
                            {editable && p.canEdit !== false && (
                              <button
                                disabled={pendingSearch}
                                onClick={() => editProduct(p)}
                                aria-label={`${p.title} besorolásának módosítása`}
                              >
                                Besorolás módosítása
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <div className="pager">
              <button
                disabled={!history.length || page.loading || pendingSearch}
                onClick={() => {
                  clearSelection();
                  setFocused(null);
                  setCursor(history.at(-1) ?? null);
                  setHistory(history.slice(0, -1));
                }}
              >
                Előző termékek
              </button>
              <button
                disabled={!page.data?.next || page.loading || pendingSearch}
                onClick={() => {
                  clearSelection();
                  setFocused(null);
                  setHistory([...history, cursor]);
                  setCursor(page.data?.next || null);
                }}
              >
                Következő termékek
              </button>
            </div>
          </>
        ) : (
          <>
            {ports.features?.mappingSearch !== false && (
              <label>
                Saját kategóriatérkép keresése
                <input
                  value={mappingSearch}
                  onChange={(e) => {
                    setMappingSearch(e.target.value);
                    setMappingCursor(null);
                    setMappingHistory([]);
                    setEditor(null);
                  }}
                />
              </label>
            )}
            {mappings.loading && (
              <p role="status">Kategóriatérképek betöltése…</p>
            )}
            {mappings.error && <p role="alert">{mappings.error}</p>}
            {mappings.data && !mappings.data.items.length && (
              <p>Még nincs a keresésnek megfelelő saját kategóriatérkép.</p>
            )}
            <ul className="classification-mappings">
              {mappings.data?.items.map((m) => (
                <li key={m.key}>
                  <h3>{m.title}</h3>
                  <p>Saját kategória: {m.originalCategory}</p>
                  <p>
                    Belső kategória:{" "}
                    {m.internalCategory?.path.join(" / ") || "Nincs jóváhagyva"}
                  </p>
                  <p>Profil: {m.profileText}</p>
                  <p>
                    {m.approved
                      ? "Jóváhagyott kategóriatérkép"
                      : "Ellenőrzést igényel"}{" "}
                    · Érintett termékek:{" "}
                    {m.affectedProducts.toLocaleString("hu-HU")}
                  </p>
                  {m.protectedEdit && <p>Kézi javítás védett</p>}
                  <p className="small muted">{m.auditText}</p>
                  {access.editMappings && writable && (
                    <button
                      disabled={mappingSearch !== mappingQuery}
                      onClick={() => editMapping(m)}
                      aria-label={`${m.title} kategóriatérképének szerkesztése`}
                    >
                      Kategóriatérkép szerkesztése
                    </button>
                  )}
                </li>
              ))}
            </ul>
            <div className="pager">
              <button
                disabled={!mappingHistory.length || mappings.loading}
                onClick={() => {
                  setEditor(null);
                  setMappingCursor(mappingHistory.at(-1) ?? null);
                  setMappingHistory(mappingHistory.slice(0, -1));
                }}
              >
                Előző kategóriatérképek
              </button>
              <button
                disabled={!mappings.data?.next || mappings.loading}
                onClick={() => {
                  setEditor(null);
                  setMappingHistory([...mappingHistory, mappingCursor]);
                  setMappingCursor(mappings.data?.next || null);
                }}
              >
                Következő kategóriatérképek
              </button>
            </div>
          </>
        )}
      </Panel>
      {focused && detail.loading && (
        <p role="status">Termékrészlet betöltése…</p>
      )}
      {focused && detail.error && <p role="alert">{detail.error}</p>}
      {active && tab === "products" && (
        <Panel title={active.title}>
          <ClassificationSummary product={active} />
          {active.group === "review" && !!active.alternatives.length && (
            <section aria-label="Besorolási alternatívák">
              <h3>Lehetséges belső kategóriák</h3>
              <ul className="classification-alternatives">
                {active.alternatives.slice(0, 3).map((c) => (
                  <li key={c.key}>
                    <span>{c.path.join(" / ")}</span>
                    {editable && active.canEdit !== false && c.selectable && (
                      <button
                        onClick={() =>
                          setEditor({
                            target: {
                              kind: "product",
                              key: active.key,
                              context: active.editContext,
                            },
                            own: active.ownCategory,
                            suggested: c,
                          })
                        }
                        aria-label={`Javaslat kiválasztása: ${c.title}`}
                      >
                        Javaslat kiválasztása
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {editable && active.canEdit !== false && (
            <button onClick={() => editProduct(active)}>
              Besorolás szerkesztése
            </button>
          )}
          {active.fields && (
            <section aria-label="Eredeti termékadatok">
              <h3>Eredeti termékadatok</h3>
              <dl className="data-list">
                {active.fields.map((f, i) => (
                  <div key={i}>
                    <dt>{f.label}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
          {!!active.history?.length && (
            <details>
              <summary>Besorolási előzmények</summary>
              <ul>
                {active.history.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </details>
          )}
          <button onClick={() => setFocused(null)}>
            Termékrészlet bezárása
          </button>
        </Panel>
      )}
      {editor && (
        <ClassificationEditor
          key={
            editor.target.kind +
            ("key" in editor.target ? editor.target.key : "bulk") +
            (editor.suggested?.key || "")
          }
          ports={ports}
          target={editor.target}
          ownCategory={editor.own}
          initialChoice={editor.suggested}
          onClose={() => setEditor(null)}
          onRefresh={refresh}
          onApplied={applied}
        />
      )}
      {access.manageThreshold && <ClassificationThreshold ports={ports} />}
    </div>
  );
}
