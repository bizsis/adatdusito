import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  deleteImportItem,
  message,
  previewDeletion,
  type Deleted,
  type DeletionPlan,
  type DeletionTarget,
  type Request,
} from "./api";

const names = {
  supplier: "Beszállító",
  run: "Feltöltött fájl",
  template: "Mentett sablon",
  version: "Sablonverzió",
};

const refusals: Record<string, string> = {
  has_related_data: "A beszállítóhoz kapcsolódó adatok tartoznak.",
  approved_or_processed: "A jóváhagyott vagy feldolgozott import nem törölhető.",
  running: "A fájl elemzése folyamatban van. Várd meg az elemzés végét.",
  template_source: "A fájl egy mentett sablon forrása. Előbb a sablont kell törölni.",
  active_version: "A sablon aktív (legújabb) verziója külön nem törölhető.",
  only_version: "A sablon egyetlen verziója külön nem törölhető.",
};

const referenceLabels: Record<string, string> = {
  import_runs: "Kapcsolódó importok",
  templates: "Mentett sablonok",
  template_versions: "Sablonverziók",
  other_profiles: "Egyéb importprofilok",
  supplier_products: "Beszállítói termékek",
  source_categories: "Saját kategóriák",
  import_rows: "Importsorok",
  import_changes: "Importváltozások",
  products_last_written_by_run: "Az importtal frissített termékek",
  product_events: "Terméknapló-bejegyzések",
  template_sources: "A fájlt használó sablonverziók",
};

export function ImportDeleteButton({
  target,
  disabled,
  onOpen,
}: {
  target: DeletionTarget;
  disabled: boolean;
  onOpen: (target: DeletionTarget) => void;
}) {
  const label = `${names[target.kind]} törlése: ${target.name}`;
  return (
    <button
      type="button"
      className="icon-button danger prep-delete-button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onOpen(target)}
    >
      <Trash2 size={16} aria-hidden="true" />
    </button>
  );
}

function DeletionImpact({ target, plan }: { target: DeletionTarget; plan: DeletionPlan }) {
  const { deletes, detaches } = plan;
  if (target.kind === "supplier")
    return <p>Törléskor csak a beszállító adatai kerülnek törlésre.</p>;
  if (target.kind === "run")
    return (
      <>
        <p>Törléskor a feltöltés, az eredeti fájl, az elemzés és a beállítások törlődnek.</p>
        {!!deletes.source_file_bytes && (
          <p>Tárolt fájlméret: {deletes.source_file_bytes.toLocaleString("hu-HU")} bájt.</p>
        )}
        {!!deletes.generated_templates && (
          <p>A fájlból generált munkatáblák száma: {deletes.generated_templates}. Ezek is törlődnek.</p>
        )}
        <p>A beszállító, a mentett sablonok, a többi feltöltés és a termékadatok megmaradnak.</p>
      </>
    );
  return (
    <>
      <p>
        {target.kind === "template"
          ? `Törléskor a sablon összes verziója törlődik (${deletes.template_versions ?? 0}).`
          : "Törléskor csak ez a sablonverzió törlődik."}
      </p>
      {!!deletes.approved_parameters_in_deleted_versions && (
        <p>A törlendő verziókban tárolt paraméter-jóváhagyások száma: {deletes.approved_parameters_in_deleted_versions}.</p>
      )}
      {!!detaches?.matched_uploads && (
        <p>{detaches.matched_uploads} jóvá nem hagyott feltöltés sablonkapcsolata megszűnik. A feltöltések és a fájljaik megmaradnak.</p>
      )}
      <p>A beszállító, a termékek és a többi sablon megmaradnak.</p>
    </>
  );
}

export function ImportDeletionDialog({
  api,
  target,
  onCancel,
  onDeleted,
}: {
  api: Request;
  target: DeletionTarget;
  onCancel: () => void;
  onDeleted: (result: Deleted) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const submitting = useRef(false);
  const [plan, setPlan] = useState<DeletionPlan>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    cancel.current?.focus();
    return () => element?.close();
  }, []);

  useEffect(() => {
    let active = true;
    previewDeletion(api, target)
      .then((result) => { if (active) setPlan(result); })
      .catch((failure) => { if (active) setError(message(failure)); });
    return () => { active = false; };
  }, [api, target]);

  async function confirm() {
    if (plan?.deletable !== true || submitting.current || error) return;
    submitting.current = true;
    setBusy(true);
    try {
      onDeleted(await deleteImportItem(api, target));
    } catch (failure) {
      setError(message(failure));
      setBusy(false);
      submitting.current = false;
    }
  }

  const related = plan && Object.entries(plan.references).filter(
    ([key, count]) => referenceLabels[key] && typeof count === "number" && count > 0,
  );
  const refusal = plan?.reason === "referenced"
    ? target.kind === "run"
      ? "Az importra termékadat vagy változásnapló hivatkozik."
      : "A sablonra jóváhagyott vagy feldolgozott import hivatkozik."
    : refusals[plan?.reason ?? ""] ?? "A kiszolgáló letiltotta a törlést.";

  return (
    <dialog
      ref={dialog}
      className="prep-dialog"
      aria-labelledby="prep-delete-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting.current) onCancel();
      }}
    >
      <header><h2 id="prep-delete-title">{names[target.kind]} törlése</h2></header>
      <p><strong>{target.name}</strong></p>
      {!plan && !error && <p role="status">A törlés feltételeinek ellenőrzése…</p>}
      {plan && (
        <>
          {!plan.deletable && <p role="alert">{refusal}</p>}
          <DeletionImpact target={target} plan={plan} />
          {!!related?.length && (
            <ul>
              {related.map(([key, count]) => <li key={key}>{referenceLabels[key]}: {count}</li>)}
            </ul>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="prep-actions">
        <button type="button" ref={cancel} disabled={busy} onClick={onCancel}>Mégse</button>
        <button
          type="button"
          className="danger"
          disabled={plan?.deletable !== true || busy || !!error}
          onClick={() => void confirm()}
        >
          {busy ? "Törlés folyamatban…" : "Törlés"}
        </button>
      </div>
    </dialog>
  );
}
