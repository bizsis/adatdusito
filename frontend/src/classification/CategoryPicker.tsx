import React, { useCallback, useState } from "react";
import type { Choice, PresentationPorts } from "./presentation";
import {
  usePresentationRead,
  usePresentationSearch,
} from "./usePresentationRead";

export function CategoryPicker({
  read,
  selected,
  onSelect,
}: {
  read: NonNullable<PresentationPorts["choices"]>;
  selected: Choice | null;
  onSelect: (choice: Choice) => void;
}) {
  const [search, setSearch] = useState("");
  const query = usePresentationSearch(search);
  const [parents, setParents] = useState<Choice[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const parent = parents.at(-1)?.key || null;
  const load = useCallback(
    (signal: AbortSignal) => read(query, parent, cursor, signal),
    [read, query, parent, cursor],
  );
  const result = usePresentationRead(load);
  function resetPage() {
    setCursor(null);
    setHistory([]);
  }
  return (
    <section
      className="classification-picker"
      aria-label="Jóváhagyott belső kategóriák"
    >
      <h3>Jóváhagyott belső kategóriák</h3>
      <label>
        Kategória keresése
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setParents([]);
            resetPage();
          }}
        />
      </label>
      {!!parents.length && (
        <p>
          {parents.map((p) => p.title).join(" / ")}{" "}
          <button
            onClick={() => {
              setParents(parents.slice(0, -1));
              resetPage();
            }}
          >
            Feljebb a kategóriákban
          </button>
        </p>
      )}
      {result.error && <p role="alert">{result.error}</p>}
      {result.loading && <p role="status">Kategóriák betöltése…</p>}
      {result.data && !result.data.items.length && (
        <p>Nincs találat. Próbálj másik kategórianevet.</p>
      )}
      <ul className="classification-choices">
        {result.data?.items.map((choice) => (
          <li key={choice.key}>
            <span>{choice.path.join(" / ") || choice.title}</span>
            <div className="actions">
              {choice.hasChildren && (
                <button
                  disabled={search !== query}
                  onClick={() => {
                    setParents([...parents, choice]);
                    setSearch("");
                    resetPage();
                  }}
                  aria-label={`${choice.title} alkategóriái`}
                >
                  Alkategóriák
                </button>
              )}
              {choice.selectable ? (
                <button
                  disabled={search !== query}
                  aria-pressed={selected?.key === choice.key}
                  onClick={() => onSelect(choice)}
                  aria-label={`Kiválasztás: ${choice.title}`}
                >
                  Kiválasztás
                </button>
              ) : (
                <span className="muted">Navigációs csoport</span>
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="pager">
        <button
          disabled={!history.length || result.loading}
          onClick={() => {
            setCursor(history.at(-1) ?? null);
            setHistory(history.slice(0, -1));
          }}
        >
          Előző kategóriák
        </button>
        <button
          disabled={!result.data?.next || result.loading}
          onClick={() => {
            setHistory([...history, cursor]);
            setCursor(result.data?.next || null);
          }}
        >
          Következő kategóriák
        </button>
      </div>
      {selected && (
        <p role="status">
          Kiválasztott belső kategória: {selected.path.join(" / ")}
        </p>
      )}
    </section>
  );
}
