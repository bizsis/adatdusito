import type {
  ParameterJob,
  ParameterServices,
} from "./parameters/presentation";
import { Help } from "./ui";
import React, { useState, useEffect, useCallback, lazy, Suspense } from "react";
import {
  ImportClassificationSummary,
  type ImportClassificationSummaryProps,
} from "./classification/ClassificationSummary";
const ParameterJobPanel = lazy(() =>
  import("./parameters/ParameterJobPanel").then((m) => ({
    default: m.ParameterJobPanel,
  })),
);
type Request = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Column = {
  index: number;
  header: string;
  field: string | null;
  confidence: number;
  method: string;
  critical: boolean;
  samples: string[];
  suggested_field?: string | null;
  requires_decision?: boolean;
  warnings?: string[];
  meaning?: string | null;
  confirmed_context?: Record<string, string> | null;
};
type Run = {
  id: number;
  supplier_id: number;
  profile_id?: number | null;
  filename: string;
  state: string;
  cursor: number;
  error: string | null;
  counters: Record<string, number>;
  created_at?: string;
  deletable?: boolean;
  analysis: {
    data_rows?: number;
    physical_rows?: number;
    empty_rows?: number;
    run_product_limit?: number;
    columns?: Column[];
    preview?: string[][];
    headers?: string[];
    drift?: string[];
    suggested_mapping?: Record<string, string>;
    matched_profile_id?: number;
  };
  config: Record<string, unknown>;
};
type Field = {
  key: string;
  label: string;
  type: string;
  required: boolean;
  internal_field?: string;
  default?: string;
  allowed?: string[];
  validation?: string;
};
type DeletionPlan = {
  run_id: number;
  filename: string;
  state: string;
  deletable: boolean;
  reason: string | null;
  deletes: { source_file_chunks: number; source_file_bytes: number };
  references: Record<string, number>;
};
type Interpreted = Record<
  string,
  { value: string | null; raw: string; issues: string[] }
>;
const PAGE = 25;
const issueLabels: Record<string, string> = {
  scientific_identifier_requires_review:
    "tudományos jelölés – a teljes azonosító nem bizonyítható",
  invalid_gtin: "nem érvényes EAN/GTIN – nem mentjük EAN-ként",
  negative_value_requires_rule: "negatív érték – értelmezési szabály szükséges",
  excel_identifier_precision_requires_review: "Excel-pontosság ellenőrizendő",
  formula_requires_review: "képlet – ellenőrizendő",
  invalid_number: "nem szám",
  uncertain_date: "bizonytalan dátum",
  missing_identity_or_name: "nincs név vagy azonosító",
  column_count_mismatch: "eltérő oszlopszám",
  duplicate_key: "ismétlődő kulcs",
  conflicting_duplicate_key: "ütköző ismétlődő kulcs",
};
const columnWarnings: Record<string, string> = {
  scientific_notation_identifier:
    "Tudományos jelölésű azonosítók (pl. 8,71999E+12): a teljes EAN nem rekonstruálható, ezek a sorok nem kapnak EAN-t. Javítás: az Excelben a vonalkód oszlopot mentés előtt Szám (0 tizedesjegy) vagy Szöveg formátumra kell állítani, majd újra feltölteni.",
  invalid_gtin_samples:
    "Érvénytelen EAN/GTIN minták: ezek a sorok nem kapnak EAN-t, a nyers érték megmarad.",
  negative_values:
    "Negatív értékek: nyers forrásadatként megmaradnak, eladható készlet nem lesz belőlük; az értelmezés külön döntés.",
};
const counterLabels: Record<string, string> = {
  ready: "feldolgozva",
  empty: "üres sor",
  error: "hibás",
  conflict: "ütközés",
  duplicate: "ismétlődés",
  not_seen_in_full_feed: "teljes feedből hiányzó",
};
// Owner decision (#42, 2026-11-17): confirmed meanings of these source headers.
const meanings: Record<string, string> = {
  last_purchase_price: "utolsó beszerzési ár",
  list_price_net_huf: "listaár – mindig nettó, HUF",
};
const deleteRefusals: Record<string, string> = {
  approved_or_processed:
    "Jóváhagyott vagy feldolgozott import nem törölhető; a termékek és a napló megmaradnak.",
  running: "Az elemzés éppen fut; várd meg a végét, vagy szakítsd meg.",
  referenced: "Az importra termék vagy változásnapló hivatkozik.",
};
const issueText = (code: string) => {
  const [field, problem] = code.includes(":") ? code.split(":") : ["", code];
  const text = issueLabels[problem] || problem;
  return field ? `${field}: ${text}` : text;
};
const formatDate = (value?: string) =>
  value ? new Date(value).toLocaleString("hu-HU") : "–";
const labels: Record<string, string> = {
  uploaded: "Feltöltve / elemzésre vár",
  awaiting_approval: "Jóváhagyásra vár",
  processing: "Feldolgozás alatt",
  paused: "Szüneteltetve",
  completed: "Befejezve",
  partial: "Részben sikeres",
  failed: "Hibás",
  cancelled: "Megszakítva",
};
export function ImportWorkspace({
  api,
  canManage,
  permissions,
  classificationSummary,
  parameterJob,
}: {
  api: Request;
  canManage: boolean;
  permissions?: string[];
  classificationSummary?: ImportClassificationSummaryProps;
  parameterJob?: ParameterServices & { initial: ParameterJob };
}) {
  const canCreate = permissions
    ? permissions.includes("imports.create")
    : canManage;
  const canApprove = permissions
    ? permissions.includes("imports.approve")
    : canManage;
  const canCancel = permissions
    ? permissions.includes("imports.cancel")
    : canManage;
  const [exportProfiles, EP] = useState<
    { id: number; name: string; fields: Field[] }[]
  >([]);
  const [exportProfile, XP] = useState("");
  const [chosenProfile, CP] = useState("");
  const [historyOffset, HO] = useState(0);
  const [sourceOffset, SO] = useState(0);
  const [previewSize, PZ] = useState(10);
  const [deletion, DL] = useState<DeletionPlan | null>(null);
  const [notice, NT] = useState("");
  const [sourcePreview, SP] = useState<{
    items: { line: number; raw: string[]; interpreted?: Interpreted }[];
    has_more: boolean;
  }>({ items: [], has_more: false });
  const [financialDefaults, FD] = useState({
    price_type: "",
    tax_basis: "",
    currency: "",
  });
  const [joins, J] = useState<
    { column: number; field: string; exact_sample_matches: number }[]
  >([]);
  const [suppliers, S] = useState<{ id: number; name: string }[]>([]),
    [supplier, T] = useState(""),
    [name, N] = useState(""),
    [runs, R] = useState<Run[]>([]),
    [run, U] = useState<Run | null>(null),
    [fields, F] = useState<{ key: string; label: string }[]>([]),
    [mapping, M] = useState<Record<string, string>>({}),
    [profile, P] = useState("Importprofil"),
    [key, K] = useState(""),
    [financial, V] = useState(false),
    [automatic, A] = useState(false),
    [feed, G] = useState("partial"),
    [error, E] = useState(""),
    [rows, Q] = useState<
      {
        line: number;
        raw: string[];
        normalized: { fields?: Record<string, string | null> } & Record<
          string,
          unknown
        >;
        issues: string[];
        state: string;
      }[]
    >([]),
    [offset, O] = useState(0),
    [profiles, PS] = useState<
      {
        id: number;
        name: string;
        version: number;
        config: {
          mapping: Record<string, string>;
          currency?: string;
          price_type?: string;
          tax_basis?: string;
          identity_field?: string;
          feed_type?: string;
          automatic?: boolean;
          analysis: { headers: string[] };
        };
      }[]
    >([]),
    [busy, B] = useState(false),
    [sheet, SH] = useState(""),
    [header, H] = useState(0),
    [delimiter, D] = useState(""),
    [encoding, EN] = useState("");
  const act = useCallback(async (fn: () => Promise<void>) => {
    E("");
    B(true);
    try {
      await fn();
    } catch (e) {
      E(String(e));
    } finally {
      B(false);
    }
  }, []);
  const canReadExports = !permissions || permissions.includes("exports.read");
  const refresh = useCallback(async () => {
    S(await api("/imports/suppliers"));
    HO(0);
    R(await api("/imports/runs"));
    if (canReadExports) EP(await api("/imports/export-profiles"));
    else EP([]);
  }, [api, canReadExports]);
  const select = useCallback((r: Run) => {
    U(r);
    T(String(r.supplier_id));
    CP(r.profile_id ? String(r.profile_id) : "");
    // Owner-confirmed context (e.g. LISTPRICE is net HUF) only prefills empty
    // defaults; the operator still has to approve the financial mapping.
    const context = Object.assign(
      {},
      ...(r.analysis.columns || [])
        .filter((c) => c.field && c.confirmed_context)
        .map((c) => c.confirmed_context),
    ) as Record<string, string>;
    FD({
      currency: String(r.config.currency || context.currency || ""),
      price_type: String(r.config.price_type || context.price_type || ""),
      tax_basis: String(r.config.tax_basis || context.tax_basis || ""),
    });
    A(false);
    G("partial");
    SP({ items: [], has_more: false });
    J([]);

    SH(String(r.config.sheet || ""));
    H(Number(r.config.header_line || 0));
    D(String(r.config.delimiter || ""));
    EN(String(r.config.encoding || ""));
    O(0);
    SO(0);
    Q([]);
    M(
      r.analysis.suggested_mapping ||
        Object.fromEntries(
          (r.analysis.columns || [])
            .filter((c) => c.field)
            .map((c) => [String(c.index), c.field!]),
        ),
    );
    V(false);
    K("");
  }, []);
  const runId = run?.id,
    runState = run?.state;
  const hasColumns = !!run?.analysis.columns;
  useEffect(() => {
    act(async () => {
      await refresh();
      F(await api("/imports/fields"));
    });
  }, [api, act, refresh]);
  useEffect(() => {
    if (supplier)
      api<typeof profiles>("/imports/profiles?supplier_id=" + supplier)
        .then(PS)
        .catch((e) => E(String(e)));
  }, [api, supplier, runId]);
  useEffect(() => {
    if (!runId) return;
    let active = true;
    const id = setInterval(() => {
      api<Run>("/imports/runs/" + runId)
        .then((r) => {
          if (!active) return;
          if (r.state !== runState && r.state === "awaiting_approval")
            select(r);
          else U(r);
          if (r.state !== runState) refresh().catch((e) => E(String(e)));
        })
        .catch((e) => {
          if (active) E(String(e));
        });
    }, 2000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [api, runId, runState, refresh, select]);
  useEffect(() => {
    if (runId)
      api<{ items: typeof rows }>(
        `/imports/runs/${runId}/rows?offset=${offset}`,
      )
        .then((r) => Q(r.items))
        .catch((e) => E(String(e)));
  }, [api, runId, runState, offset]);
  useEffect(() => {
    if (runId && hasColumns)
      api<typeof joins>(`/imports/runs/${runId}/join-suggestions`)
        .then(J)
        .catch((e) => E(String(e)));
  }, [api, runId, runState, hasColumns]);
  const columns = run?.analysis.columns || [];
  useEffect(() => {
    if (runId && runState === "awaiting_approval")
      api<typeof sourcePreview>(`/imports/runs/${runId}/preview`, "POST", {
        mapping,
        offset: sourceOffset,
        limit: previewSize,
      })
        .then(SP)
        .catch((e) => E(String(e)));
  }, [api, runId, runState, sourceOffset, previewSize, mapping]);
  const fieldLabel = (key: string) =>
    fields.find((f) => f.key === key)?.label || key;
  const mappedFields = Object.entries(mapping).filter(([, v]) => v);
  // Processed rows show the mapping that was actually approved for the run.
  const approvedFields = Object.entries(
    (run?.config.mapping as Record<string, string> | undefined) || {},
  );
  const loadHistory = async (next: number) => {
    const page = await api<Run[]>(`/imports/runs?offset=${next}`);
    HO(next);
    R(page);
    return page;
  };
  // Deletion is confirmed against the server's own dry run, and success is
  // reported only after the list has been re-read from the server.
  const askDelete = (id: number) =>
    act(async () => {
      NT("");
      DL(await api<DeletionPlan>(`/imports/runs/${id}/deletion`));
    });
  const confirmDelete = (plan: DeletionPlan) =>
    act(async () => {
      await api(`/imports/runs/${plan.run_id}`, "DELETE");
      DL(null);
      if (run?.id === plan.run_id) U(null);
      const page = await loadHistory(historyOffset);
      NT(
        page.some((r) => r.id === plan.run_id)
          ? `A(z) #${plan.run_id} import még szerepel a listában; frissítsd az oldalt.`
          : `A(z) #${plan.run_id} import (${plan.filename}) törölve.`,
      );
    });
  const targetFields =
    exportProfiles.find((p) => p.id === Number(exportProfile))?.fields || [];
  return (
    <>
      {run?.analysis.run_product_limit !== undefined && (
        <p className="notice">
          Ebben a futásban{" "}
          {run.analysis.data_rows?.toLocaleString("hu-HU") ??
            "ismeretlen számú"}{" "}
          termék; a szerver futásonkénti korlátja{" "}
          {run.analysis.run_product_limit.toLocaleString("hu-HU")}. Ez nem a
          munkaterület teljes termékszámának korlátja. Nagyobb fájlt több
          futásra kell bontani.
        </p>
      )}
      {parameterJob && (
        <Suspense fallback={<p role="status">Előkészítési futás betöltése…</p>}>
          <ParameterJobPanel {...parameterJob} />
        </Suspense>
      )}
      {classificationSummary && (
        <ImportClassificationSummary {...classificationSummary} />
      )}
      <section className="card padded">
        <h2 className="field-title">
          Beszállítói import
          <Help topic="importMapping" />
        </h2>
        <p>
          Feltöltés → felismerés → megfeleltetés → jóváhagyás. AI-kredit nélkül
          is használható.
        </p>
        {error && <p role="alert">{error}</p>}
        <label>
          Beszállító
          <select
            value={supplier}
            onChange={(e) => {
              T(e.target.value);
              CP("");
            }}
          >
            <option value="">Válassz beszállítót</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {(canManage || canCreate) && (
          <>
            {canManage && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  act(async () => {
                    const s = await api<{ id: number }>(
                      "/imports/suppliers",
                      "POST",
                      { name },
                    );
                    await refresh();
                    T(String(s.id));
                    N("");
                  });
                }}
              >
                <label>
                  Új beszállító neve
                  <input
                    value={name}
                    onChange={(e) => N(e.target.value)}
                    required
                  />
                </label>
                <button disabled={busy}>Beszállító létrehozása</button>
              </form>
            )}
            <details>
              <summary>Haladó fájlbeállítások</summary>
              <label>
                Munkalap neve (üres: első)
                <input value={sheet} onChange={(e) => SH(e.target.value)} />
              </label>
              <label>
                Fejléc sora (0: felismerés)
                <input
                  type="number"
                  min="0"
                  max="20"
                  value={header}
                  onChange={(e) => H(Number(e.target.value))}
                />
              </label>
              <label>
                CSV elválasztó
                <select value={delimiter} onChange={(e) => D(e.target.value)}>
                  <option value="">Felismerés</option>
                  {[";", ",", "\t", "|"].map((x) => (
                    <option key={x} value={x}>
                      {x === "\t" ? "Tabulátor" : x}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Kódolás
                <select value={encoding} onChange={(e) => EN(e.target.value)}>
                  <option value="">Felismerés</option>
                  {["utf-8-sig", "utf-16", "cp1250", "cp1252"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
            </details>
            <label>
              Importprofil feltöltéshez
              <select
                value={chosenProfile}
                onChange={(e) => CP(e.target.value)}
              >
                <option value="">
                  Automatikus profilfelismerés / új profil
                </option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} v{p.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              CSV/XLSX fájl
              <input
                type="file"
                accept=".csv,.xlsx"
                disabled={!supplier || busy || !canCreate}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  act(async () => {
                    const form = new FormData();
                    form.append("file", file);
                    form.append("supplier_id", supplier);
                    if (chosenProfile) form.append("profile_id", chosenProfile);
                    form.append(
                      "settings",
                      JSON.stringify({
                        ...(sheet && { sheet }),
                        ...(header && { header_line: header }),
                        ...(delimiter && { delimiter }),
                        ...(encoding && { encoding }),
                      }),
                    );
                    select(await api("/imports/runs", "POST", form));
                    await refresh();
                  });
                }}
              />
            </label>
          </>
        )}
      </section>
      <section className="card padded" aria-labelledby="import-history-title">
        <h2 id="import-history-title">Importelőzmények</h2>
        {notice && <p role="status">{notice}</p>}
        {deletion && (
          <div
            className="confirm-panel"
            role="alertdialog"
            aria-labelledby="delete-title"
            aria-describedby="delete-body"
          >
            <h3 id="delete-title">
              #{deletion.run_id} {deletion.filename} törlése
            </h3>
            <div id="delete-body">
              {deletion.deletable ? (
                <>
                  <p>Véglegesen törlődik:</p>
                  <ul>
                    <li>az importrekord, az elemzés és a fájlbeállítások;</li>
                    <li>
                      a tárolt forrásfájl (
                      {deletion.deletes.source_file_bytes.toLocaleString("hu-HU")}{" "}
                      bájt).
                    </li>
                  </ul>
                  <p>
                    Megmarad: a beszállító, a mentett importprofilok, a
                    termékek, a többi import és az auditnapló. Ebből az
                    importból termék nem készült.
                  </p>
                </>
              ) : (
                <p role="alert">
                  Nem törölhető:{" "}
                  {deleteRefusals[deletion.reason || ""] || deletion.reason}
                </p>
              )}
            </div>
            {deletion.deletable && (
              <button
                className="danger"
                disabled={busy}
                onClick={() => confirmDelete(deletion)}
              >
                Végleges törlés
              </button>
            )}
            <button disabled={busy} onClick={() => DL(null)}>
              Mégsem
            </button>
          </div>
        )}
        {!runs.length ? (
          <p className="empty-state">
            {historyOffset ? "Nincs több import." : "Még nincs import."}
          </p>
        ) : (
          <div className="table-wrap">
            <table className="import-history">
              <thead>
                <tr>
                  <th scope="col">Import</th>
                  <th scope="col">Állapot</th>
                  <th scope="col">Létrehozva</th>
                  <th scope="col">Műveletek</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.id}
                    aria-current={run?.id === r.id ? "true" : undefined}
                  >
                    <td data-label="Import">
                      <span className="file-name" title={r.filename}>
                        #{r.id} {r.filename}
                      </span>
                    </td>
                    <td data-label="Állapot">{labels[r.state] || r.state}</td>
                    <td data-label="Létrehozva">{formatDate(r.created_at)}</td>
                    <td data-label="Műveletek" className="row-actions">
                      <button
                        onClick={() => select(r)}
                        aria-label={`#${r.id} ${r.filename} megnyitása`}
                      >
                        Megnyitás
                      </button>
                      {canManage && r.deletable && (
                        <button
                          className="danger"
                          disabled={busy}
                          onClick={() => askDelete(r.id)}
                          aria-label={`#${r.id} ${r.filename} törlése`}
                        >
                          Törlés
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pager">
          <button
            disabled={!historyOffset || busy}
            onClick={() =>
              act(async () => {
                await loadHistory(Math.max(0, historyOffset - PAGE));
              })
            }
          >
            Korábbi oldal
          </button>
          <span>
            {runs.length
              ? `${historyOffset + 1}–${historyOffset + runs.length}`
              : "–"}
          </span>
          <button
            disabled={runs.length < PAGE || busy}
            onClick={() =>
              act(async () => {
                await loadHistory(historyOffset + PAGE);
              })
            }
          >
            További importok
          </button>
        </div>
      </section>
      {run && (
        <section className="card padded">
          <h2 className="run-title">
            <span className="file-name" title={run.filename}>
              #{run.id} – {labels[run.state] || run.state}
            </span>
          </h2>
          <p className="run-file" title={run.filename}>
            {run.filename}
          </p>
          {run.analysis.physical_rows !== undefined && (
            <p className="row-counts">
              Összes sor:{" "}
              {run.analysis.physical_rows.toLocaleString("hu-HU")} · nem üres
              (termékjelölt): {run.analysis.data_rows?.toLocaleString("hu-HU")}{" "}
              · kihagyott üres sor:{" "}
              {run.analysis.empty_rows?.toLocaleString("hu-HU")}
            </p>
          )}
          {!!Object.keys(run.counters).length && (
            <p>
              Eredmény:{" "}
              {Object.entries(run.counters)
                .map(
                  ([k, v]) =>
                    `${counterLabels[k] || k}: ${v.toLocaleString("hu-HU")}`,
                )
                .join(" · ")}
            </p>
          )}
          {run.error && <p role="alert">{run.error}</p>}
          <a href={`/api/v1/imports/runs/${run.id}/file`}>
            Eredeti fájl letöltése
          </a>{" "}
          ·{" "}
          <a href={`/api/v1/imports/runs/${run.id}/errors.csv`}>
            Hibajegyzék CSV
          </a>
          {(canManage || canCancel) && (
            <div>
              {(run.state === "processing"
                ? ["pause", "cancel"]
                : run.state === "paused"
                  ? ["resume", "cancel"]
                  : run.state === "failed"
                    ? ["resume", "cancel"]
                    : run.state === "uploaded"
                      ? ["analyze", "cancel"]
                      : run.state === "awaiting_approval"
                        ? ["cancel"]
                        : ["partial", "completed"].includes(run.state)
                        ? ["retry-errors"]
                        : []
              )
                .filter((a) => (a === "cancel" ? canCancel : canManage))
                .map((a) => (
                  <button
                    key={a}
                    disabled={busy}
                    onClick={() =>
                      act(async () =>
                        U(
                          await api(
                            `/imports/runs/${run.id}/actions/${a}`,
                            "POST",
                          ),
                        ),
                      )
                    }
                  >
                    {
                      {
                        pause: "Szüneteltetés",
                        cancel: "Megszakítás",
                        resume: "Folytatás",
                        analyze: "Elemzés újraindítása",
                        "retry-errors": "Hibás sorok újrapróbálása",
                      }[a]
                    }
                  </button>
                ))}
              {canManage && run.deletable && (
                <button
                  className="danger"
                  disabled={busy}
                  onClick={() => askDelete(run.id)}
                >
                  Import törlése
                </button>
              )}
            </div>
          )}
          {run.state === "awaiting_approval" && (
            <>
              <nav aria-label="Import lépései" className="import-steps">
                <ol>
                  <li>Feltöltés ✓</li>
                  <li>
                    <a href="#import-mapping">Oszlopmegfeleltetés</a>
                  </li>
                  <li>
                    <a href="#import-preview">Adatelőnézet</a>
                  </li>
                  <li>
                    <a href="#import-approval">Jóváhagyás</a>
                  </li>
                </ol>
              </nav>
              {!!run.analysis.drift?.length && (
                <p role="alert">
                  A mentett profilhoz képest eltérés van:{" "}
                  {run.analysis.drift.join(", ")}. Új jóváhagyás szükséges.
                </p>
              )}
              <label>
                Célwebáruház-exportprofil
                <select
                  value={exportProfile}
                  onChange={(e) => XP(e.target.value)}
                >
                  <option value="">Nincs kiválasztva</option>
                  {exportProfiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              {canManage && (
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () =>
                      U(
                        await api(`/imports/runs/${run.id}/settings`, "PUT", {
                          ...(sheet && { sheet }),
                          header_line: header || 1,
                          ...(delimiter && { delimiter }),
                          ...(encoding && { encoding }),
                        }),
                      ),
                    )
                  }
                >
                  Fájlelemzés javítása a haladó beállításokkal
                </button>
              )}
              <label>
                Mentett profil használata
                <select
                  defaultValue=""
                  onChange={(e) => {
                    const p = profiles.find(
                      (p) => p.id === Number(e.target.value),
                    );
                    if (p) {
                      const h = run.analysis.headers || [];
                      M(
                        Object.fromEntries(
                          Object.entries(p.config.mapping).flatMap(([i, v]) => {
                            const index = h.indexOf(
                              p.config.analysis.headers[Number(i)],
                            );
                            return index >= 0 ? [[String(index), v]] : [];
                          }),
                        ),
                      );
                      P(p.name);
                      FD({
                        currency: p.config.currency || "",
                        price_type: p.config.price_type || "",
                        tax_basis: p.config.tax_basis || "",
                      });
                      K(p.config.identity_field || "");
                      G(p.config.feed_type || "partial");
                      A(p.config.automatic || false);
                    }
                  }}
                >
                  <option value="">Automatikus javaslat</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} v{p.version}
                    </option>
                  ))}
                </select>
              </label>
              <h3 id="import-mapping">Oszlopmegfeleltetés</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Eredeti oszlop</th>
                      <th>Belső mező</th>
                      <th>Célmező</th>
                      <th>Állapot / bizonyosság</th>
                      <th>Minta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {columns
                      .filter(
                        (c) =>
                          c.field ||
                          mapping[c.index] ||
                          c.suggested_field ||
                          c.warnings?.length,
                      )
                      .map((c) => (
                        <tr key={c.index}>
                          <td>{c.header}</td>
                          <td>
                            <select
                              aria-label={`Megfeleltetés: ${c.header}`}
                              value={mapping[c.index] || ""}
                              onChange={(e) =>
                                M({ ...mapping, [c.index]: e.target.value })
                              }
                            >
                              <option value="">Nem használjuk</option>
                              {fields.map((f) => (
                                <option key={f.key} value={f.key}>
                                  {f.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            {targetFields
                              .filter(
                                (f) => f.internal_field === mapping[c.index],
                              )
                              .map((f) => f.label)
                              .join(", ") || "Exportprofil szerint"}
                          </td>
                          <td>
                            {c.meaning ? (
                              <strong className="decision">
                                Megerősített jelentés: {meanings[c.meaning] || c.meaning}
                                . Pénzügyi jóváhagyás szükséges.
                              </strong>
                            ) : c.requires_decision && c.suggested_field ? (
                              <strong className="decision">
                                Döntés szükséges – lehetséges jelentés:{" "}
                                {fieldLabel(c.suggested_field)}. Automatikusan
                                nem választjuk ki; eladási árra nem
                                következtetünk.
                              </strong>
                            ) : (
                              <>
                                {c.critical ? "Jóváhagyás szükséges" : "Javaslat"}{" "}
                                · {Math.round(c.confidence * 100)}%
                              </>
                            )}
                            {c.warnings?.map((w) => (
                              <span key={w} className="warning-text" role="note">
                                {columnWarnings[w] || w}
                              </span>
                            ))}
                          </td>
                          <td>
                            <span className="cell-trunc" title={c.samples.join(" | ")}>
                              {c.samples.join(" | ")}
                            </span>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>További / fel nem ismert oszlopok</summary>
                {columns
                  .filter(
                    (c) =>
                      !c.field &&
                      !mapping[c.index] &&
                      !c.suggested_field &&
                      !c.warnings?.length,
                  )
                  .map((c) => (
                    <label key={c.index}>
                      {c.header}
                      <select
                        value=""
                        onChange={(e) =>
                          M({ ...mapping, [c.index]: e.target.value })
                        }
                      >
                        <option value="">Nem használjuk</option>
                        {fields.map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                      <small>{c.samples.join(" | ")}</small>
                    </label>
                  ))}
              </details>
              <h3 id="import-preview">Adatelőnézet</h3>
              <p>
                {run.analysis.data_rows?.toLocaleString("hu-HU")} nem üres
                forrássor; az üres sorokat (
                {run.analysis.empty_rows?.toLocaleString("hu-HU") ?? 0}) nem
                mutatjuk és nem importáljuk.
              </p>
              <div className="pager">
                <label>
                  Sorok oldalanként
                  <select
                    value={previewSize}
                    onChange={(e) => {
                      SO(0);
                      PZ(Number(e.target.value));
                    }}
                  >
                    {[5, 10, 25, 50].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  disabled={!sourceOffset}
                  onClick={() => SO(Math.max(0, sourceOffset - previewSize))}
                >
                  Előző forrássorok
                </button>
                <span>
                  {sourcePreview.items.length
                    ? `${sourceOffset + 1}–${sourceOffset + sourcePreview.items.length}`
                    : "–"}
                </span>
                <button
                  disabled={!sourcePreview.has_more}
                  onClick={() => SO(sourceOffset + previewSize)}
                >
                  Következő forrássorok
                </button>
              </div>
              <div className="table-wrap preview-table">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Sor</th>
                      {mappedFields.map(([i, f]) => (
                        <th scope="col" key={i}>
                          {fieldLabel(f)}
                          <small>{run.analysis.headers?.[Number(i)]}</small>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sourcePreview.items.map(({ line, interpreted }) => (
                      <tr key={line}>
                        <th scope="row">{line}</th>
                        {mappedFields.map(([i, f]) => {
                          const cell = interpreted?.[f];
                          return (
                            <td key={i}>
                              <span
                                className="cell-trunc"
                                title={cell?.raw || ""}
                              >
                                {cell?.value ?? (cell?.raw ? "–" : "")}
                              </span>
                              {cell?.issues.map((x) => (
                                <span key={x} className="warning-text">
                                  {issueText(x)}
                                </span>
                              ))}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Technikai részletek (nyers forrássorok)</summary>
                <div className="table-wrap">
                  <table className="raw-table">
                    <thead>
                      <tr>
                        <th scope="col">Sor</th>
                        {(run.analysis.headers || []).map((h, j) => (
                          <th scope="col" key={j}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sourcePreview.items.map(({ raw, line }) => (
                        <tr key={line}>
                          <th scope="row">{line}</th>
                          {raw.map((c, j) => (
                            <td key={j}>
                              <span className="cell-trunc" title={c}>
                                {c}
                              </span>
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <pre className="tech-json">
                  {JSON.stringify(
                    sourcePreview.items.map((r) => ({
                      line: r.line,
                      interpreted: r.interpreted,
                    })),
                    null,
                    2,
                  )}
                </pre>
              </details>
              <p>
                A célwebáruház-mezők az exportprofil szerint határozhatók meg;
                árból nem következtetünk eladási árra.
              </p>
              {canApprove && (
                <form
                  id="import-approval"
                  aria-label="Jóváhagyás"
                  onSubmit={(e) => {
                    e.preventDefault();
                    act(async () => {
                      U(
                        await api(`/imports/runs/${run.id}/approve`, "POST", {
                          name: profile,
                          mapping: Object.fromEntries(
                            Object.entries(mapping).filter(([, v]) => v),
                          ),
                          identity_field: key || null,
                          feed_type: feed,
                          financial_approved: financial,
                          ...Object.fromEntries(
                            Object.entries(financialDefaults).filter(
                              ([, v]) => v,
                            ),
                          ),
                          automatic,
                        }),
                      );
                      await refresh();
                    });
                  }}
                >
                  <label>
                    Profil neve
                    <input
                      value={profile}
                      onChange={(e) => P(e.target.value)}
                      required
                    />
                  </label>
                  {joins.length > 0 && (
                    <p>
                      Pontos mintaegyezések korábbi beszállítói tételekkel:{" "}
                      {joins
                        .map(
                          (j) =>
                            `${columns.find((c) => c.index === j.column)?.header} → ${j.field}: ${j.exact_sample_matches} egyezés`,
                        )
                        .join("; ")}
                      . A kulcs kiválasztása külön jóváhagyás.
                    </p>
                  )}
                  <details>
                    <summary>
                      Pénzügyi értelmezés (csak ismert adatot adj meg)
                    </summary>
                    {(
                      [
                        ["price_type", "Ártípus"],
                        ["tax_basis", "Nettó/bruttó jelleg"],
                        ["currency", "Pénznem"],
                      ] as const
                    ).map(([k, label]) => (
                      <label key={k}>
                        {label}
                        <input
                          value={financialDefaults[k]}
                          onChange={(e) =>
                            FD({ ...financialDefaults, [k]: e.target.value })
                          }
                        />
                      </label>
                    ))}
                  </details>
                  <label>
                    Jóváhagyott összekapcsolási kulcs
                    <select value={key} onChange={(e) => K(e.target.value)}>
                      <option value="">Nincs – soronként külön tétel</option>
                      {fields
                        .filter(
                          (f) =>
                            [
                              "sku",
                              "supplier_id",
                              "mpn",
                              "gtin",
                              "model",
                            ].includes(f.key) &&
                            Object.values(mapping).includes(f.key),
                        )
                        .map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <p>
                    Azonos beszállítón belül csak pontos kulcsegyezéssel
                    kapcsolunk össze fájlokat. A név vagy hasonló azonosító nem
                    elegendő.
                  </p>
                  <label>
                    Feed típusa
                    <select value={feed} onChange={(e) => G(e.target.value)}>
                      {[
                        ["partial", "Részleges"],
                        ["full", "Teljes terméktörzs"],
                        ["price", "Árlista"],
                        ["stock", "Készletlista"],
                        ["technical", "Műszaki adatok"],
                      ].map(([v, t]) => (
                        <option key={v} value={v}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={financial}
                      onChange={(e) => V(e.target.checked)}
                    />{" "}
                    A pénzügyi mezők jelentését ellenőriztem; a hiányzó
                    áfa/pénznem/árjelleg ismeretlen marad.
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={automatic}
                      onChange={(e) => A(e.target.checked)}
                    />{" "}
                    Következő feltöltésnél automatikus feldolgozás, ha nincs
                    eltérés
                  </label>
                  <button disabled={busy}>
                    Megfeleltetés jóváhagyása és feldolgozás
                  </button>
                </form>
              )}
            </>
          )}
          {!!rows.length && (
            <>
              <h3>Feldolgozott sorok</h3>
              <p>
                Az üres forrássorokat csak számoljuk (
                {(run.counters.empty || 0).toLocaleString("hu-HU")}), nem
                listázzuk.
              </p>
              <div className="table-wrap preview-table">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Sor</th>
                      <th scope="col">Állapot</th>
                      {approvedFields.map(([i, f]) => (
                        <th scope="col" key={i}>
                          {fieldLabel(f)}
                        </th>
                      ))}
                      <th scope="col">Problémák</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.line}>
                        <th scope="row">{r.line}</th>
                        <td>{r.state}</td>
                        {approvedFields.map(([i, f]) => (
                          <td key={i}>
                            <span
                              className="cell-trunc"
                              title={String(r.raw[Number(i)] ?? "")}
                            >
                              {r.normalized.fields?.[f] ?? ""}
                            </span>
                          </td>
                        ))}
                        <td>
                          {r.issues.map((x) => (
                            <span key={x} className="warning-text">
                              {issueText(x)}
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Technikai részletek (normalizált JSON)</summary>
                <pre className="tech-json">
                  {JSON.stringify(
                    rows.map((r) => ({
                      line: r.line,
                      raw: r.raw,
                      normalized: r.normalized,
                      issues: r.issues,
                    })),
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
          <button
            disabled={!offset}
            onClick={() => O(Math.max(0, offset - 25))}
          >
            Előző 25 sor
          </button>
          <button disabled={rows.length < 25} onClick={() => O(offset + 25)}>
            Következő 25 sor
          </button>
        </section>
      )}
    </>
  );
}

export function ExportAdmin({
  api,
  central,
  canProfile = true,
}: {
  api: Request;
  central: boolean;
  canProfile?: boolean;
}) {
  const [engines, S] = useState<
      { key: string; name: string; version: number; fields: Field[] }[]
    >([]),
    [key, K] = useState("unas"),
    [name, N] = useState("UNAS"),
    [fields, F] = useState<Field[]>([]),
    [error, E] = useState(""),
    [message, M] = useState("");
  const load = useCallback(async () => {
    S(await api("/imports/engines"));
  }, [api]);
  useEffect(() => {
    load().catch((e) => E(String(e)));
  }, [load]);
  const act = async (fn: () => Promise<void>) => {
    E("");
    M("");
    try {
      await fn();
      M("Mentve.");
    } catch (e) {
      E(String(e));
    }
  };
  return (
    <section className="card padded">
      <h2 className="field-title">
        Webáruházmotorok → Exportmezők
        <Help topic="export" />
      </h2>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <label>
        Motor
        <select
          value={key}
          onChange={(e) => {
            K(e.target.value);
            const x = engines.find((x) => x.key === e.target.value);
            if (x) {
              N(x.name);
              F(x.fields);
            }
          }}
        >
          <option value="unas">UNAS</option>
          {engines
            .filter((e) => e.key !== "unas")
            .map((e) => (
              <option key={e.key}>{e.key}</option>
            ))}
        </select>
      </label>
      <button
        onClick={() => {
          const e = engines.find((e) => e.key === key);
          if (e) {
            N(e.name);
            F(e.fields);
          }
        }}
      >
        Definíció betöltése
      </button>
      {central && (
        <>
          <label>
            Motorazonosító
            <input value={key} onChange={(e) => K(e.target.value)} />
          </label>
          <label>
            Motor neve
            <input value={name} onChange={(e) => N(e.target.value)} />
          </label>
          <label>
            Referencia CSV/XLSX fejléc beolvasása
            <input
              type="file"
              accept=".xlsx,.csv"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f)
                  act(async () => {
                    const data = new FormData();
                    data.append("file", f);
                    const r = await api<{ fields: Field[] }>(
                      `/imports/engines/${key}/reference`,
                      "POST",
                      data,
                    );
                    F(r.fields);
                  });
              }}
            />
          </label>
          <p>
            A mintában szereplő mezők opcionális javaslatok. Kötelezőséget
            kizárólag az adminisztrátor határoz meg.
          </p>
        </>
      )}
      <fieldset className="fieldless" disabled={!central && !canProfile}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Technikai azonosító</th>
                <th>Oszlopnév</th>
                <th>Típus</th>
                <th>Kötelező</th>
                <th>Belső mező</th>
                <th>Alapérték</th>
                <th>Értéklista</th>
                <th>Validáció</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f, i) => (
                <tr key={i}>
                  {(["key", "label"] as const).map((k) => (
                    <td key={k}>
                      <input
                        aria-label={`${k} ${i}`}
                        value={f[k]}
                        onChange={(e) =>
                          F(
                            fields.map((x, j) =>
                              j === i ? { ...x, [k]: e.target.value } : x,
                            ),
                          )
                        }
                      />
                    </td>
                  ))}
                  <td>
                    <select
                      value={f.type}
                      onChange={(e) =>
                        F(
                          fields.map((x, j) =>
                            j === i ? { ...x, type: e.target.value } : x,
                          ),
                        )
                      }
                    >
                      {["text", "number", "date", "boolean"].map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      aria-label={`Kötelező ${i}`}
                      type="checkbox"
                      checked={f.required}
                      onChange={(e) =>
                        F(
                          fields.map((x, j) =>
                            j === i ? { ...x, required: e.target.checked } : x,
                          ),
                        )
                      }
                    />
                  </td>
                  {(["internal_field", "default"] as const).map((k) => (
                    <td key={k}>
                      <input
                        aria-label={`${k} ${i}`}
                        value={f[k] || ""}
                        onChange={(e) =>
                          F(
                            fields.map((x, j) =>
                              j === i ? { ...x, [k]: e.target.value } : x,
                            ),
                          )
                        }
                      />
                    </td>
                  ))}
                  <td>
                    <input
                      aria-label={`Értéklista ${i}`}
                      value={(f.allowed || []).join(";")}
                      onChange={(e) =>
                        F(
                          fields.map((x, j) =>
                            j === i
                              ? {
                                  ...x,
                                  allowed: e.target.value
                                    .split(";")
                                    .filter(Boolean),
                                }
                              : x,
                          ),
                        )
                      }
                    />
                  </td>
                  <td>
                    <select
                      value={f.validation || ""}
                      onChange={(e) =>
                        F(
                          fields.map((x, j) =>
                            j === i ? { ...x, validation: e.target.value } : x,
                          ),
                        )
                      }
                    >
                      {["", "url", "email", "gtin", "nonnegative"].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button onClick={() => F(fields.filter((_, j) => j !== i))}>
                      Eltávolítás
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          onClick={() =>
            F([
              ...fields,
              {
                key: "field_" + fields.length,
                label: "Új mező",
                type: "text",
                required: false,
              },
            ])
          }
        >
          Mező hozzáadása
        </button>
        <button
          onClick={() =>
            act(async () => {
              if (central) {
                await api("/imports/engines/" + key, "PUT", { name, fields });
                await load();
              } else {
                await api("/imports/export-profiles", "POST", {
                  engine_key: key,
                  name,
                  fields,
                });
              }
            })
          }
        >
          {central
            ? "Központi definíció mentése"
            : "Saját exportprofil mentése"}
        </button>
      </fieldset>
      <p>Tényleges UNAS-export ebben a modulban nem készül.</p>
    </section>
  );
}
