import React from "react";
import { LockKeyhole } from "lucide-react";
import { classificationLabels, type ProductCard } from "./presentation";

export function ClassificationSummary({ product }: { product: ProductCard }) {
  const confidence = product.confidencePercent;
  return (
    <div className="classification-summary">
      <span className={"badge " + (product.group === "assigned" ? "good" : "")}>
        {classificationLabels[product.group]}
      </span>
      <dl className="data-list">
        <div>
          <dt>Eredeti kategória</dt>
          <dd>{product.originalCategory || "Nincs megadva"}</dd>
        </div>
        <div>
          <dt>Saját kategória</dt>
          <dd>{product.ownCategory || "Nincs saját kategória"}</dd>
        </div>
        <div>
          <dt>Belső besorolás</dt>
          <dd>
            {product.internalCategory?.path.join(" / ") ||
              "Még nincs egyértelmű besorolás"}
          </dd>
        </div>
        <div>
          <dt>Módosítás eredete</dt>
          <dd>{product.origin}</dd>
        </div>
      </dl>
      {product.explanation && <p>{product.explanation}</p>}
      {confidence !== null &&
        Number.isFinite(confidence) &&
        confidence >= 0 &&
        confidence <= 100 && (
          <p>
            Megbízhatósági érték:{" "}
            {confidence.toLocaleString("hu-HU", { maximumFractionDigits: 2 })}%
          </p>
        )}
      {product.protectedEdit && (
        <p className="notice">
          <LockKeyhole size={16} aria-hidden /> Kézi javítás védett
        </p>
      )}
      {product.auditText && <p className="small muted">{product.auditText}</p>}
      <details>
        <summary>Belső paraméterforrás</summary>
        <p>{product.donorText || "Nincs ellenőrzött paraméterdonor."}</p>
      </details>
    </div>
  );
}

export type ImportClassificationSummaryProps = {
  runCount: number;
  assignedCount: number;
  reviewCount: number;
  onOpenProducts?: () => void;
};
export function ImportClassificationSummary(
  props: ImportClassificationSummaryProps,
) {
  return (
    <section className="card padded" aria-label="Import besorolási áttekintése">
      <h2>Besorolás áttekintése</h2>
      <p>
        Az aktuális futás termékei: {props.runCount.toLocaleString("hu-HU")}
      </p>
      <div className="facts">
        <span>
          Automatikusan besorolt: {props.assignedCount.toLocaleString("hu-HU")}
        </span>
        <span>
          Ellenőrzést igényel: {props.reviewCount.toLocaleString("hu-HU")}
        </span>
      </div>
      <p className="small muted">
        Legfeljebb 50 000 termék egy feldolgozási futásban. Ez nem az ügyfél
        teljes termékállományának korlátja.
      </p>
      {props.onOpenProducts && (
        <button onClick={props.onOpenProducts}>Termékadatok megnyitása</button>
      )}
    </section>
  );
}
