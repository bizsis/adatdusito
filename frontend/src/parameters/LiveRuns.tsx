import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePresentationRead } from "../classification/usePresentationRead";
import type { LiveParameterApi } from "./liveApi";
import type { Job, RunScope } from "./liveContract";
export function LiveRuns({
  api,
  canEdit,
  scopes,
}: {
  api: LiveParameterApi;
  canEdit: boolean;
  scopes: { key: string; label: string; scope: RunScope }[];
}) {
  const [scope, S] = useState(scopes[0]?.key || "");
  const [mode, M] = useState<"preview" | "apply">("preview");
  const [confirm, C] = useState<{
    mode: "preview" | "apply";
    scope: RunScope;
    after: number;
    label: string;
  } | null>(null);
  const [job, J] = useState<Job | null>(null);
  const [jobId, I] = useState("");
  const [tick, T] = useState(0);
  const [busy, B] = useState(false);
  const [error, E] = useState("");
  const [warning, W] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const current = job?.id ?? null;
  const load = useCallback(
    (s: AbortSignal) => {
      void tick;
      if (current === null)
        return Promise.reject(new Error("Nincs kiválasztott futás."));
      return api.job(current, s);
    },
    [api, current, tick],
  );
  const read = usePresentationRead(current === null ? null : load);
  const data = read.data || job;
  useEffect(() => {
    if (!data || read.error || !["pending", "running"].includes(data.state))
      return;
    const timer = setTimeout(() => T((t) => t + 1), 2500);
    return () => clearTimeout(timer);
  }, [data, tick, read.error]);
  async function start() {
    if (!confirm || busy) return;
    const c = new AbortController();
    pending.current = c;
    B(true);
    E("");
    W("");
    try {
      const result = await api.run(
        confirm.mode,
        confirm.scope,
        confirm.after,
        c.signal,
      );
      if (!c.signal.aborted) {
        J(result.job);
        I(String(result.job.id));
        C(null);
        T((t) => t + 1);
        if (result.enqueue_failed)
          W(
            "A futás létrejött, de a sorba állítás nem sikerült. A worker állapotát ellenőrizni kell; a felület nem próbálja vakon újra.",
          );
      }
    } catch (e) {
      if (!c.signal.aborted) {
        E(e instanceof Error ? e.message : "A futás nem indítható.");
        C(null);
      }
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  async function open() {
    if (!/^\d+$/.test(jobId) || Number(jobId) < 1) return;
    const c = new AbortController();
    pending.current?.abort();
    pending.current = c;
    B(true);
    E("");
    try {
      const result = await api.job(Number(jobId), c.signal);
      if (!c.signal.aborted) {
        J(result);
        T((t) => t + 1);
      }
    } catch (e) {
      if (!c.signal.aborted)
        E(e instanceof Error ? e.message : "A futás nem olvasható.");
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  const stateLabels = {
    pending: "Sorban áll",
    running: "Feldolgozás alatt",
    completed: "Futás befejezve",
    failed: "Futás sikertelen",
    superseded: "Újabb futás váltotta fel",
  };
  return (
    <section aria-label="Valódi paraméterfutások">
      <h3>Paraméterhelyek háttérfutása</h3>
      <p>
        Önálló szerveroldali újraszámítás, nem egy korábbi előnézeti token vagy
        tetszőleges kijelölési snapshot alkalmazása. Futásonként legfeljebb 50
        000 termék; a teljes állomány ennél nagyobb lehet.
      </p>
      {canEdit && (
        <fieldset disabled={busy || !!confirm}>
          <label>
            Futás hatóköre
            <select
              aria-label="Futás hatóköre"
              value={scope}
              onChange={(e) => S(e.target.value)}
            >
              {scopes.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Futás módja
            <select
              aria-label="Futás módja"
              value={mode}
              onChange={(e) => M(e.target.value as typeof mode)}
            >
              <option value="preview">Előnézet – nem ír paraméterhelyet</option>
              <option value="apply">Újraszámítás és alkalmazás</option>
            </select>
          </label>
          <button
            onClick={() => {
              const s = scopes.find((s) => s.key === scope);
              if (s) C({ mode, scope: s.scope, after: 0, label: s.label });
            }}
          >
            Futás indításának áttekintése
          </button>
        </fieldset>
      )}
      {confirm && (
        <section aria-label="Paraméterfutás megerősítése">
          <p>
            Hatókör: {confirm.label}. Mód:{" "}
            {confirm.mode === "preview" ? "Csak számítás" : "Alkalmazás"}. Kezdő
            termékkurzor: {confirm.after}. Ez új, külön futás; nincs snapshothoz
            kötött tömeges jóváhagyás.
          </p>
          <button disabled={busy} onClick={start}>
            Paraméterfutás indítása
          </button>
          <button disabled={busy} onClick={() => C(null)}>
            Futás indításának elvetése
          </button>
        </section>
      )}
      <label>
        Meglévő paraméterfutás azonosítója
        <input
          type="number"
          min="1"
          value={jobId}
          onChange={(e) => I(e.target.value)}
        />
      </label>
      <button disabled={busy || !jobId} onClick={open}>
        Futás betöltése
      </button>
      {(error || read.error) && <p role="alert">{error || read.error}</p>}
      {warning && <p className="notice">{warning}</p>}
      {data && (
        <>
          <p role="status">
            Futás #{data.id}: {stateLabels[data.state]} ·{" "}
            {data.mode === "preview" ? "Előnézet" : "Alkalmazás"}
          </p>
          <p>
            Hatókör: saját kategória {data.scope.source_category_id ?? "mind"},
            belső kategória {data.scope.navigation_node_id ?? "mind"},
            beszállító {data.scope.supplier_id ?? "mind"}.
          </p>
          <p>
            Feldolgozott: {data.processed.toLocaleString("hu-HU")} ·
            Futáskorlát: {data.limit.toLocaleString("hu-HU")} · Módosult
            termékek: {data.products_changed.toLocaleString("hu-HU")} · Nem kész
            donor: {data.products_not_ready.toLocaleString("hu-HU")}
          </p>
          <p>
            Helyek: új {data.slots.create}, módosult {data.slots.update},
            megszűnő üres {data.slots.remove}, megmaradó {data.slots.keep},
            védett {data.slots.blocked_locked}.
          </p>
          <p>
            A százalékos készültség nem ismert: a backend nem ad teljes
            feldolgozási darabszámot. A feldolgozott/futáskorlát arány nem a
            teljes állomány készültsége.
          </p>
          {data.stalled && (
            <p className="notice">
              A futás állapotadata elakadásra utal. Automatikus ismétlés nem
              történik.
            </p>
          )}
          {data.error && <p role="alert">{data.error}</p>}
          <button disabled={busy} onClick={() => T((t) => t + 1)}>
            Paraméterfutás állapotának frissítése
          </button>
          {canEdit &&
            data.state === "completed" &&
            data.has_more &&
            data.next_start_after_product_id !== null && (
              <button
                disabled={busy}
                onClick={() =>
                  C({
                    mode: data.mode,
                    scope: data.scope,
                    after: data.next_start_after_product_id!,
                    label: "Az előző futás változatlan hatóköre",
                  })
                }
              >
                Következő legfeljebb 50 000 termék áttekintése
              </button>
            )}
          {data.has_more && (
            <p>
              További termékek vannak; a következő futás kezdőkurzora:{" "}
              {data.next_start_after_product_id}.
            </p>
          )}
          {canEdit && (data.state === "failed" || data.stalled) && (
            <>
              <p>
                A backend ehhez az állapothoz nem ad biztonságos részleges
                folytatókurzort. Külön, ismétlésbiztos újraszámítás indítható az
                elejétől.
              </p>
              <button
                disabled={busy}
                onClick={() =>
                  C({
                    mode: data.mode,
                    scope: data.scope,
                    after: 0,
                    label: "Azonos hatókör, új futás az elejétől",
                  })
                }
              >
                Új futás az elejétől – áttekintés
              </button>
            </>
          )}
          <p>
            Összesített futásadatok; tételenkénti teljes hibanapló és általános
            megszakítási API nem érhető el ebben a szerződésben.
          </p>
        </>
      )}
    </section>
  );
}
