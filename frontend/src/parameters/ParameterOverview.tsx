import { LiveBulkPreparation } from "./LiveBulkPreparation";
import type { Request } from "../classification/category02Contract";
import type { ParameterAccess } from "./liveContract";
import React, { useCallback, useState } from "react";
import {
  usePresentationRead,
  usePresentationSearch,
} from "../classification/usePresentationRead";
import { parameterLabels } from "./presentation";
import { slotStates } from "./liveContract";
import type { LiveParameterApi } from "./liveApi";
export function ParameterOverview({
  api,
  onOpen,
  request,
  access,
}: {
  request?: Request;
  access?: ParameterAccess;
  api: LiveParameterApi;
  onOpen: (id: number) => void;
}) {
  const [selected, Selected] = useState<number[]>([]);
  const [search, S] = useState("");
  const query = usePresentationSearch(search);
  const [state, T] = useState("");
  const [profile, P] = useState("");
  const [mandatory, M] = useState("");
  const [cursor, C] = useState<number | null>(null);
  const [history, H] = useState<(number | null)[]>([]);
  const [tick, R] = useState(0);
  const load = useCallback(
    (s: AbortSignal) => {
      void tick;
      const q = new URLSearchParams({
        cursor: String(cursor || 0),
        limit: "25",
      });
      if (query.trim()) q.set("q", query);
      if (state) q.set("state", state);
      if (profile) q.set("parameter_profile_state", profile);
      if (mandatory) q.set("mandatory_missing", mandatory);
      return api.list(q, s);
    },
    [api, query, state, profile, mandatory, cursor, tick],
  );
  const read = usePresentationRead(load);
  function reset() {
    Selected([]);
    C(null);
    H([]);
  }
  return (
    <section aria-label="Paraméteres termékáttekintés">
      <h3>Paraméterhelyek termékenként</h3>
      <p>
        A számlálók tárolt helyeket mutatnak. A „van tárolt hely” nem
        felhasználói jóváhagyás.
      </p>
      <div className="filters">
        <label>
          Paraméteres termékkeresés
          <input
            maxLength={120}
            value={search}
            onChange={(e) => {
              S(e.target.value);
              reset();
            }}
          />
        </label>
        <label>
          Paraméterhely állapota
          <select
            aria-label="Paraméterhely állapota"
            value={state}
            onChange={(e) => {
              T(e.target.value);
              reset();
            }}
          >
            <option value="">Minden állapot</option>
            {slotStates.map((s) => (
              <option key={s} value={s}>
                {parameterLabels[s]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Donor készültsége
          <select
            aria-label="Donor készültsége"
            value={profile}
            onChange={(e) => {
              P(e.target.value);
              reset();
            }}
          >
            <option value="">Minden donorállapot</option>
            <option value="ready">Kész paraméterprofil</option>
            <option value="choice_required">Profilválasztás szükséges</option>
            <option value="pending_review">Donor felülvizsgálatra vár</option>
            <option value="none">Nincs paraméterprofil</option>
          </select>
        </label>
        <label>
          Kötelező hiány
          <select
            aria-label="Kötelező hiány"
            value={mandatory}
            onChange={(e) => {
              M(e.target.value);
              reset();
            }}
          >
            <option value="">Mind</option>
            <option value="true">Van kötelező hiány</option>
            <option value="false">Nincs kötelező hiány</option>
          </select>
        </label>
      </div>
      {read.loading && <p role="status">Paraméteres áttekintés betöltése…</p>}
      {read.error && (
        <>
          <p role="alert">{read.error}</p>
          <button onClick={() => R((t) => t + 1)}>
            Áttekintés újratöltése
          </button>
        </>
      )}
      {read.data && !read.data.items.length && (
        <p>Nincs a paraméterszűrésnek megfelelő termék.</p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Kijelölés</th>
              <th>Termék / SKU</th>
              <th>Helyek és kötelező hiány</th>
              <th>Állapot</th>
              <th>Művelet</th>
            </tr>
          </thead>
          <tbody>
            {read.data?.items.map((p) => (
              <tr key={p.product_id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Kijelölés: ${p.name || p.product_id}`}
                    checked={selected.includes(p.product_id)}
                    onChange={(e) =>
                      Selected(
                        e.target.checked
                          ? [...selected, p.product_id]
                          : selected.filter((id) => id !== p.product_id),
                      )
                    }
                  />
                </td>
                <td>
                  {p.name || "Név nélküli termék"}
                  <small>{p.sku || "–"}</small>
                </td>
                <td>
                  {slotStates.map((s) => (
                    <span key={s}>
                      {parameterLabels[s]}: {p.counts[s]} ·{" "}
                    </span>
                  ))}
                  <p>Kötelező hiány: {p.mandatory_missing}</p>
                </td>
                <td>
                  {p.prepared ? "Van tárolt hely" : "Még nincs tárolt hely"} ·{" "}
                  {p.parameter_profile_state === "ready"
                    ? "Kész profil"
                    : p.parameter_profile_state === "choice_required"
                      ? "Profilválasztás szükséges"
                      : p.parameter_profile_state === "pending_review"
                        ? "Donor felülvizsgálatra vár"
                        : "Nincs donor"}
                </td>
                <td>
                  <button
                    disabled={search !== query || read.loading}
                    onClick={() => onOpen(p.product_id)}
                    aria-label={`Paraméteres termék megnyitása: ${p.name || p.product_id}`}
                  >
                    Megnyitás
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <button
          disabled={!history.length || read.loading || search !== query}
          onClick={() => {
            Selected([]);
            C(history.at(-1) ?? null);
            H(history.slice(0, -1));
          }}
        >
          Előző paraméteres termékek
        </button>
        <button
          disabled={!read.data?.next_cursor || read.loading || search !== query}
          onClick={() => {
            Selected([]);
            H([...history, cursor]);
            C(read.data?.next_cursor ?? null);
          }}
        >
          Következő paraméteres termékek
        </button>
      </div>
      {request && access && read.data && search === query && (
        <LiveBulkPreparation
          key={JSON.stringify([query, state, profile, mandatory])}
          request={request}
          access={access}
          selectedIds={selected}
          filters={{
            ...(query.trim() ? { q: query } : {}),
            ...(state ? { state } : {}),
            ...(profile ? { parameter_profile_state: profile } : {}),
            ...(mandatory ? { mandatory_missing: mandatory === "true" } : {}),
          }}
        />
      )}
    </section>
  );
}
