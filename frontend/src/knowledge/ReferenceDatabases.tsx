import React, { useEffect, useState, useCallback } from "react";
import { dateTime } from "../ui";
import "./knowledge.css";
type Request = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Page<T> = { items: T[]; total: number; offset: number; limit: number };
type Run = {
  id: number;
  source_id: number;
  file_name: string;
  state: string;
  counters: Record<string, number>;
  errors: { line: number | null; code: string; column?: number }[];
  started_at: string;
  finished_at: string | null;
  cursor: number;
  uploaded: boolean;
  retryable: boolean;
  headers: string[];
  mapping: Record<string, string>;
  preview: { line: number; values: string[] }[];
};
type Source = {
  id: number;
  name: string;
  kind: string;
  tenant_id: number | null;
  products: number;
  parameters: number;
  attribute_values: number;
  imported_at: string;
  updated_at: string | null;
  state: string;
  last_import: Run | null;
  usage_status: string;
  enrichment_enabled: boolean;
  usage_note: string | null;
  usage_basis: string;
  contribution: string;
  trust_level: string | null;
  excluded_columns: string[];
  quality: {
    valid_gtin_products: number;
    without_valid_gtin: number;
    with_name: number;
    verified_products: number;
  };
};
type Options = {
  knowledge_engine_available?: boolean;
  fields: { key: string; label: string }[];
  tenants: { id: number; name: string }[];
};
type Audit = {
  id: number;
  action: string;
  actor_id: number | null;
  created_at: string;
  details: { run_id?: number };
};
const states: Record<string, string> = {
  empty: "Még nincs import",
  queued: "Elemzésre vár",
  analyzing: "Elemzés alatt",
  preview: "Ellenőrzésre váró előnézet",
  queued_import: "Importálásra vár",
  converting: "Import előkészítése",
  running: "Importálás folyamatban",
  completed: "Befejezve",
  partial: "Részben sikeres",
  failed: "Sikertelen",
  cancelled: "Megszakítva",
};
const usageLabels: Record<string, string> = {
  approved_enrichment: "Dúsításhoz engedélyezett",
  restricted: "Korlátozott",
  internal_only: "Csak belső használatra",
  revoked: "Kizárt",
};
const contributions: Record<string, string> = {
  automatic: "Automatikusan használható terméktudás",
  pending: "KNOWLEDGE-01 átvételre előkészítve",
  excluded: "A közös dúsításból kizárva",
};
const counterLabels: Record<string, string> = {
  physical_rows: "Összes forrássor",
  data_rows: "Termékjelölt",
  empty_rows: "Üres sor",
  analyzed_rows: "Átvizsgált sor",
  prepared_rows: "Előkészített sor",
  rows: "Feldolgozott sor",
  created: "Új termék",
  updated: "Frissített termék",
  unchanged: "Változatlan termék",
  protected: "Védett, hitelesített termék",
  empty: "Üres sor",
  errors: "Hibás sor",
  excluded_cells: "Kizárt cella",
  columns: "Importált oszlop",
  excluded_columns: "Kizárt oszlop",
};
const errorLabels: Record<string, string> = {
  missing_sku: "Hiányzó cikkszám és használható EAN",
  queue_unavailable: "A háttérfeldolgozó nem érhető el; próbáld újra később.",
  processing_failed:
    "A feldolgozás megszakadt. Ellenőrizd a fájlt és próbáld újra; a már mentett rekordok megmaradnak.",
  invalid_gtin: "Érvénytelen EAN/GTIN kizárva",
  uncertain_identifier: "Bizonytalan Excel-azonosító kizárva",
  excluded_cell: "Képlet vagy nem tárolható cella kizárva",
};
const auditLabels: Record<string, string> = {
  "knowledge.source.update": "Forrásbeállítás módosítása",
  "unas.reference_usage": "Forrásbeállítás módosítása",
  "knowledge.upload": "Referenciafájl feltöltése",
  "knowledge.import.start": "Import indítása",
  "knowledge.import.repeat": "Import ismétlése",
  "knowledge.import.cancel": "Feldolgozás megszakítása",
  "knowledge.import.retry": "Feldolgozás folytatása",
};
const kindLabels: Record<string, string> = {
  csv: "CSV",
  xlsx: "XLSX",
  unas_export: "UNAS-export",
};
const active = (state: string) =>
  ["queued", "analyzing", "queued_import", "converting", "running"].includes(
    state,
  );
const message = (e: unknown) =>
  e instanceof Error ? e.message : "A művelet sikertelen.";

export default function ReferenceDatabases({ api }: { api: Request }) {
  const [sources, setSources] = useState<Page<Source> | null>(null);
  const [options, setOptions] = useState<Options>({ fields: [], tenants: [] });
  const [selected, setSelected] = useState<Source | null>(null);
  const [history, setHistory] = useState<Page<Run> | null>(null);
  const [events, setEvents] = useState<Page<Audit> | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [auditOffset, setAuditOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uploadSource, setUploadSource] = useState<Source | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [scope, setScope] = useState("system");
  const [tenant, setTenant] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [name, setName] = useState("");
  const [usage, setUsage] = useState("restricted");
  const [enabled, setEnabled] = useState(false);
  const [note, setNote] = useState("");
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    let alive = true;
    void api<Options>("/knowledge-admin/options")
      .then((v) => {
        if (alive) setOptions(v);
      })
      .catch((e) => {
        if (alive) setError(message(e));
      });
    return () => {
      alive = false;
    };
  }, [api]);
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      void api<Page<Source>>(
        `/knowledge-admin/sources?offset=${offset}&q=${encodeURIComponent(query)}`,
      )
        .then((v) => {
          if (alive) setSources(v);
        })
        .catch((e) => {
          if (alive) setError(message(e));
        });
    }, 200);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, offset, query, revision]);
  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId) return;
    let alive = true;
    void Promise.all([
      api<Source>(`/knowledge-admin/sources/${selectedId}`),
      api<Page<Run>>(
        `/knowledge-admin/sources/${selectedId}/imports?offset=${historyOffset}`,
      ),
      api<Page<Audit>>(
        `/knowledge-admin/sources/${selectedId}/audit?offset=${auditOffset}`,
      ),
    ])
      .then(([source, imports, audit]) => {
        if (alive) {
          setSelected(source);
          setHistory(imports);
          setEvents(audit);
        }
      })
      .catch((e) => {
        if (alive) setError(message(e));
      });
    return () => {
      alive = false;
    };
  }, [api, selectedId, historyOffset, auditOffset, revision]);
  const runId = run?.id;
  const running = run ? active(run.state) : false;
  useEffect(() => {
    if (!runId || !running) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Run>(`/knowledge-admin/imports/${runId}`);
        if (!alive) return;
        setRun(next);
        if (next.state === "preview") setMapping(next.mapping);
        if (active(next.state)) timer = setTimeout(poll, 2000);
        else refresh();
      } catch (e) {
        if (alive) setError(message(e));
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, runId, running, refresh]);
  function choose(source: Source) {
    setSelected(source);
    setHistoryOffset(0);
    setAuditOffset(0);
    setName(source.name);
    setUsage(source.usage_status);
    setEnabled(source.enrichment_enabled);
    setNote(source.usage_note || "");
    setRun(null);
    setError("");
  }
  function showRun(next: Run) {
    setRun(next);
    setMapping(next.mapping);
    refresh();
  }
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function command(action: string) {
    if (run)
      await act(async () =>
        showRun(
          await api<Run>(
            `/knowledge-admin/imports/${run.id}/${action}`,
            "POST",
          ),
        ),
      );
  }
  function refreshSource() {
    if (selected) {
      setUploadSource(selected);
      setSourceName(selected.name);
      setScope(selected.tenant_id ? "tenant" : "system");
      setTenant(selected.tenant_id ? String(selected.tenant_id) : "");
      setAuthorized(false);
      document
        .getElementById("reference-upload")
        ?.scrollIntoView({ behavior: "smooth" });
    }
  }
  return (
    <div className="knowledge-admin">
      <p className="notice">
        Központi referenciaforrások és ellenőrzött terméktudás. A feltöltés nem
        indít AI-kutatást. A hitelesített adatokat az import nem írja felül.
      </p>
      {error && <p role="alert">{error}</p>}
      <section
        className="card padded"
        id="reference-upload"
        aria-label="Új referenciaadat-import"
      >
        <h2>
          {uploadSource ? "Forrás frissítése" : "Új referenciaadat-import"}
        </h2>
        {uploadSource && (
          <p>
            {uploadSource.name}{" "}
            <button
              onClick={() => {
                setUploadSource(null);
                setSourceName("");
                setAuthorized(false);
              }}
            >
              Új forrás helyette
            </button>
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const file = (form.elements.namedItem("file") as HTMLInputElement)
              .files?.[0];
            if (!file) return;
            void act(async () => {
              const body = new FormData();
              body.set("file", file);
              body.set("source_name", sourceName);
              body.set("scope", scope);
              body.set("reuse_authorized", String(authorized));
              if (uploadSource) body.set("source_id", String(uploadSource.id));
              if (scope === "tenant") body.set("tenant_id", tenant);
              const next = await api<Run>(
                "/knowledge-admin/uploads",
                "POST",
                body,
              );
              showRun(next);
              if (next.state === "preview") setMapping(next.mapping);
              const source = await api<Source>(
                `/knowledge-admin/sources/${next.source_id}`,
              );
              setSelected(source);
              setName(source.name);
              setUsage(source.usage_status);
              setEnabled(source.enrichment_enabled);
              setNote(source.usage_note || "");
              setAuthorized(false);
              form.reset();
            });
          }}
        >
          <div className="knowledge-form-grid">
            <label>
              Forrás megnevezése
              <input
                required
                maxLength={255}
                value={sourceName}
                onChange={(e) => setSourceName(e.target.value)}
              />
            </label>
            <label>
              Import hatóköre
              <select
                aria-label="Import hatóköre"
                value={scope}
                disabled={!!uploadSource}
                onChange={(e) => setScope(e.target.value)}
              >
                <option value="system">Rendszerszintű referenciaimport</option>
                <option value="tenant">
                  Ügyfélhez kötött, átvételre előkészítve
                </option>
              </select>
            </label>
            {scope === "tenant" && (
              <label>
                Ügyfél
                <select
                  aria-label="Referenciaimport ügyfele"
                  required
                  value={tenant}
                  disabled={!!uploadSource}
                  onChange={(e) => setTenant(e.target.value)}
                >
                  <option value="">Válassz ügyfelet</option>
                  {options.tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Referencia CSV/XLSX fájl
              <input required name="file" type="file" accept=".csv,.xlsx" />
            </label>
          </div>
          {scope === "system" ? (
            <label className="check">
              <input
                type="checkbox"
                required
                checked={authorized}
                onChange={(e) => setAuthorized(e.target.checked)}
              />
              Jogosult vagyok a termékadatok központi újrahasznosítására. A
              fájlban szereplő személyes és ügyfélspecifikus adatokat nem
              jelölöm meg terméktudásként.
            </label>
          ) : (
            <p>
              Az ügyfélforrás nem kerül a közös keresésbe. A KNOWLEDGE-01 motor
              későbbi, jogosultsághoz kötött átvételére készítjük elő.
            </p>
          )}
          <button disabled={busy || (scope === "system" && !authorized)}>
            Feltöltés és oszlopfelismerés
          </button>
        </form>
      </section>
      {run && (
        <section className="card padded" aria-label="Referenciaimport állapota">
          <h2>
            Import #{run.id} – {states[run.state] || run.state}
          </h2>
          <p className="knowledge-filename">{run.file_name}</p>
          {running && (
            <p role="status">
              Háttérfeldolgozás folyamatban. Az oldal más műveletekre is
              használható.
            </p>
          )}
          <dl className="knowledge-metrics">
            {Object.entries(run.counters).map(([key, value]) => (
              <div key={key}>
                <dt>{counterLabels[key] || key}</dt>
                <dd>{value.toLocaleString("hu-HU")}</dd>
              </div>
            ))}
          </dl>
          {run.state === "preview" && (
            <>
              <p>
                Csak a kijelölt termékadatok kerülnek a referenciatárba. Az
                ismeretlen oszlopok kizárva maradnak; árak, készletek és
                ügyféladatok nem lesznek közös terméktudás.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Forrásoszlop</th>
                      <th>Felismert jelentés</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.headers.map((header, i) => (
                      <tr key={i}>
                        <td>
                          {i + 1}. {header || "(üres fejléc)"}
                        </td>
                        <td>
                          <select
                            aria-label={`Referencia megfeleltetés: ${header || i + 1}`}
                            value={mapping[String(i)] || "exclude"}
                            onChange={(e) =>
                              setMapping((prev) => ({
                                ...prev,
                                [String(i)]: e.target.value,
                              }))
                            }
                          >
                            {options.fields.map((field) => (
                              <option key={field.key} value={field.key}>
                                {field.label}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="actions">
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      const next = await api<Run>(
                        `/knowledge-admin/imports/${run.id}/preview`,
                        "POST",
                        { mapping },
                      );
                      setRun(next);
                    })
                  }
                >
                  Előnézet frissítése
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () =>
                      showRun(
                        await api<Run>(
                          `/knowledge-admin/imports/${run.id}/start`,
                          "POST",
                          { mapping },
                        ),
                      ),
                    )
                  }
                >
                  Referenciaimport indítása
                </button>
              </div>
            </>
          )}
          {!!run.preview.length && (
            <details>
              <summary>Termékadatok előnézete</summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Forrássor</th>
                      {run.headers.map((header, i) => (
                        <th key={i}>{header || "(üres fejléc)"}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {run.preview.map((row) => (
                      <tr key={row.line}>
                        <td>{row.line}</td>
                        {row.values.map((value, i) => (
                          <td key={i}>{value}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {!!run.errors.length && (
            <details open>
              <summary>
                Importálási hibák és figyelmeztetések ({run.errors.length})
              </summary>
              <ul>
                {run.errors.map((error, i) => (
                  <li key={i}>
                    {error.line ? `${error.line}. forrássor: ` : ""}
                    {errorLabels[error.code] ||
                      "Érvénytelen rekord; ellenőrizd a sor adatait."}
                    {error.column !== undefined
                      ? ` (${error.column + 1}. oszlop)`
                      : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <div className="actions">
            {(active(run.state) || run.state === "preview") && (
              <button disabled={busy} onClick={() => void command("cancel")}>
                Feldolgozás megszakítása
              </button>
            )}
            {run.retryable && (
              <button disabled={busy} onClick={() => void command("retry")}>
                Feldolgozás folytatása
              </button>
            )}
            {run.uploaded && ["completed", "partial"].includes(run.state) && (
              <button disabled={busy} onClick={() => void command("repeat")}>
                Import ismétlése
              </button>
            )}
          </div>
        </section>
      )}
      <div className="knowledge-columns">
        <section className="card padded" aria-label="Referenciaforrások">
          <h2>Referenciaforrások ({sources?.total ?? "…"})</h2>
          <label>
            Forrás keresése
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          {!sources?.items.length && sources && (
            <p>Még nincs ilyen referenciaforrás.</p>
          )}
          <ul className="knowledge-source-list">
            {sources?.items.map((source) => (
              <li key={source.id}>
                <button
                  aria-pressed={selected?.id === source.id}
                  onClick={() => choose(source)}
                >
                  <strong>{source.name}</strong>
                  <span>
                    {kindLabels[source.kind] || source.kind} ·{" "}
                    {source.tenant_id ? "Ügyfélforrás" : "Rendszerszintű"}
                  </span>
                  <span>
                    {source.products.toLocaleString("hu-HU")} termék ·{" "}
                    {source.parameters} paraméter
                  </span>
                  <span>{states[source.state] || source.state}</span>
                  <small>
                    Érvényes GTIN: {source.quality.valid_gtin_products} /{" "}
                    {source.products} · Importhibák:{" "}
                    {source.last_import?.counters.errors || 0}
                  </small>
                  <small>
                    {usageLabels[source.usage_status]} ·{" "}
                    {contributions[source.contribution]}
                  </small>
                </button>
              </li>
            ))}
          </ul>
          <div className="pager">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Előző források
            </button>
            <button
              disabled={
                !sources || offset + sources.items.length >= sources.total
              }
              onClick={() => setOffset(offset + 25)}
            >
              További források
            </button>
          </div>
        </section>
        <section
          className="card padded"
          aria-label="Referenciaforrás részletei"
        >
          {!selected ? (
            <p>Válassz egy forrást a részletekhez.</p>
          ) : (
            <>
              <h2>{selected.name}</h2>
              <p>
                {usageLabels[selected.usage_status]} ·{" "}
                {contributions[selected.contribution]}
              </p>
              <dl className="knowledge-metrics">
                <div>
                  <dt>Termékek</dt>
                  <dd>{selected.products.toLocaleString("hu-HU")}</dd>
                </div>
                <div>
                  <dt>Paraméterek</dt>
                  <dd>{selected.parameters}</dd>
                </div>
                <div>
                  <dt>Paraméterértékek</dt>
                  <dd>{selected.attribute_values.toLocaleString("hu-HU")}</dd>
                </div>
                <div>
                  <dt>Hitelesített termékek</dt>
                  <dd>{selected.quality.verified_products}</dd>
                </div>
              </dl>
              <p>
                Forrás felvétele: {dateTime(selected.imported_at)} · Utolsó
                adatfrissítés:{" "}
                {selected.updated_at
                  ? dateTime(selected.updated_at)
                  : "Még nincs"}
              </p>
              <h3>Adatminőség</h3>
              <p>
                Érvényes EAN/GTIN: {selected.quality.valid_gtin_products} /{" "}
                {selected.products}; névvel rendelkező:{" "}
                {selected.quality.with_name} / {selected.products}. Érvényes
                GTIN nélkül: {selected.quality.without_valid_gtin}.
              </p>
              <button
                disabled={selected.kind === "tenant_import"}
                onClick={refreshSource}
              >
                Forrás frissítése új fájllal
              </button>
              <details>
                <summary>Forrás és felhasználás kezelése</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(async () => {
                      const next = await api<Source>(
                        `/knowledge-admin/sources/${selected.id}`,
                        "PUT",
                        {
                          name,
                          usage_status: usage,
                          enrichment_enabled: enabled,
                          usage_note: note,
                        },
                      );
                      choose(next);
                      refresh();
                    });
                  }}
                >
                  <label>
                    Forrás neve
                    <input
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <label>
                    Felhasználási állapot
                    <select
                      aria-label="Felhasználási állapot"
                      value={usage}
                      onChange={(e) => {
                        setUsage(e.target.value);
                        if (e.target.value !== "approved_enrichment")
                          setEnabled(false);
                      }}
                    >
                      {Object.entries(usageLabels).map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      disabled={
                        usage !== "approved_enrichment" ||
                        (!!selected.tenant_id &&
                          selected.kind !== "tenant_import")
                      }
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                    />
                    Közös adatdúsításhoz használható
                  </label>
                  <label>
                    Döntés indoklása
                    <textarea
                      required
                      minLength={3}
                      maxLength={1000}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>Forrásbeállítás mentése</button>
                </form>
              </details>
              <h3>Importelőzmények</h3>
              <ul className="knowledge-history">
                {history?.items.map((item) => (
                  <li key={item.id}>
                    <button
                      onClick={() =>
                        void act(async () =>
                          showRun(
                            await api<Run>(
                              `/knowledge-admin/imports/${item.id}`,
                            ),
                          ),
                        )
                      }
                    >
                      #{item.id} · {states[item.state] || item.state} ·{" "}
                      {item.file_name}
                    </button>
                    <small>
                      {dateTime(item.started_at)}
                      {item.finished_at
                        ? ` – ${dateTime(item.finished_at)}`
                        : ""}
                    </small>
                  </li>
                ))}
              </ul>
              <div className="pager">
                <button
                  disabled={!historyOffset}
                  onClick={() =>
                    setHistoryOffset(Math.max(0, historyOffset - 25))
                  }
                >
                  Korábbi oldal
                </button>
                <button
                  disabled={
                    !history ||
                    historyOffset + history.items.length >= history.total
                  }
                  onClick={() => setHistoryOffset(historyOffset + 25)}
                >
                  Régebbi importok
                </button>
              </div>
              <h3>Auditnapló</h3>
              <ul className="knowledge-history">
                {events?.items.map((event) => (
                  <li key={event.id}>
                    {auditLabels[event.action] || "Referenciaadat-művelet"} ·
                    felhasználó #{event.actor_id ?? "rendszer"}
                    {event.details.run_id
                      ? ` · import #${event.details.run_id}`
                      : ""}
                    <small>{dateTime(event.created_at)}</small>
                  </li>
                ))}
              </ul>
              <div className="pager">
                <button
                  disabled={!auditOffset}
                  onClick={() => setAuditOffset(Math.max(0, auditOffset - 25))}
                >
                  Előző naplóbejegyzések
                </button>
                <button
                  disabled={
                    !events || auditOffset + events.items.length >= events.total
                  }
                  onClick={() => setAuditOffset(auditOffset + 25)}
                >
                  Régebbi naplóbejegyzések
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
