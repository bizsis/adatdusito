import React, { useEffect, useRef, useState } from "react";
import type { LiveParameterApi } from "./liveApi";
import type { Slot, SlotAction } from "./liveContract";
export function LiveSlotEditor({
  product,
  revision,
  slot,
  api,
  canEdit,
  onRefresh,
}: {
  product: string;
  revision: number;
  slot: Slot;
  api: LiveParameterApi;
  canEdit: boolean;
  onRefresh: () => void;
}) {
  const [action, setAction] = useState<SlotAction["action"]>("set");
  const [value, setValue] = useState(slot.value ?? "");
  const [unit, setUnit] = useState(slot.unit ?? "");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState<SlotAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const constrained =
    slot.allow_new_value === false && slot.emag_parameter_id !== null;
  const sources = [
    ...new Set([
      ...slot.sources.map((s) => s.key),
      ...slot.candidates.flatMap((c) => (c.source_key ? [c.source_key] : [])),
    ]),
  ];
  const allowed =
    action !== "set" ||
    (!slot.locked && !constrained && value.trim().length > 0);
  async function save() {
    if (!confirm || busy || stale) return;
    const c = new AbortController();
    pending.current = c;
    setBusy(true);
    setError("");
    try {
      await api.patch(product, slot.slot_key, confirm, c.signal);
      if (!c.signal.aborted) onRefresh();
    } catch (e) {
      if (!c.signal.aborted) {
        setError(
          e instanceof Error ? e.message : "A kézi módosítás nem menthető.",
        );
        setStale(true);
        setConfirm(null);
      }
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <section aria-label="Valódi paraméterhely szerkesztése">
      <h3>Kézi paraméterdöntés</h3>
      <p>
        A nyers forrásadatok megmaradnak; a kézi döntés revíziózott és auditált.
        Revízió: {revision}.
      </p>
      {constrained && (
        <p className="notice">
          Kötött értékkészlet. Szabad értékadás itt nem elérhető; ismert
          forrásjelölt elfogadható. Univerzális
          értékválasztó/értéklista-szerkesztés nincs bekötve.
        </p>
      )}
      {!canEdit && (
        <p>Csak olvasható; nincs paramétermódosítási jogosultság.</p>
      )}
      {slot.locked && (
        <p className="notice">
          A hely védett. Új kézi értékhez előbb kifejezetten oldd fel a
          védelmet.
        </p>
      )}
      {canEdit && (
        <>
          <fieldset disabled={busy || stale || !!confirm}>
            <label>
              Kézi művelet
              <select
                aria-label="Kézi művelet"
                value={action}
                onChange={(e) =>
                  setAction(e.target.value as SlotAction["action"])
                }
              >
                <option value="set" disabled={constrained || slot.locked}>
                  Érték javítása és védelme
                </option>
                <option
                  value="accept_candidate"
                  disabled={slot.locked || !sources.length}
                >
                  Forrásjelölt elfogadása
                </option>
                <option value="lock" disabled={slot.locked}>
                  Zárolás
                </option>
                <option value="unlock" disabled={!slot.locked}>
                  Védelem feloldása
                </option>
                <option value="reset">Védelem feloldása és újraszámítás</option>
              </select>
            </label>
            {action === "set" && (
              <>
                <label>
                  Új kézi érték
                  <input
                    maxLength={1000}
                    disabled={constrained || slot.locked}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                  />
                </label>
                <label>
                  Érték egysége
                  <input
                    maxLength={24}
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                  />
                </label>
              </>
            )}
            {action === "accept_candidate" && (
              <label>
                Elfogadandó forrás
                <select
                  aria-label="Elfogadandó forrás"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="">Válassz megőrzött forrást</option>
                  {sources.map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Kézi döntés indoka
              <textarea
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          </fieldset>
          {!confirm && (
            <button
              disabled={
                !allowed ||
                !reason.trim() ||
                busy ||
                stale ||
                (action === "accept_candidate" && (!source || slot.locked)) ||
                (action === "lock" && slot.locked) ||
                (action === "unlock" && !slot.locked)
              }
              onClick={() =>
                setConfirm({
                  expected_revision: revision,
                  action,
                  reason: reason.trim(),
                  ...(action === "set"
                    ? { value, unit: unit || null }
                    : action === "accept_candidate"
                      ? { source_key: source }
                      : {}),
                })
              }
            >
              Kézi döntés áttekintése
            </button>
          )}
          {confirm && (
            <section aria-label="Kézi döntés megerősítése">
              <h4>Helyi megerősítés – nem szerveres változáselőnézet</h4>
              <p>
                Művelet: {confirm.action}. Korábbi érték:{" "}
                {slot.value ?? "Nincs"} {slot.unit || ""}; tervezett érték:{" "}
                {confirm.value ?? confirm.source_key ?? "A művelet szerint"}. A
                szerver mentéskor ellenőrzi a revíziót és az értéket.
              </p>
              <button
                className="primary"
                disabled={busy || stale}
                onClick={save}
              >
                Kézi döntés mentése
              </button>
              <button disabled={busy} onClick={() => setConfirm(null)}>
                Kézi döntés elvetése
              </button>
            </section>
          )}
        </>
      )}
      {busy && <p role="status">Kézi döntés mentése folyamatban…</p>}
      {error && <p role="alert">{error}</p>}
      {error && <button onClick={onRefresh}>Friss helyadatok betöltése</button>}
    </section>
  );
}
