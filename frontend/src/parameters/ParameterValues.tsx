import React, { useCallback, useState } from "react";
import {
  usePresentationRead,
  usePresentationSearch,
} from "../classification/usePresentationRead";
import type { ParameterPorts } from "./presentation";
export function ParameterValues({
  rowKey,
  read,
}: {
  rowKey: string;
  read: NonNullable<ParameterPorts["values"]>;
}) {
  const [search, setSearch] = useState("");
  const query = usePresentationSearch(search);
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const load = useCallback(
    async (s: AbortSignal) => {
      const result = await read(rowKey, query, cursor, s);
      if (
        !result ||
        typeof result.hasList !== "boolean" ||
        !Array.isArray(result.items) ||
        result.items.length > 100 ||
        !result.items.every((v) => typeof v === "string") ||
        (!result.hasList && result.items.length > 0) ||
        !(result.next === null || typeof result.next === "string")
      )
        throw new Error("Az értéklista válasza nem értelmezhető.");
      return result;
    },
    [read, rowKey, query, cursor],
  );
  const result = usePresentationRead(load);
  return (
    <section aria-label="Megengedett paraméterértékek">
      <h4>Megengedett paraméterértékek</h4>
      <label>
        Megengedett érték keresése
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setCursor(null);
            setHistory([]);
          }}
        />
      </label>
      {result.loading && <p role="status">Értéklista betöltése…</p>}
      {result.error && (
        <p role="alert">Az értéklista nem tölthető be: {result.error}</p>
      )}
      {result.data &&
        (!result.data.hasList ? (
          <p>Ehhez a paraméterhez nincs megengedett értéklista.</p>
        ) : result.data.items.length ? (
          <ul>
            {result.data.items.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        ) : (
          <p>Nincs a keresésnek megfelelő megengedett érték.</p>
        ))}
      <div className="pager">
        <button
          disabled={!history.length || result.loading || query !== search}
          onClick={() => {
            setCursor(history.at(-1) ?? null);
            setHistory(history.slice(0, -1));
          }}
        >
          Előző értékek
        </button>
        <button
          disabled={!result.data?.next || result.loading || query !== search}
          onClick={() => {
            setHistory([...history, cursor]);
            setCursor(result.data?.next || null);
          }}
        >
          Következő értékek
        </button>
      </div>
    </section>
  );
}
