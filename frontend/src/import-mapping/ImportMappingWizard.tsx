import { useEffect, useId, useRef, useState } from "react";
import { DonorSelection } from "./DonorSelection";
import {
  errorText,
  loadMapping,
  parameterHeader,
  saveMapping,
  validateMapping,
  type MappingInput,
  type MappingView,
  type ParameterDraft,
  type ParameterType,
  type Registry,
  type Request,
  type SavedMapping,
  type Target,
  type Validation,
} from "./importMappingApi";
import "./import-mapping.css";

type Choice = Target | { kind: "new"; draft: ParameterDraft };
type Run = {
  id: number;
  filename: string;
  state: string;
  config: Record<string, unknown>;
};

const types: Record<ParameterType, string> = {
  text: "Szöveg",
  num: "Szám",
  enum: "Lista",
  enummore: "Többértékű lista",
  link_text: "Hivatkozás",
};
const columnWarnings: Record<string, string> = {
  scientific_notation_identifier:
    "Tudományos jelölésű azonosító. Kérj teljes számjegysort a forrásból.",
  invalid_gtin_samples: "Érvénytelen EAN/GTIN található a mintákban.",
  negative_values: "Negatív érték található a mintákban.",
  duplicate_header: "Ez a fejléc több oszlopban is szerepel.",
};
const issueLabels: Record<string, string> = {
  duplicate_target: "Több oszlop ugyanahhoz a célmezőhöz tartozik.",
  unknown_target: "A kiválasztott célmező már nem érhető el.",
  parameter_not_approved: "A paraméter létrehozását jóvá kell hagyni.",
  invalid_parameter: "Hibás paraméternév, típus vagy mértékegység.",
  missing_columns: "Hiányzik egy forrásoszlop a megfeleltetésből.",
  identity_missing: "Rendelj hozzá nevet vagy azonosítót.",
  identity_target_not_mapped: "A kiválasztott kulcsmező nincs megfeleltetve.",
  identity_conflict: "Ugyanaz az azonosító eltérő sorokban szerepel.",
  financial_approval_required:
    "A pénzügyi megfeleltetés külön jóváhagyást igényel.",
  invalid_vat_rate: "Érvénytelen áfakulcs.",
  invalid_vat_rows: "Érvénytelen áfakulcs található a forrásban.",
  scientific_identifier_rows:
    "A tudományos jelölésű azonosítók teljes értéke nem állítható helyre.",
  invalid_gtin_rows: "Érvénytelen EAN/GTIN található a forrásban.",
};
const fallbackLabels: Record<string, string> = {
  default_1: "Alapértelmezett érték: 1",
  from_availability: "Pótlás a rendelhetőségből",
  net_from_gross_vat: "Számítás a bruttó árból és az ismert áfakulcsból",
  gross_from_net_vat: "Számítás a nettó árból és az ismert áfakulcsból",
};

const optionValue = (choice?: Choice) =>
  !choice
    ? ""
    : choice.kind === "field"
      ? `field:${choice.key}`
      : choice.kind === "parameter"
        ? `parameter:${choice.header}`
        : "new";
const identityValue = (target: Target) =>
  target.kind === "field" ? target.key : target.header;

function ValidationReport({
  report,
  view,
}: {
  report: Validation;
  view: MappingView;
}) {
  return (
    <div className="mapping-validation">
      <p role="status">
        {report.valid
          ? "A megfeleltetés menthető."
          : "A megfeleltetés javításra szorul."}
      </p>
      {[...report.errors, ...report.warnings].map((issue, index) => (
        <p
          key={index}
          role={index < report.errors.length ? "alert" : undefined}
        >
          {issueLabels[issue.code] ?? issue.code}
          {issue.columns?.length
            ? ` Oszlop: ${issue.columns.map((i) => view.columns.find((c) => c.index === i)?.header || i + 1).join(", ")}.`
            : ""}
          {issue.count !== undefined && ` Érintett: ${issue.count}.`}
          {issue.values?.length ? ` Példák: ${issue.values.join(", ")}.` : ""}
        </p>
      ))}
      <ul aria-label="Kötelező mezők ellenőrzése">
        {report.required.map((field) => (
          <li key={field.key}>
            <strong>{field.header}</strong>
            {" – "}
            {field.status === "mapped"
              ? "Megfeleltetve"
              : field.status === "fallback"
                ? (fallbackLabels[field.rule ?? ""] ?? "Pótolható")
                : `Hiányzik ${field.rows_missing} sorból`}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MappingForm<T extends Run>({
  api,
  run,
  registry,
  view,
  financialDefaults,
  onApproved,
}: {
  api: Request;
  run: T;
  registry: Registry;
  view: MappingView;
  financialDefaults: { currency: string; price_type: string };
  onApproved: (run: T) => void;
}) {
  const [choices, setChoices] = useState(
    () =>
      new Map<number, Choice>(
        view.columns.flatMap((column) =>
          column.current ? [[column.index, column.current]] : [],
        ),
      ),
  );
  const [name, setName] = useState("UNAS oszlopmegfeleltetés");
  const [identity, setIdentity] = useState("");
  const [financial, setFinancial] = useState(false);
  const [vat, setVat] = useState("");
  const [feed, setFeed] = useState("partial");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<{ key: string; report: Validation }>();
  const saved = useRef<{ key: string; profile: SavedMapping } | null>(null);
  const [savedForRun, setSavedForRun] = useState(false);
  const pending = useRef(false);
  const id = useId();
  const options = new Map<
    string,
    { label: string; target: Target; internal?: string | null }
  >();
  for (const field of registry.fields) {
    const target: Target =
      field.kind === "parameter"
        ? { kind: "parameter", header: field.header }
        : { kind: "field", key: field.key, header: field.header };
    options.set(optionValue(target), {
      label: field.label + (field.required ? " (kötelező)" : ""),
      target,
      internal: field.internal_field,
    });
  }
  for (const parameter of view.approved_parameters) {
    const target: Target = { kind: "parameter", header: parameter.header };
    if (!options.has(optionValue(target)))
      options.set(optionValue(target), {
        label: `Paraméter: ${parameter.name}`,
        target,
      });
  }
  const identities = [
    ...new Set([...choices.values()].map(optionValue)),
  ].flatMap((key) => {
    const option = options.get(key);
    return option?.internal &&
      ["sku", "gtin", "mpn", "model", "supplier_id"].includes(option.internal)
      ? [option]
      : [];
  });
  const effectiveIdentity =
    identities.find((item) => identityValue(item.target) === identity) ??
    identities.find((item) => item.internal === "sku") ??
    identities[0];
  const drafts = [...choices.values()].flatMap((choice) =>
    choice.kind === "new" ? [choice.draft] : [],
  );
  const invalidDraft = drafts.some(
    (draft) =>
      !draft.name.trim() ||
      draft.name.includes("|") ||
      draft.unit?.includes("|") ||
      !draft.approved,
  );
  const body: MappingInput = {
    engine_key: registry.engine_key,
    columns: view.columns.map(({ index }) => {
      const choice = choices.get(index);
      return {
        index,
        target:
          choice?.kind === "new"
            ? { kind: "parameter", header: parameterHeader(choice.draft) }
            : choice
              ? (options.get(optionValue(choice))?.target ?? choice)
              : null,
      };
    }),
    new_parameters: drafts.map((draft) => ({
      ...draft,
      name: draft.name.trim(),
    })),
    identity_target: effectiveIdentity
      ? identityValue(effectiveIdentity.target)
      : null,
    financial_approved: financial,
    vat_rate: vat === "" ? null : Number(vat),
  };
  const key = JSON.stringify(body);
  const report = checked?.key === key ? checked.report : undefined;
  const saveKey = JSON.stringify([key, name.trim()]);
  const invalidTarget = [...choices.values()].some(
    (choice) => choice.kind !== "new" && !options.has(optionValue(choice)),
  );

  function choose(index: number, choice?: Choice) {
    setError("");
    setChoices((previous) => {
      const next = new Map(previous);
      if (choice) next.set(index, choice);
      else next.delete(index);
      return next;
    });
  }

  async function runAction(task: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  function validate() {
    if (invalidDraft || invalidTarget) return;
    setChecked(undefined);
    void runAction(async () =>
      setChecked({ key, report: await validateMapping(api, run.id, body) }),
    );
  }

  function approve() {
    if (!report?.valid || invalidDraft || invalidTarget || !name.trim()) return;
    void runAction(async () => {
      // A retry of /approve must reuse a profile successfully created by A5.
      const profile =
        saved.current?.key === saveKey
          ? saved.current.profile
          : await saveMapping(api, run.id, body, name.trim());
      saved.current = { key: saveKey, profile };
      setSavedForRun(true);
      const internalIdentity = body.columns.find(
        ({ target }) =>
          target && identityValue(target) === body.identity_target,
      );
      const approved = await api<T>(`/imports/runs/${run.id}/approve`, "POST", {
        name: name.trim(),
        mapping: profile.import_mapping,
        engine_mapping_profile_id: profile.profile_id,
        identity_field: internalIdentity
          ? (profile.import_mapping[String(internalIdentity.index)] ?? null)
          : null,
        financial_approved: financial,
        feed_type: feed,
        ...profile.approval_defaults,
        ...(financial && financialDefaults.currency
          ? { currency: financialDefaults.currency }
          : {}),
        ...(financial && financialDefaults.price_type
          ? { price_type: financialDefaults.price_type }
          : {}),
      });
      onApproved(approved);
    });
  }

  return (
    <>
      <p className="mapping-file">
        {view.rows.data_rows === null
          ? "A termékszám nem érhető el"
          : `${view.rows.data_rows.toLocaleString("hu-HU")} termék`}
        {" · "}
        {view.columns.length} forrásoszlop
      </p>
      <fieldset className="mapping-panel" disabled={busy}>
        <label className="mapping-engine">
          Webshopmotor
          <select value={registry.engine_key} disabled>
            <option value={registry.engine_key}>{registry.name}</option>
          </select>
        </label>
        {view.saved_profile && (
          <p>
            Korábbi megfeleltetés · {view.saved_profile.version}. verzió
            {view.saved_profile.requires_review &&
              " · Ellenőrizd a változásokat."}
            {view.saved_profile.new_headers.length > 0 &&
              ` Új oszlopok: ${view.saved_profile.new_headers.join(", ")}.`}
            {view.saved_profile.missing_headers.length > 0 &&
              ` Hiányzó oszlopok: ${view.saved_profile.missing_headers.join(", ")}.`}
          </p>
        )}
        <ul className="mapping-columns" aria-label="Forrásoszlopok">
          {view.columns.map((column) => {
            const choice = choices.get(column.index);
            const value = optionValue(choice);
            const suggestion = column.suggestion?.target;
            const suggestedOption =
              suggestion && suggestion.kind !== "new_parameter"
                ? options.get(optionValue(suggestion))
                : undefined;
            const caption =
              suggestion?.kind === "new_parameter"
                ? `Paraméter: ${suggestion.parameter.name}`
                : suggestedOption?.label;
            const label = column.header || "Névtelen oszlop";
            return (
              <li key={column.index} className="mapping-column">
                <div className="mapping-source">
                  <strong>
                    {column.index + 1}. {label}
                  </strong>
                  <ul aria-label="Forrásértékek">
                    {column.samples.length ? (
                      column.samples.map((value, index) => (
                        <li key={index}>{value}</li>
                      ))
                    ) : (
                      <li>Nincs mintaérték</li>
                    )}
                  </ul>
                  {column.warnings.map((warning) => (
                    <p key={warning}>{columnWarnings[warning] ?? warning}</p>
                  ))}
                </div>
                <div className="mapping-suggestion">
                  {caption && suggestion && column.suggestion ? (
                    <>
                      <span>
                        Javaslat: {caption} (
                        {Math.round(column.suggestion.confidence * 100)}%)
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          choose(
                            column.index,
                            suggestion.kind === "new_parameter"
                              ? {
                                  kind: "new",
                                  draft: {
                                    ...suggestion.parameter,
                                    approved: false,
                                  },
                                }
                              : suggestedOption?.target,
                          )
                        }
                      >
                        Javaslat átvétele
                      </button>
                    </>
                  ) : (
                    <span>Nincs javaslat</span>
                  )}
                </div>
                <div className="mapping-target">
                  <label>
                    Célmező
                    <select
                      aria-label={`Célmező: ${label}, ${column.index + 1}. oszlop`}
                      value={value}
                      onChange={(event) =>
                        choose(
                          column.index,
                          event.target.value === "new"
                            ? {
                                kind: "new",
                                draft: {
                                  name: "",
                                  param_type: "text",
                                  group_name: "",
                                  unit: null,
                                  approved: false,
                                },
                              }
                            : options.get(event.target.value)?.target,
                        )
                      }
                    >
                      <option value="">Eredeti oszlop megőrzése</option>
                      {value && value !== "new" && !options.has(value) && (
                        <option value={value} disabled>
                          Korábbi célmező · ellenőrizendő
                        </option>
                      )}
                      {[...options].map(([key, option]) => (
                        <option key={key} value={key}>
                          {option.label}
                        </option>
                      ))}
                      <option value="new">Új paraméter létrehozása</option>
                    </select>
                  </label>
                  {choice && choice === column.current && (
                    <small>Korábbi megfeleltetés</small>
                  )}
                  {choice?.kind === "new" && (
                    <ParameterEditor
                      draft={choice.draft}
                      onChange={(draft) =>
                        choose(column.index, { kind: "new", draft })
                      }
                    />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="mapping-options">
          <label>
            Profil neve
            <input
              value={name}
              maxLength={120}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Kulcsmező
            <select
              value={
                effectiveIdentity ? identityValue(effectiveIdentity.target) : ""
              }
              onChange={(event) => setIdentity(event.target.value)}
            >
              {!effectiveIdentity && (
                <option value="">Automatikus azonosítás</option>
              )}
              {identities.map((item) => (
                <option
                  key={identityValue(item.target)}
                  value={identityValue(item.target)}
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Feed típusa
            <select
              value={feed}
              onChange={(event) => setFeed(event.target.value)}
            >
              <option value="partial">Részlista</option>
              <option value="full">Teljes lista</option>
              <option value="price">Árfrissítés</option>
              <option value="stock">Készletfrissítés</option>
              <option value="technical">Műszaki frissítés</option>
            </select>
          </label>
          <label>
            Ismert egységes áfakulcs
            <select
              value={vat}
              onChange={(event) => setVat(event.target.value)}
            >
              <option value="">Nincs megadva</option>
              {[0, 5, 18, 27].map((rate) => (
                <option key={rate} value={rate}>
                  {rate}%
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="mapping-check" htmlFor={`${id}-financial`}>
          <input
            id={`${id}-financial`}
            type="checkbox"
            checked={financial}
            onChange={(event) => setFinancial(event.target.checked)}
          />
          Jóváhagyom a pénzügyi megfeleltetést
        </label>
        {invalidDraft && (
          <p>
            Adj érvényes nevet minden új paraméternek, és hagyd jóvá a
            létrehozását. A név és a mértékegység nem tartalmazhat | jelet.
          </p>
        )}
        {invalidTarget && (
          <p role="alert">Ellenőrizd a már nem elérhető korábbi célmezőket.</p>
        )}
        <button
          type="button"
          disabled={invalidDraft || invalidTarget}
          onClick={validate}
        >
          Megfeleltetés ellenőrzése
        </button>
        {report && <ValidationReport report={report} view={view} />}
        <button
          type="button"
          className="primary"
          disabled={
            !report?.valid || invalidDraft || invalidTarget || !name.trim()
          }
          onClick={approve}
        >
          {savedForRun && saved.current?.key === saveKey
            ? "Import jóváhagyásának újrapróbálása"
            : "Megfeleltetés jóváhagyása és mentése"}
        </button>
      </fieldset>
      {busy && <p role="status">Kérés feldolgozása…</p>}
      {error && <p role="alert">{error}</p>}
    </>
  );
}

function ParameterEditor({
  draft,
  onChange,
}: {
  draft: ParameterDraft;
  onChange: (draft: ParameterDraft) => void;
}) {
  const update = (fields: Partial<ParameterDraft>) =>
    onChange({ ...draft, ...fields, approved: false });
  return (
    <fieldset className="mapping-new">
      <legend>Új paraméter</legend>
      <label>
        Paraméternév
        <input
          value={draft.name}
          maxLength={120}
          onChange={(event) => update({ name: event.target.value })}
        />
      </label>
      <label>
        Típus
        <select
          value={draft.param_type}
          onChange={(event) =>
            update({ param_type: event.target.value as ParameterType })
          }
        >
          {Object.entries(types).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Mértékegység
        <input
          value={draft.unit ?? ""}
          maxLength={32}
          onChange={(event) => update({ unit: event.target.value || null })}
        />
      </label>
      <label className="mapping-check">
        <input
          type="checkbox"
          checked={draft.approved}
          disabled={!draft.name.trim()}
          onChange={(event) =>
            onChange({ ...draft, approved: event.target.checked })
          }
        />
        Jóváhagyom a paraméter létrehozását
      </label>
    </fieldset>
  );
}

export function ImportMappingWizard<T extends Run>({
  api,
  run,
  registry,
  canManage,
  financialDefaults,
  onApproved,
}: {
  api: Request;
  run: T;
  registry: Registry;
  canManage: boolean;
  financialDefaults: { currency: string; price_type: string };
  onApproved: (run: T) => void;
}) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [view, setView] = useState<MappingView>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [approvedLocally, setApprovedLocally] = useState(false);
  const linked =
    approvedLocally || typeof run.config.engine_mapping_profile_id === "number";
  const { id: runId } = run;
  const engine = registry.engine_key;

  useEffect(() => {
    if (linked) return;
    let active = true;
    loadMapping(api, runId, engine)
      .then((next) => {
        if (active) setView(next);
      })
      .catch((failure) => {
        if (active) setError(errorText(failure));
      });
    return () => {
      active = false;
    };
  }, [api, runId, engine, linked, retry]);

  return (
    <section className="mapping-wizard" aria-labelledby={id}>
      <ol className="mapping-steps" aria-label="Előkészítés lépései">
        <li aria-current={!linked ? "step" : undefined}>Oszlopmegfeleltetés</li>
        <li aria-current={linked ? "step" : undefined}>eMAG-paraméterek</li>
      </ol>
      <h3 id={id} ref={heading} tabIndex={-1}>
        {linked ? "Hiányzó eMAG-paraméterek" : "Oszlopmegfeleltetés"}
      </h3>
      {linked ? (
        <DonorSelection
          api={api}
          runId={run.id}
          state={run.state}
          canManage={canManage}
        />
      ) : view ? (
        <MappingForm
          api={api}
          run={run}
          registry={registry}
          view={view}
          financialDefaults={financialDefaults}
          onApproved={(next) => {
            setApprovedLocally(true);
            onApproved(next);
            requestAnimationFrame(() => heading.current?.focus());
          }}
        />
      ) : error ? (
        <>
          <p role="alert">{error}</p>
          <button
            type="button"
            onClick={() => {
              setError("");
              setRetry(retry + 1);
            }}
          >
            Újrapróbálás
          </button>
        </>
      ) : (
        <p role="status">Forrásoszlopok betöltése…</p>
      )}
    </section>
  );
}
