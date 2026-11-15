import React, { useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import { CategoryPicker } from "./CategoryPicker";
import {
  ClassificationConflict,
  type ChangePreview,
  type Choice,
  type EditIntent,
  type PresentationPorts,
} from "./presentation";

export type EditorTarget = EditIntent["target"];
export function ClassificationEditor({
  ports,
  target,
  ownCategory,
  onClose,
  onRefresh,
  onApplied,
  initialChoice,
}: {
  ports: PresentationPorts;
  target: EditorTarget;
  ownCategory: string;
  onClose: () => void;
  onRefresh: () => void;
  onApplied: () => void;
  initialChoice?: Choice;
}) {
  const [choice, setChoice] = useState<Choice | null>(
    initialChoice?.selectable ? initialChoice : null,
  );
  const [reason, setReason] = useState("");
  const [inherit, setInherit] = useState(false);
  const [preview, setPreview] = useState<ChangePreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function invalidate() {
    request.current?.abort();
    setPreview(null);
    setBusy(false);
    setError("");
  }
  async function inspect() {
    if (!choice || !reason.trim() || !ports.preview) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await ports.preview(
        {
          target: target.kind === "mapping" ? { ...target, inherit } : target,
          category: choice,
          reason: reason.trim(),
        },
        controller.signal,
      );
      if (!controller.signal.aborted) setPreview(result);
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : "Az előnézet nem érhető el.");
        setConflict(e instanceof ClassificationConflict);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  async function apply() {
    if (
      !preview ||
      !preview.canApply ||
      preview.conflicts > 0 ||
      !ports.apply ||
      busy ||
      conflict
    )
      return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      await ports.apply(preview, controller.signal);
      if (!controller.signal.aborted) onApplied();
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : "A módosítás nem menthető.");
        setPreview(null);
        setConflict(e instanceof ClassificationConflict);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <Panel
      title={
        target.kind === "mapping"
          ? "Saját kategóriatérkép jóváhagyása"
          : "Belső besorolás módosítása"
      }
    >
      <p>
        Saját kategória:{" "}
        <strong>{ownCategory || "Nincs saját kategória"}</strong>
      </p>
      <p className="notice">
        A belső besorolás és paraméterdonor kiválasztása nem módosítja az
        eredeti saját kategóriát vagy értékeket. A mentett kézi döntés védelmét
        a szerver biztosítja.
      </p>
      <fieldset
        className="classification-picker-lock"
        disabled={busy || conflict}
      >
        {ports.choices && (
          <CategoryPicker
            read={ports.choices}
            selected={choice}
            onSelect={(value) => {
              invalidate();
              setChoice(value);
            }}
          />
        )}
      </fieldset>
      <label>
        Módosítás indoka
        <textarea
          value={reason}
          disabled={busy}
          onChange={(e) => {
            invalidate();
            setReason(e.target.value);
          }}
        />
      </label>
      {target.kind === "mapping" && (
        <label>
          <input
            type="checkbox"
            checked={inherit}
            disabled={busy}
            onChange={(e) => {
              invalidate();
              setInherit(e.target.checked);
            }}
          />
          Alkalmazás a saját kategória termékeire
        </label>
      )}
      {error && <p role="alert">{error}</p>}
      {conflict && (
        <div className="notice">
          <p>
            Az adatok időközben megváltoztak. A régi előnézettel nem lehet
            menteni.
          </p>
          <button onClick={onRefresh}>Friss adatok betöltése</button>
        </div>
      )}
      <div className="actions">
        <button
          disabled={
            !choice || !reason.trim() || busy || conflict || !ports.preview
          }
          onClick={inspect}
        >
          Módosítások előnézete
        </button>
        <button disabled={busy} onClick={onClose}>
          Mégse
        </button>
      </div>
      {busy && <p role="status">Művelet folyamatban…</p>}
      {preview && (
        <section aria-label="Módosítás előnézete">
          <h3>Előnézet</h3>
          <p>{preview.summary}</p>
          <dl className="data-list">
            <div>
              <dt>Érintett termékek</dt>
              <dd>{preview.affected.toLocaleString("hu-HU")}</dd>
            </div>
            <div>
              <dt>Védett, kihagyandó</dt>
              <dd>{preview.locked.toLocaleString("hu-HU")}</dd>
            </div>
            <div>
              <dt>Ütközések</dt>
              <dd>{preview.conflicts.toLocaleString("hu-HU")}</dd>
            </div>
          </dl>
          <ul>
            {preview.changes.map((change, index) => (
              <li key={index}>
                {change.label}: {change.before || "–"} → {change.after || "–"}
              </li>
            ))}
          </ul>
          {preview.locked > 0 && (
            <p>
              A védett kézi javítások megmaradnak; a szerver ezeket kihagyja.
            </p>
          )}
          {preview.conflicts > 0 && (
            <p role="alert">
              Az ütközéseket előbb rendezni kell. A módosítás nem alkalmazható.
            </p>
          )}
          <button
            className="primary"
            disabled={
              !preview.canApply ||
              preview.conflicts > 0 ||
              busy ||
              conflict ||
              !ports.apply
            }
            onClick={apply}
          >
            {target.kind === "mapping"
              ? "Kategóriatérkép jóváhagyása"
              : "Módosítás mentése"}
          </button>
        </section>
      )}
    </Panel>
  );
}
