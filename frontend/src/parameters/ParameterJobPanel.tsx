import { validateParameterJob } from "./validation";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import { usePresentationRead } from "../classification/usePresentationRead";
import type { ParameterJob, ParameterServices } from "./presentation";
type JobProps = ParameterServices & { initial: ParameterJob };
export function ParameterJobPanel(props: JobProps) {
  return <JobState key={props.initial.key} {...props} />;
}
function JobState({
  initial,
  ports,
  access,
}: ParameterServices & { initial: ParameterJob }) {
  const [tick, setTick] = useState(0);
  const [updated, setUpdated] = useState<ParameterJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(
    (s: AbortSignal) => {
      void tick;
      return (
        ports.job ? ports.job(initial.key, s) : Promise.resolve(initial)
      ).then(validateParameterJob);
    },
    [ports, initial, tick],
  );
  const read = usePresentationRead(load);
  const job = updated || read.data || initial;
  useEffect(() => {
    if (!ports.job || read.error || !["queued", "running"].includes(job.state))
      return;
    const timer = setTimeout(() => {
      setUpdated(null);
      setTick((t) => t + 1);
    }, 2500);
    return () => clearTimeout(timer);
  }, [ports, job, tick, read.error]);
  const states = {
    queued: "Sorban áll",
    running: "Feldolgozás alatt",
    paused: "Szüneteltetve",
    partial: "Részleges siker",
    completed: "Befejezve",
    failed: "Sikertelen",
    cancelled: "Megszakítva",
    superseded: "Újabb futás váltotta fel",
  };
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function act(kind: "resume" | "cancel") {
    const fn = ports[kind];
    if (!fn || busy) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      const next = validateParameterJob(await fn(job, controller.signal));
      if (!controller.signal.aborted) setUpdated(next);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "A futás nem módosítható.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  const progress = job.progressPercent;
  return (
    <Panel title="Paraméter-előkészítés futása">
      <p>Futás: {job.key}</p>
      <p role="status">
        {states[job.state]} · {job.message}
      </p>
      {progress !== null &&
      Number.isFinite(progress) &&
      progress >= 0 &&
      progress <= 100 ? (
        <>
          <progress
            aria-label="Futás előrehaladása"
            max={100}
            value={progress}
          />
          <p>{progress.toLocaleString("hu-HU")}% – szerveradat</p>
        </>
      ) : (
        <p>A százalékos előrehaladás még nem ismert.</p>
      )}
      <dl className="data-list">
        {[
          ["Feldolgozott", job.processed],
          ["Összes a futásban", job.total ?? "Még nem ismert"],
          ["Módosított", job.changed],
          ["Kihagyott / védett", job.skipped],
          ["Hibás", job.failed],
        ].map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v.toLocaleString("hu-HU")}</dd>
          </div>
        ))}
      </dl>
      <p>
        Legfeljebb 50 000 termék egy feldolgozási futásban; a teljes tárolt
        állomány ennél nagyobb lehet.
      </p>
      {(error || read.error) && <p role="alert">{error || read.error}</p>}
      {!!job.errors.length && (
        <ul aria-label="Futás hibái">
          {job.errors.map((e, i) => (
            <li key={i}>
              {e.label}: {e.message}
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button
          disabled={busy || !ports.job}
          onClick={() => {
            setUpdated(null);
            setTick((t) => t + 1);
          }}
        >
          Futás frissítése
        </button>
        {access.manageJobs && ports.resume && job.canResume && (
          <button disabled={busy} onClick={() => act("resume")}>
            Feldolgozás folytatása
          </button>
        )}
        {access.manageJobs && ports.cancel && job.canCancel && (
          <button disabled={busy} onClick={() => act("cancel")}>
            Hátralévő feldolgozás megszakítása
          </button>
        )}
      </div>
    </Panel>
  );
}
