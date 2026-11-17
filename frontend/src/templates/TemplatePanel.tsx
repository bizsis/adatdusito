import React, { useEffect, useState } from "react";

type Request = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Category = {
  id: string;
  path: string;
  donors: { emag_category_id: number; name: string; review_state: string }[];
};
type Binding = { node_id: string; donor?: number };
type Snapshot = {
  retry_allowed?: boolean;
  id: number;
  state: string;
  error: string | null;
  options: {
    mapping?: Record<string, number>;
    category?: Binding;
    rows?: Record<string, Binding>;
  };
  manifest: {
    columns?: {
      key: string;
      header: string;
      source_index?: number;
      kind: string;
      mandatory?: boolean;
    }[];
    mapping?: Record<string, number>;
    rows?: number;
    products?: number;
    warnings?: string[];
    preview?: { line: number; values: string[] }[];
  };
};
const fields = [
  "Cikkszám",
  "Termék Név",
  "Kategória",
  "Nettó Ár",
  "Bruttó Ár",
  "Státusz",
  "Rövid Leírás",
  "Tulajdonságok",
  "Kép link",
  "Raktárkészlet",
  "Vásárolható, ha nincs Raktáron",
  "Egység",
  "SEO Title",
  "SEO Description",
  "Kép ALT/TITLE",
  "SEF URL",
  "Akciós Nettó Ár",
  "Akciós Bruttó Ár",
  "Alternatív Kategória 1.",
];

export function TemplatePanel({
  api,
  runId,
  headers,
  canCreate,
  canClassify,
}: {
  api: Request;
  runId: number;
  headers: string[];
  canCreate: boolean;
  canClassify: boolean;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [category, setCategory] = useState("");
  const [donor, setDonor] = useState("");
  const [row, setRow] = useState("");
  const [rows, setRows] = useState<Record<string, Binding>>({});
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    let initialize = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await api<Snapshot | null>(
          `/imports/runs/${runId}/template`,
        );
        if (!active) return;
        setSnapshot(value);
        if (value && initialize) {
          initialize = false;
          setMapping(value.options.mapping || {});
          setRows(value.options.rows || {});
          setCategory(value.options.category?.node_id || "");
          setDonor(
            value.options.category?.donor
              ? String(value.options.category.donor)
              : "",
          );
        }
        if (!value || ["queued", "building"].includes(value.state))
          timer = setTimeout(load, 2500);
      } catch (e) {
        if (active)
          setError(
            e instanceof Error ? e.message : "A sablon nem tölthető be.",
          );
      }
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, runId, revision]);
  useEffect(() => {
    let active = true;
    if (canClassify)
      void api<Category[]>("/imports/template-categories")
        .then((v) => {
          if (active) setCategories(v);
        })
        .catch(() => {
          if (active) setError("A kategóriák nem tölthetők be.");
        });
    return () => {
      active = false;
    };
  }, [api, canClassify]);
  const selected = categories.find((c) => c.id === category);
  const approvedDonors =
    selected?.donors.filter((d) => d.review_state === "reviewed") || [];
  const chosen: Binding | null = selected
    ? { node_id: selected.id, ...(donor ? { donor: Number(donor) } : {}) }
    : null;
  const running =
    busy ||
    (!snapshot?.retry_allowed &&
      (snapshot?.state === "queued" || snapshot?.state === "building"));
  async function generate() {
    setBusy(true);
    setError("");
    try {
      const value = await api<Snapshot>(
        `/imports/runs/${runId}/templates`,
        "POST",
        { mapping, rows, ...(chosen && !row ? { category: chosen } : {}) },
      );
      setSnapshot(value);
      setRevision((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "A sablon nem készíthető el.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="template-panel" aria-label="Adatdúsítási munkasablon">
      <h3>Adatdúsítási munkasablon</h3>
      <p>
        Az eredeti oszlopok után a hiányzó UNAS-munkamezők és a hozzárendelt
        kategóriák paraméterei következnek. A készítés nem indít AI-kutatást,
        nem fogyaszt AI-kreditet. Ez munkatábla; a végleges UNAS-export külön
        lépés.
      </p>
      {error && <p role="alert">{error}</p>}
      {snapshot?.error && <p role="alert">{snapshot.error}</p>}
      {running && <p role="status">Sablon készítése…</p>}
      {!snapshot && (
        <p>
          A feltöltés elemzése után a sablon automatikusan elkészül. Ha még nem
          indult el, az alábbi gombbal is kérhető.
        </p>
      )}
      {snapshot?.state === "ready_for_enrichment" && (
        <>
          <p role="status">
            Adatdúsításra előkészítve (ready_for_enrichment) ·{" "}
            {snapshot.manifest.products} termék · {snapshot.manifest.rows}{" "}
            eredeti adatsor
          </p>
          {snapshot.manifest.warnings?.map((w) => (
            <p key={w}>{w}</p>
          ))}
          <div className="actions">
            {(["xlsx", "csv"] as const).map((format) => (
              <a
                className="button"
                key={format}
                href={`/api/v1/imports/runs/${runId}/templates/${snapshot.id}/${format}`}
                download
              >
                Sablon letöltése – {format.toUpperCase()}
              </a>
            ))}
            <button disabled aria-describedby={`enrichment-info-${runId}`}>
              Adatdúsítás indítása
            </button>
          </div>
          <p id={`enrichment-info-${runId}`}>
            Az AI-adatdúsítás indítása még nem érhető el. A meglévő
            paraméter-előkészítés és jóváhagyás külön munkafolyamatban
            változatlanul használható.
          </p>
          <details>
            <summary>Sablon előnézete és paraméteroszlopai</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Forrássor</th>
                    {snapshot.manifest.columns?.map((c) => (
                      <th key={c.key}>
                        {c.header || "(üres fejléc)"}
                        {c.kind === "parameter"
                          ? c.mandatory
                            ? " · kötelező"
                            : " · opcionális"
                          : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {snapshot.manifest.preview?.map((r) => (
                    <tr key={r.line}>
                      <td>{r.line}</td>
                      {r.values.map((v, i) => (
                        <td key={i}>{v}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      {canCreate && (
        <details>
          <summary>Oszlopok és kategóriák beállítása</summary>
          <p>
            Az eredeti oszlop neve és tartalma megmarad. A megfeleltetett
            UNAS-mezőhöz nem készül még egy oszlop. Csak biztos jelentésű mezőt
            válassz; a bizonytalan árak maradjanak üresen.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>UNAS-munkamező</th>
                  <th>Beszállítói forrásoszlop</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((field) => (
                  <tr key={field}>
                    <td>{field}</td>
                    <td>
                      <select
                        aria-label={`Sablon megfeleltetés: ${field}`}
                        value={mapping[field] ?? ""}
                        onChange={(e) =>
                          setMapping((prev) => {
                            const next = { ...prev };
                            if (e.target.value === "") delete next[field];
                            else next[field] = Number(e.target.value);
                            return next;
                          })
                        }
                      >
                        <option value="">
                          Automatikus felismerés / hiány esetén új oszlop
                        </option>
                        {headers.map((h, i) => (
                          <option key={i} value={i}>
                            {i + 1}. {h || "(üres fejléc)"}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {canClassify && (
            <>
              <p>
                A kategóriaválasztás csak ehhez a sablonhoz tartozik; a termékek
                jóváhagyott besorolását nem írja felül. Meglévő besorolás esetén
                a sorhoz tartozó kategória elsőbbséget élvez.
              </p>
              <label>
                Sablon kategóriája
                <select
                  aria-label="Sablon kategóriája"
                  value={category}
                  onChange={(e) => {
                    setCategory(e.target.value);
                    setDonor("");
                  }}
                >
                  <option value="">A termékek meglévő besorolása</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.path}
                    </option>
                  ))}
                </select>
              </label>
              {!!selected?.donors.length && (
                <label>
                  Sablon paraméterprofilja
                  <select
                    aria-label="Sablon paraméterprofilja"
                    value={donor}
                    onChange={(e) => setDonor(e.target.value)}
                  >
                    <option value="">
                      {selected.donors.length === 1
                        ? "Egyetlen jóváhagyott profil automatikusan"
                        : "Válassz profilt"}
                    </option>
                    {approvedDonors.map((d) => (
                      <option
                        key={d.emag_category_id}
                        value={d.emag_category_id}
                      >
                        {d.name} ({d.emag_category_id})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                Eltérő kategória eredeti sorszáma (fejléc nélkül, a fájl
                sorszáma)
                <input
                  type="number"
                  min={2}
                  value={row}
                  onChange={(e) => setRow(e.target.value)}
                />
              </label>
              <button
                disabled={!chosen || !row}
                onClick={() => {
                  if (chosen) setRows((prev) => ({ ...prev, [row]: chosen }));
                }}
              >
                Kategória rögzítése ehhez a sorhoz
              </button>
              {Object.entries(rows).map(([line, b]) => (
                <p key={line}>
                  {line}. forrássor:{" "}
                  {categories.find((c) => c.id === b.node_id)?.path}
                  <button
                    onClick={() =>
                      setRows((prev) => {
                        const n = { ...prev };
                        delete n[line];
                        return n;
                      })
                    }
                  >
                    Sorbeállítás törlése
                  </button>
                </p>
              ))}
            </>
          )}
        </details>
      )}
      {canCreate && (
        <button disabled={running} onClick={() => void generate()}>
          Sablon {snapshot ? "újragenerálása" : "elkészítése"}
        </button>
      )}
      <p>
        A CSV minden cellája szöveg, de az Excel automatikus számfelismerése
        módosíthatja az azonosítókat. Vezető nullákhoz az XLSX-et használd, vagy
        szövegként importáld a CSV-t.
      </p>
    </section>
  );
}
