import React, { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "../ui";
import {
  usePresentationRead,
  usePresentationSearch,
} from "../classification/usePresentationRead";
import { ParameterAction } from "./ParameterAction";
import { ParameterJobPanel } from "./ParameterJobPanel";
import { ParameterValues } from "./ParameterValues";
import {
  parameterLabels,
  type DiffPage,
  type ParameterFilters,
  type ParameterIntent,
  type ParameterJob,
  type ParameterRow,
  type ParameterSelection,
  type ParameterValue,
  type ParameterWorkspaceProps,
} from "./presentation";
import "./parameters.css";

export function ParameterWorkspace(props: ParameterWorkspaceProps) {
  return (
    <Workspace key={`${props.workspaceKey}:${props.product.key}`} {...props} />
  );
}
const initial: ParameterFilters = { search: "", status: "all", match: "all" };
function Value({ value }: { value: ParameterValue }) {
  return (
    <dl className="parameter-value">
      <div>
        <dt>Eredeti nyers érték</dt>
        <dd>
          {value.raw === null
            ? "Nincs forrásérték"
            : value.raw === ""
              ? "Üres forráscella"
              : `${value.raw} ${value.rawUnit || ""}`}
        </dd>
      </div>
      <div>
        <dt>Normalizált érték</dt>
        <dd>
          {value.normalized === null
            ? "Nincs normalizált érték"
            : `${value.normalized} ${value.unit || ""}`}
        </dd>
      </div>
      <div>
        <dt>Forrás</dt>
        <dd>{value.source}</dd>
      </div>
      {value.conversionNote && (
        <div>
          <dt>Alkalmazott konverziós szabály</dt>
          <dd>{value.conversionNote}</dd>
        </div>
      )}
    </dl>
  );
}
function validatePage(page: DiffPage) {
  if (
    !page ||
    !Array.isArray(page.rows) ||
    page.rows.length > 100 ||
    !Number.isSafeInteger(page.total) ||
    page.total < 0 ||
    (page.totalProducts !== null &&
      (!Number.isSafeInteger(page.totalProducts) || page.totalProducts < 0)) ||
    !Array.isArray(page.profiles) ||
    !page.preparation ||
    page.rows.some(
      (r) =>
        !r ||
        !Object.hasOwn(parameterLabels, r.status) ||
        !["confirmed", "ambiguous", "none"].includes(r.match) ||
        !Array.isArray(r.history),
    )
  )
    throw new Error("A paraméterlista válasza nem értelmezhető.");
  return page;
}
function Workspace({
  ports,
  access,
  product,
  workspaceKey,
  renderDetails,
  allowSourcePreparation = false,
  allowProfileChoice = true,
  preparationActionLabel,
}: ParameterWorkspaceProps) {
  const [filters, setFilters] = useState<ParameterFilters>(initial);
  const query = usePresentationSearch(filters.search);
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const [revision, setRevision] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void revision;
      return validatePage(
        await ports.read(
          product.key,
          { status: filters.status, match: filters.match, search: query },
          cursor,
          signal,
        ),
      );
    },
    [
      ports,
      product.key,
      filters.status,
      filters.match,
      query,
      cursor,
      revision,
    ],
  );
  const read = usePresentationRead(load);
  const [action, setAction] = useState<Omit<ParameterIntent, "reason"> | null>(
    null,
  );
  const [actionKey, setActionKey] = useState(0);
  const [selection, setSelection] = useState<ParameterSelection | null>(null);
  const [focused, setFocused] = useState<ParameterRow | null>(null);
  const [correction, setCorrection] = useState("");
  const [unit, setUnit] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [selecting, setSelecting] = useState(false);
  const [job, setJob] = useState<ParameterJob | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const writable = !!ports.preview && !!ports.apply;
  const page = read.data;
  const profile = page?.profiles.find((p) => p.key === page.activeProfileKey);
  const waiting = query !== filters.search || read.loading;
  function canDiscard() {
    const dirty =
      focused &&
      !focused.locked &&
      (correction !== (focused.correction ?? "") ||
        unit !== (focused.own?.value.unit || focused.donor?.unit || ""));
    return (
      !dirty ||
      window.confirm(
        "A kézi javítás még nincs mentve. Elveted a mentetlen javítást?",
      )
    );
  }
  function clear() {
    setAction(null);
    setSelection(null);
    setFocused(null);
    setError("");
    setMessage("");
    pending.current?.abort();
    setSelecting(false);
  }
  function filter(next: ParameterFilters) {
    if (!canDiscard()) return;
    clear();
    setFilters(next);
    setCursor(null);
    setHistory([]);
  }
  function refresh() {
    clear();
    setCursor(null);
    setHistory([]);
    setRevision((r) => r + 1);
  }
  function prepare(
    kind: ParameterIntent["action"],
    extra: Partial<ParameterIntent> = {},
  ) {
    if (!page || waiting) return;
    setActionKey((k) => k + 1);
    setAction({
      action: kind,
      productKey: product.key,
      context: page.context,
      ...extra,
    });
  }
  async function selectScope() {
    if (!ports.snapshot || selecting) return;
    pending.current?.abort();
    const c = new AbortController();
    pending.current = c;
    setSelecting(true);
    setError("");
    setAction(null);
    try {
      const snapshot = await ports.snapshot(product.key, c.signal);
      if (
        !snapshot ||
        !Number.isSafeInteger(snapshot.count) ||
        snapshot.count < 0 ||
        typeof snapshot.description !== "string"
      )
        throw new Error("A termékkör válasza nem értelmezhető.");
      if (!c.signal.aborted) setSelection(snapshot);
    } catch (e) {
      if (!c.signal.aborted)
        setError(
          e instanceof Error ? e.message : "A termékkör nem rögzíthető.",
        );
    } finally {
      if (!c.signal.aborted) setSelecting(false);
    }
  }
  const prepLabels = {
    unprepared: "Még nincs előkészítve",
    review: "Előkészítés ellenőrzést igényel",
    approved: "Paraméteres előkészítés jóváhagyva",
    stale: "Az előkészítési jóváhagyás elavult",
  };
  return (
    <div className="parameter-workspace" data-workspace={workspaceKey}>
      <Panel title="Paraméter-összehasonlítás">
        <h3>{product.title}</h3>
        <p>
          Saját kategória:{" "}
          <strong>{product.ownCategory || "Nincs saját kategória"}</strong>
        </p>
        <p>
          Belső kategória: {product.internalPath || "Nincs belső besorolás"}
        </p>
        <p className="notice">
          Az eredeti beszállítói adatok megmaradnak. A biztos egyezések külön
          jelöltek; a bizonytalan megfeleltetéseket felülvizsgálhatod. A hiányzó
          hely elfogadása nem tölti ki az értéket.
        </p>
        {message && <p role="status">{message}</p>}
        {(error || read.error) && <p role="alert">{error || read.error}</p>}
        {read.error && (
          <button onClick={refresh}>Paraméterlista újratöltése</button>
        )}
        <div className="filters">
          <label>
            Paraméter keresése
            <input
              value={filters.search}
              onChange={(e) => filter({ ...filters, search: e.target.value })}
            />
          </label>
          <label>
            Paraméter állapota
            <select
              aria-label="Paraméter állapota"
              value={filters.status}
              onChange={(e) =>
                filter({
                  ...filters,
                  status: e.target.value as ParameterFilters["status"],
                })
              }
            >
              <option value="all">Minden állapot</option>
              {Object.entries(parameterLabels).map(([key, title]) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Egyezés jellege
            <select
              aria-label="Egyezés jellege"
              value={filters.match}
              onChange={(e) =>
                filter({
                  ...filters,
                  match: e.target.value as ParameterFilters["match"],
                })
              }
            >
              <option value="all">Minden egyezés</option>
              <option value="confirmed">Biztos egyezés</option>
              <option value="ambiguous">Bizonytalan egyezés</option>
              <option value="none">Nincs egyezés</option>
            </select>
          </label>
        </div>
        {waiting && <p role="status">Paraméterek betöltése…</p>}
        {page && (
          <>
            <p>
              Paramétertalálatok: {page.total.toLocaleString("hu-HU")} · Teljes
              tárolt termékállomány:{" "}
              {page.totalProducts === null
                ? "Nincs összesített adat"
                : page.totalProducts.toLocaleString("hu-HU")}
            </p>
            <p className="small muted">{page.versionLabel}</p>
            <details>
              <summary>Paraméterforrás és donorprofilok</summary>
              <p>
                {profile
                  ? `${profile.title} · ${profile.path}`
                  : "Paraméterforrás nem egyértelmű; a saját adatok továbbra is elérhetők."}
              </p>
              {profile?.review === "pending_review" && (
                <p className="notice">
                  A donor felülvizsgálatra vár. Automatikus paraméterkitöltésre
                  nem használható.
                </p>
              )}
              <p>
                A kategóriabesorolás és a donor későbbi dúsítási jóváhagyása
                külön döntés. A profilválasztás nem ír át forrásértéket.
              </p>
              {page.profiles.map((p) => (
                <div key={p.key}>
                  <span>
                    {p.title} · {p.path} ·{" "}
                    {p.review === "approved"
                      ? "Ellenőrzött profil"
                      : "Felülvizsgálandó profil"}
                  </span>
                  {access.edit && writable && allowProfileChoice && (
                    <button
                      disabled={waiting}
                      onClick={() =>
                        prepare("select_profile", { profileKey: p.key })
                      }
                      aria-label={`Donorprofil felülvizsgálata: ${p.title}`}
                    >
                      Profilválasztás előnézete
                    </button>
                  )}
                </div>
              ))}
            </details>
            <div className="actions">
              {access.edit &&
                writable &&
                (profile?.review === "approved" || allowSourcePreparation) && (
                  <button
                    disabled={waiting}
                    onClick={() => prepare("add_missing")}
                  >
                    {preparationActionLabel || "Hiányzó üres helyek előnézete"}
                  </button>
                )}
              {access.bulk && writable && ports.snapshot && (
                <button disabled={waiting || selecting} onClick={selectScope}>
                  Termékkör rögzítése tömeges előnézethez
                </button>
              )}
              {selection && (
                <>
                  <span>
                    Rögzített termékkör:{" "}
                    {selection.count.toLocaleString("hu-HU")} ·{" "}
                    {selection.description}
                  </span>
                  {profile?.review === "approved" && (
                    <button
                      disabled={waiting}
                      onClick={() => prepare("add_missing", { selection })}
                    >
                      Tömeges paraméter-előnézet
                    </button>
                  )}
                </>
              )}
            </div>
            {!page.rows.length && (
              <p>
                Nincs a szűrésnek megfelelő paraméter. Ez nem jelent jóváhagyott
                előkészítést.
              </p>
            )}
            <div className="table-wrap">
              <table className="parameter-table">
                <thead>
                  <tr>
                    <th>Állapot és egyezés</th>
                    <th>Saját / beszállítói paraméter</th>
                    <th>Donorparaméter</th>
                    <th>Megőrzés és javítás</th>
                    <th>Művelet</th>
                  </tr>
                </thead>
                <tbody>
                  {page.rows.map((r) => (
                    <tr key={r.key}>
                      <td data-label="Állapot és egyezés">
                        <span
                          className={`badge parameter-status-${r.status} ${r.status === "present" ? "good" : ""}`}
                        >
                          {parameterLabels[r.status]}
                        </span>
                        <p>
                          {r.match === "confirmed"
                            ? "Biztos egyezés"
                            : r.match === "ambiguous"
                              ? "Bizonytalan egyezés – jóváhagyásra vár"
                              : "Nincs egyezés – a mezők külön maradnak"}
                        </p>
                        <p>{r.explanation}</p>
                      </td>
                      <td data-label="Saját / beszállítói paraméter">
                        {r.own ? (
                          <>
                            <strong>{r.own.title}</strong>
                            <small>
                              Saját kulcs: {r.own.key} ·{" "}
                              {r.own.required === null
                                ? "Saját profil kötelezősége nem ismert"
                                : r.own.required
                                  ? "Saját profil szerint kötelező"
                                  : "Saját profil szerint opcionális"}
                            </small>
                            <Value value={r.own.value} />
                          </>
                        ) : (
                          <p>Hiányzó saját paraméterhely – még nincs érték.</p>
                        )}
                        {r.additionalSources?.map((source) => (
                          <section
                            key={source.key}
                            aria-label={`További forrás: ${source.title}`}
                          >
                            <h4>{source.title}</h4>
                            <Value value={source.value} />
                          </section>
                        ))}
                      </td>
                      <td data-label="Donorparaméter">
                        {r.donor ? (
                          <>
                            <strong>{r.donor.title}</strong>
                            <small>
                              Paraméter: {r.donor.key} · Típus: {r.donor.type} ·
                              Egység: {r.donor.unit || "Nincs megadva"}
                            </small>
                            <p>
                              {r.donor.required
                                ? "Donor szerint kötelező"
                                : "Donor szerint opcionális"}
                            </p>
                            {r.donor.constraint && (
                              <p className="notice">
                                Kategóriamegkötés: {r.donor.constraint}
                              </p>
                            )}
                          </>
                        ) : (
                          <p>Nincs donor-megfelelés; a saját érték megmarad.</p>
                        )}
                      </td>
                      <td data-label="Megőrzés és javítás">
                        {r.storedValue !== undefined && (
                          <p>
                            Tárolt helyérték:{" "}
                            {r.storedValue ?? "Nincs tárolt érték"}{" "}
                            {r.storedUnit || ""} · {r.storedOrigin || ""}
                          </p>
                        )}
                        <p>
                          Javított érték: {r.correction ?? "Nincs kézi javítás"}
                        </p>
                        {r.locked && (
                          <p className="notice">Kézi paraméterjavítás védett</p>
                        )}
                        {r.aliasSuggestion && (
                          <p>Javasolt alias: {r.aliasSuggestion}</p>
                        )}
                        <details>
                          <summary>Paraméter változástörténete</summary>
                          {r.history.length ? (
                            <ul>
                              {r.history.map((h, i) => (
                                <li key={i}>
                                  {h.when} · {h.actor} · {h.reason}:{" "}
                                  {h.before || "–"} → {h.after || "–"}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p>Nincs visszakapott változásbejegyzés.</p>
                          )}
                        </details>
                      </td>
                      <td data-label="Művelet">
                        <button
                          disabled={waiting}
                          onClick={() => {
                            if (!canDiscard()) return;
                            setFocused(r);
                            setAction(null);
                            setCorrection(r.correction ?? "");
                            setUnit(r.own?.value.unit || r.donor?.unit || "");
                          }}
                          aria-label={`Paraméterrészlet: ${r.own?.title || r.donor?.title || r.key}`}
                        >
                          Részletek
                        </button>
                        {r.match === "ambiguous" &&
                          access.approve &&
                          writable && (
                            <button
                              disabled={waiting || r.locked}
                              onClick={() =>
                                prepare("approve_alias", { rowKey: r.key })
                              }
                              aria-label={`Alias felülvizsgálata: ${r.key}`}
                            >
                              Alias előnézete
                            </button>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <section aria-label="Paraméteres előkészítés jóváhagyása">
              <h3>
                {page.preparation.heading || prepLabels[page.preparation.state]}
              </h3>
              <p>{page.preparation.explanation}</p>
              <p>{page.preparation.audit}</p>
              <p>
                A hiányzó érték nem azonos a hiányzó hellyel. A későbbi
                AI-dúsítás külön fázis; ezen a felületen nem indítható.
              </p>
              {access.approve &&
                writable &&
                page.preparation.canApprove &&
                profile?.review === "approved" && (
                  <button
                    disabled={waiting}
                    onClick={() => prepare("approve_preparation")}
                  >
                    Előkészítési jóváhagyás előnézete
                  </button>
                )}
            </section>
          </>
        )}
        <div className="pager">
          <button
            disabled={!history.length || waiting}
            onClick={() => {
              if (!canDiscard()) return;
              clear();
              setCursor(history.at(-1) ?? null);
              setHistory(history.slice(0, -1));
            }}
          >
            Előző paraméterek
          </button>
          <button
            disabled={!page?.next || waiting}
            onClick={() => {
              if (!canDiscard()) return;
              clear();
              setHistory([...history, cursor]);
              setCursor(page?.next || null);
            }}
          >
            Következő paraméterek
          </button>
        </div>
      </Panel>
      {focused && (
        <Panel
          title={`Paraméterrészlet: ${focused.own?.title || focused.donor?.title || focused.key}`}
        >
          {focused.own && <Value value={focused.own.value} />}
          {renderDetails?.(focused, refresh)}
          {focused.donor && ports.values && (
            <ParameterValues
              key={focused.key}
              rowKey={focused.key}
              read={ports.values}
            />
          )}
          {access.edit && focused.canEdit && writable && !focused.locked && (
            <>
              <label>
                Kézi javított érték
                <input
                  value={correction}
                  onChange={(e) => {
                    setCorrection(e.target.value);
                    setAction(null);
                  }}
                />
              </label>
              <label>
                Javítás egysége
                <input
                  value={unit}
                  onChange={(e) => {
                    setUnit(e.target.value);
                    setAction(null);
                  }}
                />
              </label>
              <button
                disabled={waiting || !correction.trim()}
                onClick={() =>
                  prepare("edit", { rowKey: focused.key, correction, unit })
                }
              >
                Kézi javítás előnézete
              </button>
            </>
          )}
          {focused.locked && access.unlock && writable && (
            <button
              disabled={waiting}
              onClick={() => prepare("unlock", { rowKey: focused.key })}
            >
              Védelem feloldásának előnézete
            </button>
          )}
          <button
            onClick={() => {
              if (!canDiscard()) return;
              setFocused(null);
              setAction(null);
            }}
          >
            Paraméterrészlet bezárása
          </button>
        </Panel>
      )}
      {action && (
        <ParameterAction
          key={actionKey}
          intent={action}
          ports={ports}
          onClose={() => setAction(null)}
          onRefresh={refresh}
          onApplied={(text, nextJob) => {
            refresh();
            setMessage(text);
            if (nextJob) setJob(nextJob);
          }}
        />
      )}
      {job && (
        <ParameterJobPanel
          key={job.key}
          initial={job}
          ports={ports}
          access={access}
        />
      )}
    </div>
  );
}
