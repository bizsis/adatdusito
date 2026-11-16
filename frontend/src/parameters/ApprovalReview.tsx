import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePresentationRead } from "../classification/usePresentationRead";
import type { BulkApi } from "./bulkApi";
export function ApprovalReview({
  api,
  canApprove,
  selectedId,
  refresh,
}: {
  api: BulkApi;
  canApprove: boolean;
  selectedId: number | null;
  refresh: number;
}) {
  const [id, S] = useState(selectedId);
  const [cursor, C] = useState<number | null>(null);
  const [history, H] = useState<(number | null)[]>([]);
  const [state, F] = useState("active");
  const [tick, T] = useState(0);
  const load = useCallback(
    (s: AbortSignal) => {
      void refresh;
      void tick;
      return api.approvals(
        new URLSearchParams({
          state,
          cursor: String(cursor || 0),
          limit: "25",
        }),
        s,
      );
    },
    [api, state, cursor, refresh, tick],
  );
  const list = usePresentationRead(load);
  return (
    <section aria-label="Előkészítési jóváhagyások">
      <h3>Előkészítési jóváhagyások</h3>
      <p>
        A jóváhagyás termék-, katalógus- és szabályrevízióhoz kötött. Az
        érvényesség minden adatváltozás után újraellenőrizendő. Ez nem
        kutatásindítás.
      </p>
      <label>
        Jóváhagyások állapota
        <select
          aria-label="Jóváhagyások állapota"
          value={state}
          onChange={(e) => {
            F(e.target.value);
            C(null);
            H([]);
          }}
        >
          <option value="active">Aktív</option>
          <option value="revoked">Visszavont</option>
        </select>
      </label>
      {list.error && <p role="alert">{list.error}</p>}
      <button onClick={() => T((v) => v + 1)}>
        Jóváhagyáslista frissítése
      </button>
      <ul>
        {list.data?.items.map((a) => (
          <li key={a.id}>
            #{a.id} · Jóváhagyott: {a.approved} · Utolsó mérés szerint érvényes:{" "}
            {a.valid}; érvénytelen: {a.invalid}.{" "}
            <button onClick={() => S(a.id)}>
              Jóváhagyás #{a.id} megnyitása
            </button>
          </li>
        ))}
      </ul>
      <button
        disabled={!history.length || list.loading}
        onClick={() => {
          C(history.at(-1) ?? null);
          H(history.slice(0, -1));
        }}
      >
        Előző jóváhagyások
      </button>
      <button
        disabled={!list.data?.next_cursor || list.loading}
        onClick={() => {
          H([...history, cursor]);
          C(list.data?.next_cursor ?? null);
        }}
      >
        Következő jóváhagyások
      </button>
      {id !== null && (
        <ApprovalDetail
          key={id}
          api={api}
          id={id}
          canApprove={canApprove}
          onChanged={() => T((v) => v + 1)}
        />
      )}
    </section>
  );
}
function ApprovalDetail({
  api,
  id,
  canApprove,
  onChanged,
}: {
  api: BulkApi;
  id: number;
  canApprove: boolean;
  onChanged: () => void;
}) {
  const [tick, T] = useState(0);
  const load = useCallback(
    (s: AbortSignal) => {
      void tick;
      return api.approval(id, s);
    },
    [api, id, tick],
  );
  const read = usePresentationRead(load);
  const [cursor, C] = useState<number | null>(null);
  const [history, H] = useState<(number | null)[]>([]);
  const [valid, V] = useState("");
  const itemsLoad = useCallback(
    (s: AbortSignal) => {
      void tick;
      const q = new URLSearchParams({
        cursor: String(cursor || 0),
        limit: "25",
      });
      if (valid) q.set("valid", valid);
      return api.approvalItems(id, q, s);
    },
    [api, id, cursor, valid, tick],
  );
  const items = usePresentationRead(itemsLoad);
  const [reason, R] = useState("");
  const [confirm, F] = useState<{
    kind: "revoke" | "revalidate";
    version: number;
  } | null>(null);
  const [busy, B] = useState(false);
  const [error, E] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const refresh = () => {
    E("");
    F(null);
    T((v) => v + 1);
  };
  async function save() {
    if (!confirm || busy) return;
    const c = new AbortController();
    pending.current = c;
    B(true);
    E("");
    try {
      if (confirm.kind === "revoke")
        await api.revoke(id, confirm.version, reason.trim(), c.signal);
      else await api.revalidate(id, c.signal);
      if (!c.signal.aborted) {
        refresh();
        onChanged();
      }
    } catch (e) {
      if (!c.signal.aborted) {
        E(e instanceof Error ? e.message : "A jóváhagyás nem módosítható.");
        F(null);
      }
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  const a = read.data;
  return (
    <section aria-label={`Jóváhagyás ${id} részletei`}>
      {read.error && <p role="alert">{read.error}</p>}
      {items.error && <p role="alert">{items.error}</p>}
      {error && <p role="alert">{error}</p>}
      <button disabled={busy} onClick={refresh}>
        Jóváhagyás aktuális érvényességének frissítése
      </button>
      {a && (
        <>
          <h4>Előkészítési jóváhagyás #{a.id}</h4>
          <p>
            Állapot: {a.state === "active" ? "Aktív" : "Visszavont"} · Verzió:{" "}
            {a.version} · Jelenleg érvényes: {a.valid}; érvénytelen: {a.invalid}
            ; jóváhagyáskor kihagyott, elavult: {a.skipped_stale}.
          </p>
          <p>
            Katalógus: {a.catalog_version_id} · Szabály: {a.rule_version} ·
            Séma: {a.schema_current ? "Aktuális" : "Megváltozott"} · Kutatandó
            hiány: {a.research_targets}; kötelező:{" "}
            {a.mandatory_research_targets}.
          </p>
          {canApprove && a.state === "active" && (
            <>
              <button
                disabled={busy || !!error || !!confirm}
                onClick={() => F({ kind: "revalidate", version: a.version })}
              >
                Jóváhagyás újramérésének áttekintése
              </button>
              <label>
                Visszavonás indoka
                <textarea
                  aria-label="Visszavonás indoka"
                  maxLength={500}
                  value={reason}
                  onChange={(e) => {
                    R(e.target.value);
                    F(null);
                  }}
                />
              </label>
              <button
                disabled={
                  busy || !!error || !!confirm || reason.trim().length < 3
                }
                onClick={() => F({ kind: "revoke", version: a.version })}
              >
                Jóváhagyás visszavonásának áttekintése
              </button>
            </>
          )}
          {confirm && (
            <>
              <p>
                {confirm.kind === "revoke"
                  ? "A jóváhagyás visszavonása nem törli a tételeket."
                  : "Az újramérés végleg érvényteleníti az elavult tételeket; nem teszi újra érvényessé őket."}
              </p>
              <button disabled={busy} onClick={save}>
                Jóváhagyási döntés megerősítése
              </button>
              <button disabled={busy} onClick={() => F(null)}>
                Jóváhagyási döntés elvetése
              </button>
            </>
          )}
        </>
      )}
      <label>
        Jóváhagyott tételek érvényessége
        <select
          aria-label="Jóváhagyott tételek érvényessége"
          value={valid}
          onChange={(e) => {
            V(e.target.value);
            C(null);
            H([]);
          }}
        >
          <option value="">Mind</option>
          <option value="true">Érvényes</option>
          <option value="false">Érvénytelen</option>
        </select>
      </label>
      <ul>
        {items.data?.items.map((i) => (
          <li key={i.product_id}>
            Termék {i.product_id} · {i.valid ? "Érvényes" : "Érvénytelen"} ·
            Rögzített revízió: {i.product_revision}; aktuális:{" "}
            {i.current_revision} · {i.invalid_reason || ""}
          </li>
        ))}
      </ul>
      <button
        disabled={!history.length || items.loading}
        onClick={() => {
          C(history.at(-1) ?? null);
          H(history.slice(0, -1));
        }}
      >
        Előző jóváhagyott tételek
      </button>
      <button
        disabled={!items.data?.next_cursor || items.loading}
        onClick={() => {
          H([...history, cursor]);
          C(items.data?.next_cursor ?? null);
        }}
      >
        Következő jóváhagyott tételek
      </button>
    </section>
  );
}
