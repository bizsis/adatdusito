import { useId, useRef, useState } from "react";
import "./import-mapping.css";

// Presentation types only. The adapter maps the published backend contract to
// these props and owns persistence, validation of source data and donor lookup.
export type MappingChoice =
  | { kind: "keep" }
  | { kind: "field"; key: string }
  | { kind: "newParameter"; name: string };

export type MappingColumn = {
  id: string;
  name: string;
  samples: readonly string[];
  suggestion?: {
    choice: Exclude<MappingChoice, { kind: "keep" }>;
    confidence?: number;
  };
  savedChoice?: MappingChoice;
  warnings?: readonly string[];
};

export type MappingEngine = {
  id: string;
  name: string;
  fields: readonly { key: string; label: string; required: boolean }[];
  // Deterministic fallbacks already established by analysis, such as Státusz.
  providedFields?: Readonly<Record<string, string>>;
};

export type MissingParameter = {
  key: string;
  name: string;
  category?: string;
  required?: boolean;
};

export type MappingReview = {
  engineId: string;
  columns: readonly { columnId: string; choice: MappingChoice }[];
};

export type MissingReview = {
  donorLabels: readonly string[];
  parameters: readonly MissingParameter[];
  canProceed: boolean;
  message?: string;
};

export type ImportMappingWizardProps = {
  fileName: string;
  productCount: number;
  columns: readonly MappingColumn[];
  engines: readonly MappingEngine[];
  initialEngineId?: string;
  onApproveMapping: (review: MappingReview) => Promise<MissingReview>;
  onSelectParameters: (keys: readonly string[]) => Promise<void>;
};

const keep: MappingChoice = { kind: "keep" };
const targetValue = (choice: MappingChoice) =>
  choice.kind === "field" ? `field:${choice.key}` : choice.kind;
const normalize = (name: string) =>
  name.trim().normalize("NFC").toLocaleLowerCase("hu");

export function ImportMappingWizard({
  fileName,
  productCount,
  columns,
  engines,
  initialEngineId,
  onApproveMapping,
  onSelectParameters,
}: ImportMappingWizardProps) {
  const id = useId();
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const [engineId, setEngineId] = useState(
    initialEngineId ?? engines[0]?.id ?? "",
  );
  const [choices, setChoices] = useState(
    () =>
      new Map(
        columns.flatMap((column) =>
          column.savedChoice ? [[column.id, column.savedChoice] as const] : [],
        ),
      ),
  );
  const [review, setReview] = useState<MissingReview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [complete, setComplete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const engine = engines.find((entry) => entry.id === engineId);
  const decisions = columns.map((column) => ({
    columnId: column.id,
    choice: choices.get(column.id) ?? keep,
  }));
  const fields = decisions.flatMap(({ choice }) =>
    choice.kind === "field" ? [choice.key] : [],
  );
  const parameterNames = decisions.flatMap(({ choice }) =>
    choice.kind === "newParameter" ? [normalize(choice.name)] : [],
  );
  const missingFields =
    engine?.fields.filter(
      (field) =>
        field.required &&
        !fields.includes(field.key) &&
        !engine.providedFields?.[field.key],
    ) ?? [];
  const hasDuplicate =
    new Set(fields).size !== fields.length ||
    new Set(parameterNames).size !== parameterNames.length;
  const invalidField = fields.some(
    (key) => !engine?.fields.some((field) => field.key === key),
  );
  const parameters = [
    ...new Map(review?.parameters.map((item) => [item.key, item])).values(),
  ];
  const canApproveMapping = Boolean(
    engine &&
    columns.length &&
    !missingFields.length &&
    !hasDuplicate &&
    !parameterNames.includes("") &&
    !invalidField,
  );

  function choose(columnId: string, choice: MappingChoice) {
    setError("");
    setChoices((previous) => new Map(previous).set(columnId, choice));
  }

  function focusStep() {
    requestAnimationFrame(() => stepHeading.current?.focus());
  }

  async function approve() {
    if (busy || !canApproveMapping) return;
    setError("");
    setBusy(true);
    try {
      const result = await onApproveMapping({
        engineId,
        columns: decisions.map((decision) =>
          decision.choice.kind === "newParameter"
            ? {
                ...decision,
                choice: {
                  ...decision.choice,
                  name: decision.choice.name.trim(),
                },
              }
            : decision,
        ),
      });
      setReview(result);
      setSelected(new Set());
      focusStep();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "A jóváhagyás sikertelen.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (busy || !review?.canProceed) return;
    setError("");
    setBusy(true);
    try {
      await onSelectParameters(
        parameters
          .filter((item) => selected.has(item.key))
          .map((item) => item.key),
      );
      setComplete(true);
      focusStep();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "A kijelölés mentése sikertelen.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mapping-wizard" aria-labelledby={`${id}-step`}>
      <p className="mapping-file">
        <strong>{fileName}</strong> · {productCount.toLocaleString("hu-HU")}{" "}
        termék · {columns.length} forrásoszlop
      </p>
      <ol className="mapping-steps" aria-label="Előkészítés lépései">
        <li aria-current={!review ? "step" : undefined}>Oszlopmegfeleltetés</li>
        <li aria-current={review ? "step" : undefined}>eMAG-paraméterek</li>
      </ol>
      <h3 id={`${id}-step`} ref={stepHeading} tabIndex={-1}>
        {complete
          ? "Az előkészítés kész"
          : review
            ? "Hiányzó eMAG-paraméterek"
            : "Oszlopmegfeleltetés"}
      </h3>
      {!review && (
        <fieldset className="mapping-panel" disabled={busy}>
          <label className="mapping-engine">
            Webshopmotor
            <select
              value={engineId}
              onChange={(event) => {
                setEngineId(event.target.value);
                setChoices(new Map());
                setError("");
              }}
            >
              {!engine && <option value="">Válassz webshopmotort</option>}
              {engines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p>
            Válaszd ki a célmezőt, vagy tartsd meg az oszlopot eredeti mezőként.
            A javaslatokat egyenként veheted át.
          </p>
          <ul className="mapping-columns" aria-label="Forrásoszlopok">
            {columns.map((column, index) => {
              const choice = choices.get(column.id) ?? keep;
              const suggestion = column.suggestion;
              const suggestionChoice = suggestion?.choice;
              const suggestedField =
                suggestionChoice?.kind === "field"
                  ? engine?.fields.find(
                      (field) => field.key === suggestionChoice.key,
                    )
                  : undefined;
              const caption =
                suggestionChoice?.kind === "newParameter"
                  ? `Paraméter: ${suggestionChoice.name}`
                  : suggestedField?.label;
              const label = column.name || `Névtelen oszlop (${index + 1}.)`;
              const chosenField = choice.kind === "field" ? choice.key : null;
              return (
                <li key={column.id} className="mapping-column">
                  <div className="mapping-source">
                    <strong>
                      {index + 1}. {label}
                    </strong>
                    <ul aria-label="Forrásértékek">
                      {column.samples.length ? (
                        column.samples.map((sample, i) => (
                          <li key={i}>{sample || "Üres"}</li>
                        ))
                      ) : (
                        <li>Nincs mintaérték</li>
                      )}
                    </ul>
                    {column.warnings?.map((warning) => (
                      <p key={warning}>{warning}</p>
                    ))}
                  </div>
                  <div className="mapping-suggestion">
                    {caption && suggestion && suggestionChoice ? (
                      <>
                        <span>
                          Javaslat: {caption}
                          {suggestion.confidence !== undefined &&
                            ` (${Math.round(suggestion.confidence * 100)}%)`}
                        </span>
                        <button
                          type="button"
                          className="link"
                          onClick={() => choose(column.id, suggestionChoice)}
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
                        aria-label={`Célmező: ${label}, ${index + 1}. oszlop`}
                        value={targetValue(choice)}
                        onChange={(event) => {
                          const value = event.target.value;
                          choose(
                            column.id,
                            value === "keep"
                              ? keep
                              : value === "newParameter"
                                ? { kind: "newParameter", name: "" }
                                : {
                                    kind: "field",
                                    key: value.slice("field:".length),
                                  },
                          );
                        }}
                      >
                        <option value="keep">Eredeti oszlop megőrzése</option>
                        {chosenField &&
                          !engine?.fields.some(
                            (field) => field.key === chosenField,
                          ) && (
                            <option value={targetValue(choice)} disabled>
                              Korábbi célmező – ellenőrizendő
                            </option>
                          )}
                        {engine?.fields.map((field) => (
                          <option key={field.key} value={`field:${field.key}`}>
                            {field.label}
                            {field.required ? " (kötelező)" : ""}
                          </option>
                        ))}
                        <option value="newParameter">
                          Új paraméter létrehozása
                        </option>
                      </select>
                    </label>
                    {column.savedChoice === choice && (
                      <small>Korábbi megfeleltetés</small>
                    )}
                    {choice.kind === "newParameter" && (
                      <label>
                        Paraméternév
                        <input
                          value={choice.name}
                          maxLength={255}
                          onChange={(event) =>
                            choose(column.id, {
                              kind: "newParameter",
                              name: event.target.value,
                            })
                          }
                        />
                      </label>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          {engine &&
            Object.entries(engine.providedFields ?? {})
              .filter(([key]) => !fields.includes(key))
              .map(([key, note]) => (
                <p key={key}>
                  {engine.fields.find((field) => field.key === key)?.label ??
                    key}
                  : {note}
                </p>
              ))}
          {missingFields.length > 0 && (
            <p>
              Hiányzó kötelező mezők:{" "}
              {missingFields.map((field) => field.label).join(", ")}.
            </p>
          )}
          {hasDuplicate && (
            <p role="alert">
              Egy célmező vagy új paraméternév csak egyszer szerepelhet.
            </p>
          )}
          {invalidField && (
            <p role="alert">
              Ellenőrizd a már nem elérhető korábbi célmezőket.
            </p>
          )}
          {parameterNames.includes("") && (
            <p>Add meg minden új paraméter nevét.</p>
          )}
          <button
            type="button"
            className="primary"
            disabled={!canApproveMapping}
            onClick={() => void approve()}
          >
            {busy ? "Jóváhagyás folyamatban…" : "Megfeleltetés jóváhagyása"}
          </button>
        </fieldset>
      )}
      {review && !complete && (
        <fieldset className="mapping-panel" disabled={busy}>
          <p>
            {review.donorLabels.length
              ? `eMAG-donor: ${review.donorLabels.join(", ")}`
              : "Nincs elérhető eMAG-donor."}
          </p>
          <p>A beszállítói kategória és az eredeti értékek megmaradnak.</p>
          {review.message && <p>{review.message}</p>}
          {parameters.length > 0 ? (
            <>
              <div className="mapping-actions">
                <button
                  type="button"
                  onClick={() =>
                    setSelected(new Set(parameters.map((item) => item.key)))
                  }
                >
                  Összes kijelölése
                </button>
                <button type="button" onClick={() => setSelected(new Set())}>
                  Kijelölés törlése
                </button>
                <span role="status">
                  {selected.size} / {parameters.length} kijelölve
                </span>
              </div>
              <ul
                className="mapping-parameters"
                aria-label="Hiányzó paraméterek"
              >
                {parameters.map((item) => (
                  <li key={item.key}>
                    <label>
                      <input
                        type="checkbox"
                        checked={selected.has(item.key)}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setSelected((previous) => {
                            const next = new Set(previous);
                            if (checked) next.add(item.key);
                            else next.delete(item.key);
                            return next;
                          });
                        }}
                      />
                      <span>
                        {item.name}
                        {item.category && <small>{item.category}</small>}
                        {item.required && (
                          <small>Kötelező a donor kategóriában</small>
                        )}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>Nincs kiválasztható hiányzó paraméter.</p>
          )}
          <div className="mapping-actions">
            <button
              type="button"
              onClick={() => {
                setReview(null);
                setError("");
                focusStep();
              }}
            >
              Vissza a megfeleltetéshez
            </button>
            <button
              type="button"
              className="primary"
              disabled={!review.canProceed}
              onClick={() => void finish()}
            >
              {busy ? "Mentés…" : "Kijelölés mentése"}
            </button>
          </div>
        </fieldset>
      )}
      {complete && (
        <p role="status">
          {selected.size} hiányzó paraméter került az előkészítésbe.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
