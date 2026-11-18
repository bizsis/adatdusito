import { useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  loadResult,
  message,
  resultDownload,
  type Request,
  type ResultIssue,
  type TemplateResultPage,
  type TemplateVersion,
} from "./api";

const explanations: Record<string, string> = {
  missing_sku: "Hiányzik a cikkszám, ezért ez a sor kimarad a letöltésből.",
  missing_required: "Hiányzik a kötelező érték.",
  missing_price: "Nincs megadva eladási ár.",
  invalid_date: "A forrásérték nem felismerhető dátum.",
  invalid_number: "A forrásérték nem szám.",
  invalid_vat: "Az ÁFA értéke csak 0, 5, 18 vagy 27 százalék lehet.",
  invalid_status:
    "A státusz értéke nem értelmezhető aktív vagy inaktív állapotként.",
  invalid_image: "A képhez érvényes HTTP vagy HTTPS hivatkozás szükséges.",
  invalid_image_url: "A képhez érvényes HTTP vagy HTTPS hivatkozás szükséges.",
  ean_unrecoverable:
    "A vonalkódból elveszett számjegyek nem állíthatók helyre.",
  ean_reconstructed:
    "A vonalkódot a pontos forrásértékből állította helyre a rendszer.",
  invalid_gtin: "A vonalkód hossza vagy ellenőrzőszáma érvénytelen.",
  negative_stock: "A forráskészlet negatív.",
  image_missing_in_sequence: "Az üres képhelyek kimaradnak a képek listájából.",
  images_over_unas_limit: "Tíznél több kép van a sorban. Az export mindegyiket tartalmazza.",
  additional_images_not_exported:
    "Az UNAS-fájl csak az első képet tartalmazza.",
  duplicate_sku: "A cikkszám többször szerepel a forrásban.",
  price_vat_mismatch:
    "A nettó és bruttó ár eltér a megadott ÁFA alapján számított értéktől.",
  currency_mismatch:
    "A forrás pénzneme eltér a sablonétól. Az eredmény az eredeti értéket tartalmazza.",
};

const defaultFields: Record<string, string> = {
  missing_sku: "cikkszam",
  duplicate_sku: "cikkszam",
  negative_stock: "raktarkeszlet",
  invalid_status: "statusz",
  invalid_image: "kep",
  invalid_image_url: "kep",
  image_missing_in_sequence: "kep",
  images_over_unas_limit: "kep",
};

const identifierIssues = new Set([
  "ean_unrecoverable",
  "ean_reconstructed",
  "invalid_gtin",
]);
const warningOnly = new Set([
  "ean_reconstructed",
  "negative_stock",
  "duplicate_sku",
  "price_vat_mismatch",
  "currency_mismatch",
  "additional_images_not_exported",
  "image_missing_in_sequence",
  "images_over_unas_limit",
]);

function issueText(issue: ResultIssue) {
  return explanations[issue.code] ?? "Ellenőrizd a forrásban megadott értéket.";
}

function invalidImageUrl(value: string) {
  try {
    const url = new URL(value);
    return (
      !["http:", "https:"].includes(url.protocol) ||
      !url.hostname ||
      !/^https?:\/\//i.test(value)
    );
  } catch {
    return true;
  }
}

function IssueDetails({
  children,
  label,
  warning = false,
}: {
  children: ReactNode;
  label: string;
  warning?: boolean;
}) {
  const tooltipId = useId();
  const [position, setPosition] = useState<{
    top: number;
    left: number;
    below: boolean;
  }>();
  const show = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 16);
    setPosition({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      top: rect.top < 150 ? rect.bottom : rect.top,
      below: rect.top < 150,
    });
  };
  return (
    <>
      <button
        type="button"
        className={`prep-result-issue${warning ? " prep-warning" : ""}`}
        aria-label={label}
        aria-describedby={position ? tooltipId : undefined}
        onMouseEnter={(event) => show(event.currentTarget)}
        onMouseLeave={() => setPosition(undefined)}
        onFocus={(event) => show(event.currentTarget)}
        onBlur={() => setPosition(undefined)}
        onClick={(event) => show(event.currentTarget)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setPosition(undefined);
        }}
      >
        {warning ? "Figyelmeztetés" : "Hiba"}
      </button>
      {position &&
        createPortal(
          <div
            id={tooltipId}
            role="tooltip"
            className={`prep-result-tooltip${position.below ? " below" : ""}`}
            style={{ top: position.top, left: position.left }}
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  );
}

export function TemplateResult({
  api,
  template,
  run,
  onBack,
}: {
  api: Request;
  template: TemplateVersion;
  run: number;
  onBack: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const key = `${offset}:${revision}`;
  const [loaded, setLoaded] = useState<{
    key: string;
    data?: TemplateResultPage;
    error?: string;
  }>();
  const current = loaded?.key === key ? loaded : undefined;
  const result = current?.data;
  useEffect(() => {
    let active = true;
    loadResult(api, template.id, run, offset).then(
      (data) => {
        if (active) setLoaded({ key, data });
      },
      (error) => {
        if (active) setLoaded({ key, error: message(error) });
      },
    );
    return () => {
      active = false;
    };
  }, [api, template.id, run, offset, key]);

  const identifiers = result?.columns.filter(
    ({ target }) => target.key === "ean" || target.key === "gyartoi_cikkszam",
  );
  const singleIdentifier =
    identifiers?.length === 1 ? identifiers[0].target.key : undefined;

  return (
    <section className="card padded prep-result" aria-label="UNAS eredmény">
      <h3>UNAS eredmény</h3>
      <p role="status">
        Sablon mentve: {template.name} · v{template.version}
      </p>
      <div className="prep-actions">
        <button type="button" onClick={onBack}>
          Vissza a megfeleltetéshez
        </button>
        <button
          type="button"
          onClick={() => {
            setOffset(0);
            setRevision((value) => value + 1);
          }}
        >
          Újragenerálás
        </button>
        <button type="button" disabled>
          Dúsítás indítása (későbbi fejlesztés)
        </button>
      </div>
      {!current && <p role="status">UNAS előnézet betöltése…</p>}
      {current?.error && <p role="alert">{current.error}</p>}
      {result && (
        <>
          <p>
            {result.template.currency} · {result.summary.rows} sor ·{" "}
            {result.summary.exportable} letölthető · {result.summary.excluded}{" "}
            kizárt
          </p>
          {result.excluded_columns.length > 0 && (
            <p className="prep-warning">
              Kimaradó UNAS-oszlopok:{" "}
              {result.excluded_columns.map(({ header }) => header).join(", ")}
            </p>
          )}
          {result.missing_source_columns.length > 0 && (
            <p className="prep-warning">
              Hiányzó forrásoszlopok: {result.missing_source_columns.join(", ")}
            </p>
          )}
          <div className="prep-actions prep-result-downloads">
            <a href={resultDownload(template.id, run, "csv")}>
              UNAS CSV letöltése
            </a>
            <a href={resultDownload(template.id, run, "xlsx")}>
              UNAS XLSX letöltése
            </a>
          </div>
          <div
            className="prep-result-table"
            tabIndex={0}
            role="region"
            aria-label="UNAS előnézet görgetése"
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Forrássor</th>
                  {result.columns.map((column, index) => (
                    <th scope="col" key={index}>
                      {column.header}
                    </th>
                  ))}
                  <th scope="col">Ellenőrzés</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => {
                  const issues = [...row.errors, ...row.warnings];
                  if (
                    result.columns.some(
                      (column, index) =>
                        column.target.key === "kep" &&
                        Boolean(row.values[index]) &&
                        row.values[index].split("|").some(invalidImageUrl),
                    ) &&
                    !issues.some((issue) =>
                      ["invalid_image", "invalid_image_url"].includes(
                        issue.code,
                      ),
                    )
                  )
                    issues.push({ code: "invalid_image_url", target: "kep" });
                  return (
                    <tr key={row.line}>
                      <th scope="row">{row.line}</th>
                      {result.columns.map((column, index) => {
                        const cellIssues = issues.filter((issue) => {
                          const field =
                            issue.target ??
                            (identifierIssues.has(issue.code)
                              ? singleIdentifier
                              : defaultFields[issue.code]);
                          return field === column.target.key;
                        });
                        const warning = cellIssues.every((issue) =>
                          warningOnly.has(issue.code),
                        );
                        return (
                          <td key={index}>
                            {row.values[index]}
                            {cellIssues.length > 0 && (
                              <IssueDetails
                                warning={warning}
                                label={`${warning ? "Figyelmeztetés" : "Hiba"}: ${column.header}, ${row.line}. sor`}
                              >
                                {cellIssues.map(issueText).join(" ")}
                              </IssueDetails>
                            )}
                          </td>
                        );
                      })}
                      <td>
                        {issues.length > 0 ? (
                          <IssueDetails
                            label={`${row.line}. sor hibái és figyelmeztetései`}
                          >
                            {row.status === "error" && (
                              <p>Ez a sor kimarad a letöltésből.</p>
                            )}
                            {issues.map((issue, index) => (
                              <p key={index}>{issueText(issue)}</p>
                            ))}
                          </IssueDetails>
                        ) : (
                          "Rendben"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!result.rows.length && <p>Nincs megjeleníthető sor.</p>}
          {result.total > result.limit && (
            <nav className="prep-actions" aria-label="UNAS eredmény lapozása">
              <button
                type="button"
                disabled={result.offset === 0}
                onClick={() =>
                  setOffset(Math.max(0, result.offset - result.limit))
                }
              >
                Előző oldal
              </button>
              <span>
                {result.offset + 1}–{result.offset + result.rows.length} /{" "}
                {result.total}
              </span>
              <button
                type="button"
                disabled={result.offset + result.limit >= result.total}
                onClick={() => setOffset(result.offset + result.limit)}
              >
                Következő oldal
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
