import React, { lazy, Suspense, useEffect, useState } from "react";
import { Panel } from "./ui";
import type { ClassificationPresentation } from "./classification/presentation";
const ClassificationWorkspace = lazy(() =>
  import("./classification/ClassificationWorkspace").then((module) => ({
    default: module.ClassificationWorkspace,
  })),
);
type Api = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Product = {
  id: number;
  fields: Record<string, unknown>;
  supplier_name: string;
  source_line: number;
};
export function ProductData({
  api,
  classification,
}: {
  api: Api;
  classification?: ClassificationPresentation;
}) {
  // Production keeps the current API until CATEGORY-02A has a verified adapter.
  if (classification)
    return (
      <Suspense fallback={<p role="status">Termékbesorolás betöltése…</p>}>
        <ClassificationWorkspace {...classification} />
      </Suspense>
    );
  return <ImportedProductData api={api} />;
}
function ImportedProductData({ api }: { api: Api }) {
  const [cursor, C] = useState(0),
    [history, H] = useState<number[]>([]),
    [data, D] = useState<{
      items: Product[];
      next_cursor: number | null;
      field_labels: Record<string, string>;
    } | null>(null),
    [item, I] = useState<Product | null>(null),
    [error, E] = useState("");
  useEffect(() => {
    let cancelled = false;
    D(null);
    I(null);
    api<NonNullable<typeof data>>("/workspace/products?cursor=" + cursor)
      .then((r) => {
        if (!cancelled) D(r);
      })
      .catch((e) => {
        if (!cancelled) E(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [api, cursor]);
  return (
    <>
      <Panel title="Beszállítói termékadatok">
        <p className="muted">
          Az aktív ügyfél feldolgozott termékei. A forrásadatok és az
          importfolyamat változatlanok.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Terméknév</th>
                <th>Cikkszám</th>
                <th>Gyártó</th>
                <th>Beszállító</th>
                <th>Művelet</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((p) => (
                <tr key={p.id}>
                  <td>{String(p.fields.name || "Név nélküli termék")}</td>
                  <td>{String(p.fields.sku || p.fields.supplier_id || "–")}</td>
                  <td>{String(p.fields.brand || "–")}</td>
                  <td>{p.supplier_name}</td>
                  <td>
                    <button onClick={() => I(p)}>Adatok megtekintése</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data?.items.length === 0 && (
          <p className="empty">
            Még nincs feldolgozott termék ebben a munkaterületben.
          </p>
        )}
        {!data && !error && <p role="status">Betöltés…</p>}
        <div className="pager">
          <button
            disabled={!history.length}
            onClick={() => {
              C(history[history.length - 1]);
              H(history.slice(0, -1));
            }}
          >
            Előző termékek
          </button>
          <button
            disabled={!data?.next_cursor}
            onClick={() => {
              H([...history, cursor]);
              C(data?.next_cursor || 0);
            }}
          >
            Következő termékek
          </button>
        </div>
      </Panel>
      {item && (
        <Panel title={String(item.fields.name || "Termékadatok")}>
          <p>
            Beszállító: {item.supplier_name}, eredeti fájl sora:{" "}
            {item.source_line}.
          </p>
          <dl className="data-list">
            {Object.entries(item.fields).map(([k, v]) => (
              <div key={k}>
                <dt>{data?.field_labels[k] || k}</dt>
                <dd>
                  {typeof v === "object" ? JSON.stringify(v) : String(v ?? "–")}
                </dd>
              </div>
            ))}
          </dl>
          <button onClick={() => I(null)}>Részletek bezárása</button>
        </Panel>
      )}
    </>
  );
}
