import React, { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import type { PresentationPorts } from "./presentation";
import { usePresentationRead } from "./usePresentationRead";

export function ClassificationThreshold({
  ports,
}: {
  ports: PresentationPorts;
}) {
  const read = ports.threshold;
  const load = useCallback(
    (signal: AbortSignal) => {
      if (!read)
        return Promise.reject(
          new Error("A besorolási beállítás API-kapcsolata még nem érhető el."),
        );
      return read(signal);
    },
    [read],
  );
  const result = usePresentationRead(load);
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const percent = draft ?? String(saved ?? result.data ?? "");
  const number = percent.trim() === "" ? NaN : Number(percent);
  const valid = Number.isFinite(number) && number >= 50 && number <= 100;
  async function save() {
    if (!valid || !ports.saveThreshold || busy) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const actual = await ports.saveThreshold(number, controller.signal);
      if (!Number.isFinite(actual) || actual < 50 || actual > 100)
        throw new Error("A kiszolgáló beállításválasza nem értelmezhető.");
      if (!controller.signal.aborted) {
        setSaved(actual);
        setDraft(null);
        setMessage("A besorolási küszöb mentve.");
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "A beállítás nem menthető.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <Panel title="Kategóriabesorolás beállítása">
      <p>
        A küszöböt és a besorolási döntést a kiszolgáló kezeli. A százalék nem
        empirikusan mért pontosság.
      </p>
      {result.loading && <p role="status">Beállítás betöltése…</p>}
      {(result.error || error) && <p role="alert">{error || result.error}</p>}
      {message && <p role="status">{message}</p>}
      {result.data !== null && !result.error && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label>
            Kategória-besorolási admin küszöb (%)
            <input
              type="number"
              min="50"
              max="100"
              step="0.1"
              value={percent}
              disabled={busy || !ports.saveThreshold}
              onChange={(e) => {
                setDraft(e.target.value);
                setMessage("");
              }}
            />
          </label>
          {ports.saveThreshold && (
            <button disabled={!valid || busy}>Besorolási küszöb mentése</button>
          )}
        </form>
      )}
    </Panel>
  );
}
