import { useEffect, useRef, useState } from "react";
import {
  errorText,
  loadDiff,
  loadDonors,
  loadPrepared,
  saveSelection,
  type DonorCategories,
  type DonorDiff,
  type Request,
} from "./importMappingApi";

export function DonorSelection({
  api,
  runId,
  state,
  canManage,
}: {
  api: Request;
  runId: number;
  state: string;
  canManage: boolean;
}) {
  const [categories, setCategories] = useState<DonorCategories>();
  const [donor, setDonor] = useState<number>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const ready = state === "completed" || state === "partial";

  useEffect(() => {
    if (!ready) return;
    let active = true;
    loadDonors(api, runId)
      .then((value) => {
        if (!active) return;
        setCategories(value);
        setDonor((previous) => {
          if (value.donors.some((item) => item.emag_category_id === previous))
            return previous;
          if (
            value.reference_suggestions.some((item) =>
              item.emag_category_ids.includes(previous ?? 0),
            )
          )
            return previous;
          return value.donors.length === 1
            ? value.donors[0].emag_category_id
            : undefined;
        });
      })
      .catch((failure) => {
        if (active) setError(errorText(failure));
      });
    return () => {
      active = false;
    };
  }, [api, runId, ready, retry]);

  if (!ready)
    return (
      <p role="status">
        {["failed", "paused", "cancelled"].includes(state)
          ? "A donorparaméterek a sikeres import után érhetők el."
          : "Az import feldolgozása folyamatban van. A donorparaméterek ezután jelennek meg."}
      </p>
    );

  const donors = new Map(
    categories?.donors.map((item) => [
      item.emag_category_id,
      `${item.name ?? `eMAG #${item.emag_category_id}`} (${item.products} termék)`,
    ]),
  );
  for (const item of categories?.reference_suggestions ?? [])
    for (const id of item.emag_category_ids)
      if (!donors.has(id))
        donors.set(
          id,
          `${item.path.join(" / ")} · referenciajavaslat (#${id})`,
        );

  return (
    <>
      {categories && (
        <>
          {categories.source_categories.length > 0 && (
            <ul aria-label="Eredeti beszállítói kategóriák">
              {categories.source_categories.map((item) => (
                <li key={item.source_category_id}>
                  {item.path ?? "Ismeretlen kategória"} ({item.products} termék)
                </li>
              ))}
            </ul>
          )}
          {categories.products_without_source_category > 0 && (
            <p>
              {categories.products_without_source_category} termék
              forráskategória nélkül.
            </p>
          )}
          {donors.size ? (
            <label className="mapping-engine">
              eMAG-donor
              <select
                value={donor ?? ""}
                onChange={(event) =>
                  setDonor(Number(event.target.value) || undefined)
                }
              >
                <option value="">Válassz donorkategóriát</option>
                {[...donors].map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p>
              Ehhez az importhoz még nincs eMAG-donor. A termékbesorolás után
              frissítsd a listát.
            </p>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {!categories && !error && <p role="status">Donorok betöltése…</p>}
      {(categories || error) && (
        <button
          type="button"
          onClick={() => {
            setError("");
            setRetry(retry + 1);
          }}
        >
          Donorok frissítése
        </button>
      )}
      {donor && (
        <ParameterList
          key={donor}
          api={api}
          runId={runId}
          donor={donor}
          canManage={canManage}
        />
      )}
    </>
  );
}

function ParameterList({
  api,
  runId,
  donor,
  canManage,
}: {
  api: Request;
  runId: number;
  donor: number;
  canManage: boolean;
}) {
  const [diff, setDiff] = useState<DonorDiff>();
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const pending = useRef(false);
  useEffect(() => {
    let active = true;
    loadDiff(api, runId, donor)
      .then((value) => {
        if (active) setDiff(value);
      })
      .catch((failure) => {
        if (active) setError(errorText(failure));
      });
    return () => {
      active = false;
    };
  }, [api, runId, donor, retry]);

  async function update(mode: "set" | "all" | "none", ids?: number[]) {
    if (!canManage || pending.current) return;
    pending.current = true;
    setBusy(true);
    setStatus("");
    setError("");
    try {
      const next = await saveSelection(api, runId, donor, mode, ids);
      setDiff(next);
      setStatus("Kijelölés mentve.");
      try {
        const prepared = await loadPrepared(api, runId);
        const count = prepared.donor_parameters.filter(
          (item) => item.emag_category_id === donor,
        ).length;
        setStatus(
          `Kijelölés mentve. ${count} előkészített eMAG-mező ennél a donornál.`,
        );
      } catch (failure) {
        setError(
          `Az előkészített mezők összesítője nem tölthető be. ${errorText(failure)}`,
        );
      }
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  if (!diff)
    return error ? (
      <>
        <p role="alert">{error}</p>
        <button
          type="button"
          onClick={() => {
            setError("");
            setRetry(retry + 1);
          }}
        >
          Paraméterek újratöltése
        </button>
      </>
    ) : (
      <p role="status">Donorparaméterek betöltése…</p>
    );

  const selectedIds = diff.parameters
    .filter((item) => item.selected)
    .map((item) => item.emag_parameter_id);
  const priorIds = diff.parameters
    .filter(
      (item) =>
        item.status === "missing" &&
        diff.previous_selection?.includes(item.emag_parameter_id),
    )
    .map((item) => item.emag_parameter_id);

  return (
    <fieldset className="mapping-panel" disabled={busy}>
      <p role="status">
        {diff.selected} / {diff.missing} hiányzó kijelölve · {diff.covered} már
        szerepel
      </p>
      {!canManage && (
        <p>A kijelölés módosításához importkezelési jogosultság szükséges.</p>
      )}
      {canManage && diff.missing > 0 && (
        <div className="mapping-actions">
          <button type="button" onClick={() => void update("all")}>
            Összes kijelölése
          </button>
          <button type="button" onClick={() => void update("none")}>
            Kijelölés törlése
          </button>
          {priorIds.length > 0 && (
            <button type="button" onClick={() => void update("set", priorIds)}>
              Korábbi kijelölés átvétele
            </button>
          )}
        </div>
      )}
      {diff.parameters.length > 0 ? (
        <ul className="mapping-parameters" aria-label="Donorparaméterek">
          {diff.parameters.map((item) => (
            <li
              key={item.emag_parameter_id}
              className={
                item.status === "covered" ? "mapping-covered" : undefined
              }
            >
              <label>
                <input
                  type="checkbox"
                  checked={item.selected}
                  disabled={!canManage || item.status === "covered"}
                  onChange={(event) =>
                    void update(
                      "set",
                      event.target.checked
                        ? [...selectedIds, item.emag_parameter_id]
                        : selectedIds.filter(
                            (id) => id !== item.emag_parameter_id,
                          ),
                    )
                  }
                />
                <span>
                  {item.name}
                  {item.unit &&
                    !item.name.includes(item.unit) &&
                    ` (${item.unit})`}
                  {item.covered_by && (
                    <small>
                      Már szerepel az oszlopok között: {item.covered_by.header}
                    </small>
                  )}
                  {item.mandatory && (
                    <small>Kötelező a donor kategóriában</small>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : (
        <p>A donorhoz nem tartozik paraméter.</p>
      )}
      {busy && <p role="status">Kijelölés mentése…</p>}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </fieldset>
  );
}
