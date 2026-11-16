import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  usePresentationRead,
  usePresentationSearch,
} from "../classification/usePresentationRead";
import type { LiveParameterApi } from "./liveApi";
import type {
  Alias,
  AliasInput,
  ParameterAccess,
  Parameters,
} from "./liveContract";
export function LiveAliases({
  api,
  access,
  data,
  onChanged,
}: {
  api: LiveParameterApi;
  access: ParameterAccess;
  data: Parameters;
  onChanged: () => void;
}) {
  const [search, S] = useState("");
  const query = usePresentationSearch(search);
  const [scope, T] = useState<"all" | "tenant" | "global">("all");
  const [state, U] = useState<"approved" | "revoked">("approved");
  const [cursor, C] = useState<number | null>(null);
  const [history, H] = useState<(number | null)[]>([]);
  const [tick, R] = useState(0);
  const load = useCallback(
    (s: AbortSignal) => {
      void tick;
      return api.aliases(
        new URLSearchParams({
          q: query,
          scope,
          state,
          cursor: String(cursor || 0),
          limit: "25",
        }),
        s,
      );
    },
    [api, query, scope, state, cursor, tick],
  );
  const page = usePresentationRead(load);
  const [label, L] = useState("");
  const [unit, V] = useState("");
  const [param, P] = useState("");
  const [kind, K] = useState<"tenant" | "global">(
    access.edit ? "tenant" : "global",
  );
  const [reason, D] = useState("");
  const [intent, I] = useState<AliasInput | Alias | null>(null);
  const [busy, B] = useState(false);
  const [error, E] = useState("");
  const [message, M] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  function reset() {
    I(null);
    C(null);
    H([]);
    E("");
    M("");
    R((n) => n + 1);
  }
  async function apply() {
    if (!intent || busy) return;
    const c = new AbortController();
    pending.current = c;
    B(true);
    E("");
    try {
      if ("id" in intent)
        await api.revokeAlias(intent.id, intent.version, c.signal);
      else await api.createAlias(intent, c.signal);
      if (!c.signal.aborted) {
        reset();
        M(
          "Az aliasszabály mentve. A termékek csak külön alkalmazáskor változnak.",
        );
        onChanged();
      }
    } catch (e) {
      if (!c.signal.aborted) {
        E(e instanceof Error ? e.message : "Az alias nem menthető.");
        I(null);
      }
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  const choices = data.slots.filter(
    (s) => s.emag_parameter_id !== null && s.state !== "detached",
  );
  return (
    <section aria-label="Aliasszabályok">
      <h3>Aliasszabályok – kifejezett hatókörrel</h3>
      <p>
        Ez újrafelhasználható címkeszabály, nem egy termékérték javítása. Nem
        futtat visszamenőleges cserét, és nem hagy jóvá donort.
      </p>
      <label>
        Alias keresése
        <input
          maxLength={160}
          value={search}
          onChange={(e) => {
            S(e.target.value);
            C(null);
            H([]);
            I(null);
          }}
        />
      </label>
      <label>
        Aliasok hatóköre
        <select
          aria-label="Aliasok hatóköre"
          value={scope}
          onChange={(e) => {
            T(e.target.value as typeof scope);
            C(null);
            H([]);
            I(null);
          }}
        >
          <option value="all">Ügyfél és globális</option>
          <option value="tenant">Ez az ügyfél</option>
          <option value="global">Minden ügyfél</option>
        </select>
      </label>
      <label>
        Aliasok állapota
        <select
          aria-label="Aliasok állapota"
          value={state}
          onChange={(e) => {
            U(e.target.value as typeof state);
            C(null);
            H([]);
            I(null);
          }}
        >
          <option value="approved">Jóváhagyott</option>
          <option value="revoked">Visszavont</option>
        </select>
      </label>
      {page.loading && <p role="status">Aliasok betöltése…</p>}
      {page.error && <p role="alert">{page.error}</p>}
      {page.data && !page.data.items.length && (
        <p>Nincs a szűrésnek megfelelő aliasszabály.</p>
      )}
      <ul>
        {page.data?.items.map((a) => (
          <li key={a.id}>
            <strong>{a.label}</strong> ({a.unit || "Egység nélkül"}) →{" "}
            {a.emag_parameter_id} · Donor: {a.scope_emag_category_id} ·{" "}
            {a.scope === "global" ? "Minden ügyfél" : "Ez az ügyfél"} · Verzió:{" "}
            {a.version} ·{" "}
            {a.state === "approved" ? "Jóváhagyott" : "Visszavont"} ·{" "}
            {a.reason || ""}
            {a.state === "approved" &&
              (a.scope === "global" ? access.globalAliases : access.edit) && (
                <button
                  disabled={busy || !!error}
                  onClick={() => I(a)}
                  aria-label={`Alias visszavonása: ${a.label}`}
                >
                  Visszavonás
                </button>
              )}
          </li>
        ))}
      </ul>
      <div className="pager">
        <button
          disabled={!history.length || page.loading}
          onClick={() => {
            I(null);
            C(history.at(-1) ?? null);
            H(history.slice(0, -1));
          }}
        >
          Előző aliasok
        </button>
        <button
          disabled={!page.data?.next_cursor || page.loading}
          onClick={() => {
            I(null);
            H([...history, cursor]);
            C(page.data?.next_cursor ?? null);
          }}
        >
          Következő aliasok
        </button>
      </div>
      {(access.edit || access.globalAliases) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (error) return;
            if (!data.classification.donor_emag_category_id) return;
            I({
              scope: kind,
              label: label.trim(),
              unit: unit || null,
              emag_parameter_id: Number(param),
              scope_emag_category_id:
                data.classification.donor_emag_category_id,
              reason: reason.trim(),
            });
          }}
        >
          <fieldset
            disabled={
              busy ||
              !!intent ||
              !!error ||
              !data.classification.donor_emag_category_id ||
              !choices.length
            }
          >
            <legend>Új aliasszabály a kiválasztott donor környezetében</legend>
            <label>
              Alias címkéje
              <input
                required
                maxLength={160}
                value={label}
                onChange={(e) => L(e.target.value)}
              />
            </label>
            <label>
              Alias egysége
              <input
                maxLength={24}
                value={unit}
                onChange={(e) => V(e.target.value)}
              />
            </label>
            <label>
              Alias célparamétere
              <select
                aria-label="Alias célparamétere"
                required
                value={param}
                onChange={(e) => P(e.target.value)}
              >
                <option value="">Válassz létező donorparamétert</option>
                {choices.map((s) => (
                  <option key={s.slot_key} value={s.emag_parameter_id!}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Új alias hatóköre
              <select
                aria-label="Új alias hatóköre"
                value={kind}
                onChange={(e) => K(e.target.value as typeof kind)}
              >
                {access.edit && (
                  <option value="tenant">Csak ez az ügyfél</option>
                )}
                {access.globalAliases && (
                  <option value="global">Minden ügyfél – rendszerjog</option>
                )}
              </select>
            </label>
            <label>
              Alias indoka
              <textarea
                required
                maxLength={500}
                value={reason}
                onChange={(e) => D(e.target.value)}
              />
            </label>
            <button disabled={!label.trim() || !param || !reason.trim()}>
              Aliasszabály áttekintése
            </button>
          </fieldset>
        </form>
      )}
      {!choices.length && (
        <p>
          Új alias csak létező, a kiválasztott donorhoz tartozó paraméterre
          hozható létre. A forrásadat megmarad.
        </p>
      )}
      {intent && (
        <section aria-label="Aliasszabály megerősítése">
          <p>
            Helyi megerősítés, nem szerveres dry-run.{" "}
            {intent.scope === "global"
              ? "Minden ügyfélre érvényes szabály."
              : "Csak az aktív ügyfél szabálya."}{" "}
            {"id" in intent
              ? "Visszavonás az aktuális verzióval."
              : "A szabály külön alkalmazástól érvényesül; meglévő értéket most nem ír át."}
          </p>
          <button disabled={busy} onClick={apply}>
            Aliasszabály megerősítése
          </button>
          <button disabled={busy} onClick={() => I(null)}>
            Alias művelet elvetése
          </button>
        </section>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      {(error || page.error) && (
        <button onClick={reset}>Aliasok friss betöltése</button>
      )}
    </section>
  );
}
