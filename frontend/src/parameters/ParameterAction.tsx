import { validateParameterJob } from "./validation";
import React, { useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import {
  ParameterRevisionConflict,
  type ParameterIntent,
  type ParameterPorts,
  type ParameterPreview,
  type ParameterJob,
} from "./presentation";

export function ParameterAction({
  intent,
  ports,
  onClose,
  onRefresh,
  onApplied,
}: {
  intent: Omit<ParameterIntent, "reason">;
  ports: ParameterPorts;
  onClose: () => void;
  onRefresh: () => void;
  onApplied: (message: string, job: ParameterJob | null) => void;
}) {
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ParameterPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function inspect() {
    if (!ports.preview || !reason.trim()) return;
    pending.current?.abort();
    const c = new AbortController();
    pending.current = c;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const p = await ports.preview(
        { ...intent, reason: reason.trim() },
        c.signal,
      );
      if (!p) throw new Error("Az előnézet válasza nem értelmezhető.");
      const numbers = [
        p.eligible,
        p.preserved,
        p.addedEmpty,
        p.locked,
        p.conflicts,
        p.blocked,
        p.sourceOverwrites,
      ];
      if (
        !["server", "local"].includes(p.origin) ||
        !numbers.every((n) => Number.isSafeInteger(n) && n >= 0) ||
        !Array.isArray(p.changes) ||
        !Array.isArray(p.runs)
      )
        throw new Error("Az előnézet válasza nem értelmezhető.");
      if (!c.signal.aborted) setPreview(p);
    } catch (e) {
      if (!c.signal.aborted) {
        setError(
          e instanceof Error ? e.message : "Az előnézet nem tölthető be.",
        );
        setStale(e instanceof ParameterRevisionConflict);
      }
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  const validRuns =
    !preview ||
    preview.runs.every(
      (r) => Number.isSafeInteger(r.count) && r.count > 0 && r.count <= 50000,
    );
  async function apply() {
    if (
      !preview ||
      !ports.apply ||
      preview.origin !== "server" ||
      !preview.canApply ||
      !validRuns ||
      preview.sourceOverwrites !== 0 ||
      busy ||
      stale
    )
      return;
    const c = new AbortController();
    pending.current = c;
    setBusy(true);
    setError("");
    try {
      const result = await ports.apply(preview, c.signal);
      if (!result || typeof result.message !== "string" || !("job" in result))
        throw new Error(
          "A mentés eredménye nem igazolható. Töltsd újra az adatokat.",
        );
      if (result.job) validateParameterJob(result.job);
      if (!c.signal.aborted) onApplied(result.message, result.job);
    } catch (e) {
      if (!c.signal.aborted) {
        setError(e instanceof Error ? e.message : "A módosítás nem menthető.");
        setStale(e instanceof ParameterRevisionConflict);
        setPreview(null);
      }
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <Panel title="Paramétermódosítás ellenőrzése">
      <p>
        Az eredeti beszállítói érték megmarad. A javítás és jóváhagyás külön,
        auditált döntés.
      </p>
      <label>
        Döntés indoka
        <textarea
          maxLength={500}
          value={reason}
          disabled={busy || stale}
          onChange={(e) => {
            setReason(e.target.value);
            setPreview(null);
          }}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      {error && (
        <button onClick={onRefresh}>Friss paraméteradatok betöltése</button>
      )}
      {stale && (
        <p className="notice">
          A revízió vagy a pillanatkép megváltozott. Új lekérés és új előnézet
          szükséges; nincs automatikus újramentés.
        </p>
      )}
      <div className="actions">
        <button
          disabled={!reason.trim() || busy || stale || !ports.preview}
          onClick={inspect}
        >
          Paraméterváltozások előnézete
        </button>
        <button disabled={busy} onClick={onClose}>
          Mégse
        </button>
      </div>
      {busy && <p role="status">Paraméterművelet folyamatban…</p>}
      {preview && (
        <section aria-label="Paraméterváltozások előnézete">
          <h3>
            {preview.origin === "server"
              ? "Szerveroldali változáselőnézet"
              : "Kliensoldali becslés – nem szerveres próbafuttatás"}
          </h3>
          <p>{preview.summary}</p>
          <dl className="data-list">
            {[
              ["Alkalmazható", preview.eligible],
              ["Megmarad", preview.preserved],
              ["Új üres hely", preview.addedEmpty],
              ["Védett, kihagyandó", preview.locked],
              ["Ütköző", preview.conflicts],
              ["Blokkolt", preview.blocked],
              ["Forrásértékek felülírása", preview.sourceOverwrites],
            ].map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v.toLocaleString("hu-HU")}</dd>
              </div>
            ))}
          </dl>
          <ul>
            {preview.changes.map((c, i) => (
              <li key={i}>
                {c.label}: {c.before || "–"} → {c.after || "–"}
              </li>
            ))}
          </ul>
          {!!preview.runs.length && (
            <>
              <h4>A szerver által tervezett futások</h4>
              <ul>
                {preview.runs.map((r, i) => (
                  <li key={i}>
                    {r.label}: {r.count.toLocaleString("hu-HU")} termék
                  </li>
                ))}
              </ul>
            </>
          )}
          {!validRuns && (
            <p role="alert">
              A kapott terv túllépi a futásonkénti 50 000 termékes korlátot. Új
              szerveroldali terv szükséges.
            </p>
          )}
          {preview.sourceOverwrites !== 0 && (
            <p role="alert">Forrásértéket felülíró művelet nem alkalmazható.</p>
          )}
          <button
            className="primary"
            disabled={
              preview.origin !== "server" ||
              !preview.canApply ||
              !validRuns ||
              preview.sourceOverwrites !== 0 ||
              busy ||
              stale ||
              !ports.apply
            }
            onClick={apply}
          >
            Előnézet jóváhagyása és alkalmazása
          </button>
        </section>
      )}
    </Panel>
  );
}
