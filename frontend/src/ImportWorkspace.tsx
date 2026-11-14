import React, { useState, useEffect } from "react";
type Request = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Column = {
  index: number;
  header: string;
  field: string | null;
  confidence: number;
  method: string;
  critical: boolean;
  samples: string[];
};
type Run = {
  id: number;
  supplier_id: number;
  filename: string;
  state: string;
  cursor: number;
  error: string | null;
  counters: Record<string, number>;
  analysis: {
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
}: {
  api: Request;
  canManage: boolean;
}) {
  const [exportProfiles, EP] = useState<
    { id: number; name: string; fields: Field[] }[]
  >([]);
  const [exportProfile, XP] = useState("");
  const [historyOffset, HO] = useState(0);
  const [sourceOffset, SO] = useState(0);
  const [sourcePreview, SP] = useState<{
    items: { line: number; raw: string[]; interpreted?: unknown }[];
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
        normalized: unknown;
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
          analysis: { headers: string[] };
        };
      }[]
    >([]),
    [busy, B] = useState(false),
    [sheet, SH] = useState(""),
    [header, H] = useState(0),
    [delimiter, D] = useState(""),
    [encoding, EN] = useState("");
  const act = async (fn: () => Promise<void>) => {
    E("");
    B(true);
    try {
      await fn();
    } catch (e) {
      E(String(e));
    } finally {
      B(false);
    }
  };
  async function refresh() {
    S(await api("/imports/suppliers"));
    R(await api("/imports/runs"));
    EP(await api("/imports/export-profiles"));
  }
  function select(r: Run) {
    U(r);
    T(String(r.supplier_id));
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
  }
  useEffect(() => {
    act(async () => {
      await refresh();
      F(await api("/imports/fields"));
    });
  }, []);
  useEffect(() => {
    if (supplier)
      api<typeof profiles>("/imports/profiles?supplier_id=" + supplier)
        .then(PS)
        .catch((e) => E(String(e)));
  }, [supplier, run?.id]);
  useEffect(() => {
    if (!run) return;
    const id = setInterval(() => {
      api<Run>("/imports/runs/" + run.id)
        .then((r) => {
          if (r.state !== run.state && r.state === "awaiting_approval")
            select(r);
          else U(r);
          if (r.state !== run.state) refresh().catch((e) => E(String(e)));
        })
        .catch((e) => E(String(e)));
    }, 2000);
    return () => clearInterval(id);
  }, [run?.id, run?.state]);
  useEffect(() => {
    if (run)
      api<{ items: typeof rows }>(
        `/imports/runs/${run.id}/rows?offset=${offset}`,
      )
        .then((r) => Q(r.items))
        .catch((e) => E(String(e)));
  }, [run?.id, run?.state, offset]);
  useEffect(() => {
    if (run?.analysis.columns)
      api<typeof joins>(`/imports/runs/${run.id}/join-suggestions`)
        .then(J)
        .catch((e) => E(String(e)));
  }, [run?.id, run?.state]);
  const columns = run?.analysis.columns || [];
  useEffect(() => {
    if (run?.state === "awaiting_approval")
      api<typeof sourcePreview>(`/imports/runs/${run.id}/preview`, "POST", {
        mapping,
        offset: sourceOffset,
      })
        .then(SP)
        .catch((e) => E(String(e)));
  }, [run?.id, run?.state, sourceOffset, mapping]);
  const targetFields =
    exportProfiles.find((p) => p.id === Number(exportProfile))?.fields || [];
  return (
    <>
      <section className="card padded">
        <h2>Beszállítói import</h2>
        <p>
          Feltöltés → felismerés → megfeleltetés → jóváhagyás. AI-kredit nélkül
          is használható.
        </p>
        {error && <p role="alert">{error}</p>}
        <label>
          Beszállító
          <select value={supplier} onChange={(e) => T(e.target.value)}>
            <option value="">Válassz beszállítót</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {canManage && (
          <>
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
              CSV/XLSX fájl
              <input
                type="file"
                accept=".csv,.xlsx"
                disabled={!supplier || busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  act(async () => {
                    const form = new FormData();
                    form.append("file", file);
                    form.append("supplier_id", supplier);
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
      <section className="card padded">
        <h2>Importelőzmények</h2>
        <button
          disabled={!historyOffset}
          onClick={() =>
            act(async () => {
              const next = Math.max(0, historyOffset - 25);
              HO(next);
              R(await api(`/imports/runs?offset=${next}`));
            })
          }
        >
          Korábbi oldal
        </button>
        <button
          disabled={runs.length < 25}
          onClick={() =>
            act(async () => {
              const next = historyOffset + 25;
              HO(next);
              R(await api(`/imports/runs?offset=${next}`));
            })
          }
        >
          További importok
        </button>
        {runs.map((r) => (
          <button key={r.id} onClick={() => select(r)}>
            #{r.id} {r.filename} · {labels[r.state] || r.state}
          </button>
        ))}
      </section>
      {run && (
        <section className="card padded">
          <h2>
            #{run.id} – {labels[run.state] || run.state}
          </h2>
          <p>
            Feldolgozott forrássor: {run.cursor} ·{" "}
            {Object.entries(run.counters)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </p>
          {run.error && <p role="alert">{run.error}</p>}
          <a href={`/api/v1/imports/runs/${run.id}/file`}>
            Eredeti fájl letöltése
          </a>{" "}
          ·{" "}
          <a href={`/api/v1/imports/runs/${run.id}/errors.csv`}>
            Hibajegyzék CSV
          </a>
          {canManage && (
            <div>
              {(run.state === "processing"
                ? ["pause", "cancel"]
                : run.state === "paused"
                  ? ["resume", "cancel"]
                  : run.state === "failed"
                    ? ["resume", "cancel"]
                    : run.state === "uploaded"
                      ? ["analyze", "cancel"]
                      : ["partial", "completed"].includes(run.state)
                        ? ["retry-errors"]
                        : []
              ).map((a) => (
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
            </div>
          )}
          {run.state === "awaiting_approval" && (
            <>
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
                      .filter((c) => c.field || mapping[c.index])
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
                            {c.critical ? "Jóváhagyás szükséges" : "Javaslat"} ·{" "}
                            {Math.round(c.confidence * 100)}%
                          </td>
                          <td>{c.samples.join(" | ")}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>További / fel nem ismert oszlopok</summary>
                {columns
                  .filter((c) => !c.field && !mapping[c.index])
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
              <h3>Eredeti adatelőnézet</h3>
              <p>
                Forrássorok: {sourceOffset + 1}–
                {sourceOffset + sourcePreview.items.length}
              </p>
              <button
                disabled={!sourceOffset}
                onClick={() => SO(Math.max(0, sourceOffset - 25))}
              >
                Előző forrássorok
              </button>
              <button
                disabled={!sourcePreview.has_more}
                onClick={() => SO(sourceOffset + 25)}
              >
                Következő forrássorok
              </button>
              <div className="table-wrap">
                <table>
                  <tbody>
                    {sourcePreview.items.map(
                      ({ raw: r, line: i, interpreted }) => (
                        <tr key={i}>
                          <td>
                            <pre>{JSON.stringify(interpreted, null, 2)}</pre>
                          </td>
                          {r.map((c, j) => (
                            <td key={j}>{c}</td>
                          ))}
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
              <p>
                A célwebáruház-mezők az exportprofil szerint határozhatók meg;
                árból nem következtetünk eladási árra.
              </p>
              {canManage && (
                <form
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
              <h3>Eredeti és értelmezett sorok</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Sor / állapot</th>
                      <th>Eredeti</th>
                      <th>Értelmezett / hibák</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.line}>
                        <td>
                          {r.line} · {r.state}
                        </td>
                        <td>{JSON.stringify(r.raw)}</td>
                        <td>
                          <pre>{JSON.stringify(r.normalized, null, 2)}</pre>
                          {r.issues.join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
}: {
  api: Request;
  central: boolean;
}) {
  const [engines, S] = useState<
      { key: string; name: string; version: number; fields: Field[] }[]
    >([]),
    [key, K] = useState("unas"),
    [name, N] = useState("UNAS"),
    [fields, F] = useState<Field[]>([]),
    [error, E] = useState(""),
    [message, M] = useState("");
  async function load() {
    S(await api("/imports/engines"));
  }
  useEffect(() => {
    load().catch((e) => E(String(e)));
  }, []);
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
      <h2>Webáruházmotorok → Exportmezők</h2>
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
        {central ? "Központi definíció mentése" : "Saját exportprofil mentése"}
      </button>
      <p>Tényleges UNAS-export ebben a modulban nem készül.</p>
    </section>
  );
}
