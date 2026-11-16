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
  onApplied: (message?: string) => void;
  initialChoice?: Choice;
}) {
  const [choice, setChoice] = useState<Choice | null>(
    initialChoice?.selectable ? initialChoice : null,
  );
  const [action, setAction] = useState<"set" | "reset" | "reject">("set");
  const [donorKey, setDonorKey] = useState("");
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
    if ((action === "set" && !choice) || !reason.trim() || !ports.preview)
      return;
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
          action,
          donorKey,
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
      (preview.conflicts ?? 0) > 0 ||
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
      const message = await ports.apply(preview, controller.signal);
      if (!controller.signal.aborted) onApplied(message || undefined);
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
          ? "Saját kategóriatérkép szerkesztése"
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
        a szerver biztosítja. A kategória kiválasztása nem jelenti a donorprofil
        vagy a későbbi automatikus dúsítás jóváhagyását.
      </p>
      {ports.resetSupported && (
        <label>
          Művelet
          <select
            aria-label="Művelet"
            value={action}
            disabled={busy || conflict}
            onChange={(e) => {
              invalidate();
              setAction(e.target.value as typeof action);
            }}
          >
            <option value="set">
              {target.kind === "mapping"
                ? "Kategóriatérkép jóváhagyása"
                : "Kézi besorolás"}
            </option>
            <option value="reset">
              {target.kind === "mapping"
                ? "Kategóriatérkép törlése és automatikus újrabesorolás"
                : "Kézi védelem feloldása és automatikus újrabesorolás"}
            </option>
            {target.kind === "mapping" && (
              <option value="reject">Kategóriatérkép elutasítása</option>
            )}
          </select>
        </label>
      )}
      {action !== "set" && (
        <p className="notice">
          A szerver újraértékeli az érintett besorolásokat. A saját kategóriák
          és eredeti termékadatok megmaradnak.
        </p>
      )}
      <fieldset
        className="classification-picker-lock"
        disabled={busy || conflict}
      >
        {action === "set" && ports.choices && (
          <CategoryPicker
            read={ports.choices}
            selected={choice}
            onSelect={(value) => {
              invalidate();
              setChoice(value);
              setDonorKey("");
            }}
          />
        )}
      </fieldset>
      {action === "set" && !!choice?.donors?.length && (
        <label>
          Paraméterprofil
          <select
            aria-label="Paraméterprofil"
            value={donorKey}
            disabled={busy}
            onChange={(e) => {
              invalidate();
              setDonorKey(e.target.value);
            }}
          >
            <option value="">Válassz paraméterprofilt</option>
            {choice.donors.map((d) => (
              <option key={d.key} value={d.key}>
                {d.title}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Módosítás indoka
        <textarea
          maxLength={500}
          value={reason}
          disabled={busy}
          onChange={(e) => {
            invalidate();
            setReason(e.target.value);
          }}
        />
      </label>
      {target.kind === "mapping" && ports.mappingPropagation === "always" && (
        <p className="notice">
          A jóváhagyás a saját kategória összes nem zárolt termékére azonnal
          érvényesül. A védett kézi döntések megmaradnak.
        </p>
      )}
      {target.kind === "mapping" && ports.mappingPropagation !== "always" && (
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
      {error && !conflict && (
        <button onClick={onRefresh}>Friss adatok betöltése</button>
      )}
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
            (action === "set" && !choice) ||
            !reason.trim() ||
            busy ||
            conflict ||
            !ports.preview
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
          {preview.localOnly && (
            <p className="notice">
              Helyi módosítás-összesítő, nem szerveroldali próbafuttatás. A
              szerver mentéskor ellenőrzi a jogosultságokat és a revíziót. Az
              érintett termékszám felső becslés; a pontos eredményt a mentési
              válasz adja meg.
            </p>
          )}
          <p>{preview.summary}</p>
          <dl className="data-list">
            <div>
              <dt>Érintett termékek</dt>
              <dd>{preview.affected.toLocaleString("hu-HU")}</dd>
            </div>
            <div>
              <dt>Védett, kihagyandó</dt>
              <dd>
                {preview.locked?.toLocaleString("hu-HU") ??
                  "Mentéskor derül ki"}
              </dd>
            </div>
            <div>
              <dt>Ütközések</dt>
              <dd>
                {preview.conflicts?.toLocaleString("hu-HU") ??
                  "Mentéskor ellenőrzött"}
              </dd>
            </div>
          </dl>
          <ul>
            {preview.changes.map((change, index) => (
              <li key={index}>
                {change.label}: {change.before || "–"} → {change.after || "–"}
              </li>
            ))}
          </ul>
          {(preview.locked ?? 0) > 0 && (
            <p>
              A védett kézi javítások megmaradnak; a szerver ezeket kihagyja.
            </p>
          )}
          {(preview.conflicts ?? 0) > 0 && (
            <p role="alert">
              Az ütközéseket előbb rendezni kell. A módosítás nem alkalmazható.
            </p>
          )}
          <button
            className="primary"
            disabled={
              !preview.canApply ||
              (preview.conflicts ?? 0) > 0 ||
              busy ||
              conflict ||
              !ports.apply
            }
            onClick={apply}
          >
            {target.kind === "mapping"
              ? action === "reset"
                ? "Kategóriatérkép törlése"
                : action === "reject"
                  ? "Kategóriatérkép elutasítása"
                  : "Kategóriatérkép jóváhagyása"
              : "Módosítás mentése"}
          </button>
        </section>
      )}
    </Panel>
  );
}
