import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";
import { parseParameterHeader } from "../import-mapping/importMappingApi";
import {
  message,
  saveTemplate,
  validateTemplate,
  type Assignment,
  type Catalog,
  type Defaults,
  type Issue,
  type Parameter,
  type Preparation,
  type Request,
  type Saved,
  type Target,
  type Validation,
} from "./api";
import {
  assign,
  bindings,
  initialAssignments,
  moveImage,
  parameterNameKey,
  replaceBinding,
  slotId,
} from "./mapping";

const dragType = "application/x-adatdusito-template-column";
const typeLabels = {
  text: "Szöveg",
  num: "Szám",
  enum: "Lista",
  enummore: "Többértékű lista",
  link_text: "Hivatkozás",
};
const issueLabels: Record<string, string> = {
  scientific_notation_identifier:
    "Tudományos jelölésű azonosító. A hiányzó számjegyek nem állíthatók helyre.",
  uncertain_excel_number:
    "Bizonytalan Excel-számformátum. Ellenőrizd az eredeti értéket.",
  invalid_gtin_samples: "A mintában érvénytelen EAN/GTIN szerepel.",
  duplicate_header: "Ez a fejléc többször szerepel a fájlban.",
  currency_mismatch:
    "A forrás pénzneme eltér a sablon pénznemétől. Az értékek átváltás nélkül maradnak meg.",
  price_missing: "Hiányzik az eladási ár. A sablon így is menthető.",
  price_rows_missing: "Egyes sorokban hiányzik az eladási ár.",
  purchase_price_as_sale_price:
    "Ez az oszlop beszerzési árnak tűnik. Ellenőrizd, hogy eladási árat tartalmaz.",
  invalid_vat_rows:
    "Érvénytelen ÁFA-érték. Ezeknél a soroknál az ár nem számítható ki.",
  scientific_identifier_rows: "Tudományos jelölésű azonosítót találtunk.",
  undecided_columns:
    "A hozzárendelés nélküli oszlopok eredeti forrásadatként megmaradnak.",
  missing_columns: "A fájl néhány oszlopa hiányzik a megfeleltetésből.",
  unknown_target: "Ismeretlen célmező.",
  duplicate_target: "Egy célmezőhöz több azonos hozzárendelés tartozik.",
  parameter_not_approved: "Fogadd el a paramétert a mentéshez.",
  invalid_parameter: "Ellenőrizd a paraméter nevét, típusát és mértékegységét.",
  cikkszam_required: "Rendelj forrásoszlopot a Cikkszám mezőhöz.",
  invalid_default: "Ellenőrizd a Státusz és az ÁFA alapértékét.",
  unsupported_currency: "A pénznem nem támogatott.",
  unsupported_engine: "A webshopmotor nem támogatott.",
};

type ParameterEdit = {
  parameter: Parameter;
  index?: number;
  previous?: Target;
};
const blankParameter: Parameter = {
  name: "",
  param_type: "text",
  group_name: "",
  unit: null,
};
const baseTarget = (key: string): Target =>
  key === "alternativ_kategoria"
    ? { key, instance: 1 }
    : key === "raktarkeszlet"
      ? { key, instance: 0 }
      : { key };

function dragPayload(event: DragEvent, index: number, binding: boolean) {
  event.dataTransfer.setData(dragType, JSON.stringify({ index, binding }));
  event.dataTransfer.effectAllowed = "move";
}

function readDrop(event: DragEvent) {
  event.preventDefault();
  try {
    const value = JSON.parse(event.dataTransfer.getData(dragType));
    if (Number.isInteger(value.index) && typeof value.binding === "boolean") {
      return value as { index: number; binding: boolean };
    }
  } catch {
    /* Unrelated drags are ignored. */
  }
}

function allowDrop(event: DragEvent) {
  if (event.dataTransfer.types.includes(dragType)) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }
}

function ParameterDialog({
  edit,
  view,
  onClose,
  onAccept,
}: {
  edit: ParameterEdit;
  view: Preparation;
  onClose: () => void;
  onAccept: (parameter: Parameter, index?: number) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState(edit.parameter);
  const [source, setSource] = useState(
    edit.index === undefined ? "" : String(edit.index),
  );
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const valid =
    draft.name.trim() &&
    ![draft.name, draft.group_name, draft.unit ?? ""].some((v) =>
      v.includes("|"),
    );
  return (
    <dialog
      ref={dialog}
      className="prep-dialog"
      aria-label="Paraméter szerkesztése"
      onClose={onClose}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (valid)
            onAccept(
              {
                ...draft,
                name: draft.name.trim(),
                unit: draft.unit?.trim() || null,
              },
              source === "" ? undefined : Number(source),
            );
        }}
      >
        <h3>{edit.previous ? "Paraméter módosítása" : "Új paraméter"}</h3>
        <label>
          Paraméter neve
          <input
            required
            maxLength={120}
            value={draft.name}
            onChange={(event) =>
              setDraft({ ...draft, name: event.target.value })
            }
          />
        </label>
        <label>
          Paraméter típusa
          <select
            aria-label="Paraméter típusa"
            value={draft.param_type}
            onChange={(event) =>
              setDraft({
                ...draft,
                param_type: event.target.value as Parameter["param_type"],
              })
            }
          >
            {Object.entries(typeLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Mértékegység
          <input
            maxLength={32}
            value={draft.unit ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, unit: event.target.value || null })
            }
          />
        </label>
        <label>
          Forrásoszlop
          <select
            aria-label="Forrásoszlop"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="">Később rendelem hozzá</option>
            {view.columns.map((column) => (
              <option key={column.index} value={column.index}>
                {column.index + 1}. {column.header || "Névtelen oszlop"}
              </option>
            ))}
          </select>
        </label>
        <div className="prep-actions">
          <button type="button" onClick={onClose}>
            Mégse
          </button>
          <button className="primary" disabled={!valid} type="submit">
            Paraméter elfogadása
          </button>
        </div>
      </form>
    </dialog>
  );
}

function DefaultField({
  field,
  label,
  value,
  onChange,
}: {
  field: keyof Defaults;
  label: string;
  value: string;
  onChange?: (value: string) => void;
}) {
  const name = `${label} alapértéke`;
  return (
    <label className="prep-default">
      {name}
      <select
        aria-label={name}
        value={value}
        disabled={!onChange}
        onChange={(event) => onChange?.(event.target.value)}
      >
        {(field === "statusz" ? ["1", "0"] : ["27", "18", "5", "0"]).map(
          (option) => (
            <option key={option} value={option}>
              {option}
              {field === "afa" ? "%" : ""}
            </option>
          ),
        )}
      </select>
    </label>
  );
}

export function EmptyTemplateTargets({
  catalog,
  defaults,
  onDefault,
}: {
  catalog: Catalog;
  defaults: Defaults;
  onDefault?: (field: keyof Defaults, value: string) => void;
}) {
  return (
    <section className="card padded prep-targets" aria-label="UNAS-célmezők">
      <h3>UNAS-célmezők</h3>
      <ul className="prep-list">
        {catalog.targets.map((field) => (
          <li className="prep-field" key={field.key}>
            <strong>
              {field.label}
              {field.required ? " *" : ""}
            </strong>
            {(field.key === "statusz" || field.key === "afa") && (
              <DefaultField
                field={field.key}
                label={field.label}
                value={defaults[field.key]}
                onChange={
                  onDefault
                    ? (value) => onDefault(field.key as keyof Defaults, value)
                    : undefined
                }
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TemplateEditor({
  api,
  catalog,
  view,
  initialDefaults,
  currency,
  canSave,
  sourceControls,
  currencyWarnings,
  currencyBusy,
  onSaved,
  onBusy,
}: {
  api: Request;
  catalog: Catalog;
  view: Preparation;
  initialDefaults: Defaults;
  currency: string;
  canSave: boolean;
  sourceControls: ReactNode;
  currencyWarnings: Issue[];
  currencyBusy: boolean;
  onSaved: (result: Saved) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [assignments, setAssignments] = useState(() =>
    initialAssignments(view.columns, catalog.targets),
  );
  const [defaults, setDefaults] = useState(initialDefaults);
  const [name, setName] = useState(view.template?.name ?? "");
  const [templateId, setTemplateId] = useState(view.template?.id);
  const [extraSlots, setExtraSlots] = useState<Target[]>([]);
  const [created, setCreated] = useState<Parameter[]>([]);
  const [editing, setEditing] = useState<ParameterEdit>();
  const [report, setReport] = useState<Validation>();
  const [saved, setSaved] = useState<Saved>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const editable = canSave && !busy && !saved;
  const sourceNames = new Map(
    view.columns.map((column) => [
      column.index,
      `${column.index + 1}. ${column.header || "Névtelen oszlop"}`,
    ]),
  );
  const dynamic = [
    ...extraSlots,
    ...Object.values(assignments).flatMap((choice) =>
      choice.state === "mapped" ? [choice.target] : [],
    ),
  ];
  const groups = catalog.targets.map((field) => {
    const base = baseTarget(field.key);
    const slots = new Map([[slotId(base), base]]);
    if (field.multiple === "instances")
      for (const target of dynamic) {
        if (target.key === field.key) slots.set(slotId(target), target);
      }
    return {
      field,
      slots: [...slots.values()].sort(
        (a, b) => (a.instance ?? 0) - (b.instance ?? 0),
      ),
    };
  });
  function targetLabel(target: Target) {
    const field = catalog.targets.find((item) => item.key === target.key);
    if (target.parameter) return `Paraméter: ${target.parameter.name}`;
    if (target.key === "raktarkeszlet")
      return `Raktárkészlet #${target.instance ?? 0}`;
    if (target.key === "alternativ_kategoria" && (target.instance ?? 1) > 1)
      return `Alternatív kategória ${target.instance}`;
    return field?.label ?? target.key;
  }
  const approvedTargets = useMemo(
    () =>
      view.approved_parameters.flatMap(({ header }) => {
        const parameter = parseParameterHeader(header);
        return parameter ? [{ key: "parameter", header, parameter }] : [];
      }),
    [view.approved_parameters],
  );
  const approvedById = new Map(
    approvedTargets.map((target) => [slotId(target), target]),
  );
  const options = groups.flatMap(({ slots }) =>
    slots.filter(
      (slot) =>
        (slot.key !== "parameter" || slot.parameter) &&
        !approvedById.has(slotId(slot)),
    ),
  );
  const optionMap = new Map(
    [...options, ...approvedTargets].map((target) => [slotId(target), target]),
  );
  const mapColumn = (index: number, choice: Assignment) => {
    if (!editable) return;
    setReport(undefined);
    setError("");
    setAssignments((previous) => assign(previous, index, choice));
  };

  function applySuggestion(index: number, target: Target) {
    const approved = approvedById.get(slotId(target));
    if (target.key === "parameter" && !approved) {
      setEditing({ parameter: target.parameter ?? blankParameter, index });
    } else {
      mapColumn(index, { state: "mapped", target: approved ?? target });
    }
  }

  function dropOnTarget(event: DragEvent, target: Target) {
    const payload = readDrop(event);
    if (!payload || !editable || !sourceNames.has(payload.index)) return;
    if (target.key === "parameter" && !target.parameter) {
      setEditing({
        parameter: view.columns.find((column) => column.index === payload.index)
          ?.suggestion?.target.parameter ?? {
          ...blankParameter,
          name:
            view.columns.find((column) => column.index === payload.index)
              ?.header ?? "",
        },
        index: payload.index,
      });
    } else mapColumn(payload.index, { state: "mapped", target });
  }

  function acceptParameter(parameter: Parameter, index?: number) {
    if (!editing) return;
    const previous = editing.previous;
    const oldId = previous ? slotId(previous) : undefined;
    let target: Target = { key: "parameter", parameter };
    if (previous && slotId({ ...previous, header: undefined }) === slotId(target))
      target = previous;
    const id = slotId(target);
    const existing = approvedById.get(id);
    if (
      !existing &&
      [...approvedTargets, ...dynamic].some(
        (slot) =>
          slot.parameter &&
          slotId(slot) !== oldId &&
          parameterNameKey(slot.parameter) === parameterNameKey(parameter),
      )
    ) {
      setError("Ezzel a névvel már van paraméter. Válaszd ki a meglévőt.");
      setEditing(undefined);
      return;
    }
    setReport(undefined);
    setError("");
    setExtraSlots((old) => [
      ...old.filter((slot) => slotId(slot) !== oldId && slotId(slot) !== id),
      existing ?? target,
    ]);
    setCreated((old) => [
      ...old.filter((item) => {
        const itemId = slotId({ key: "parameter", parameter: item });
        return itemId !== oldId && itemId !== id;
      }),
      ...(existing ? [] : [parameter]),
    ]);
    setAssignments((old) => {
      const assigned = previous ? bindings(old, previous) : [];
      let next = old;
      for (const item of assigned)
        next = assign(next, item.index, { state: null });
      return index === undefined
        ? next
        : assign(next, index, { state: "mapped", target: existing ?? target });
    });
    setEditing(undefined);
  }

  async function save() {
    if (pending.current || !editable || currencyBusy || !name.trim()) return;
    setError("");
    setReport(undefined);
    pending.current = true;
    setBusy(true);
    onBusy(true);
    const columns = view.columns.map(({ index }) => ({
      index,
      ...(assignments[index] ?? { state: null }),
    }));
    const used = new Set(
      columns.flatMap((column) =>
        column.state === "mapped" && column.target.parameter
          ? [slotId(column.target)]
          : [],
      ),
    );
    const body = {
      engine: catalog.engine.key,
      currency,
      columns,
      defaults,
      new_parameters: created
        .filter((parameter) =>
          used.has(slotId({ key: "parameter", parameter })),
        )
        .map((parameter) => ({ ...parameter, approved: true as const })),
    };
    try {
      const result = await validateTemplate(api, view.run_id, body);
      setReport(result);
      if (!result.valid) return;
      const response = await saveTemplate(
        api,
        view.run_id,
        name.trim(),
        body,
        templateId,
      );
      setSaved(response);
      setReport(response.validation);
      onSaved(response);
    } catch (failure) {
      setError(message(failure));
    } finally {
      pending.current = false;
      setBusy(false);
      onBusy(false);
    }
  }

  const renderIssue = (issue: Issue, key: number, blocking = false) => (
    <p key={key} role={blocking ? "alert" : undefined} className="prep-warning">
      {issueLabels[issue.code] ?? issue.code}
      {issue.columns?.length
        ? ` Oszlopok: ${issue.columns.map((index) => sourceNames.get(index) ?? index + 1).join(", ")}.`
        : ""}
      {issue.count !== undefined ? ` Érintett sorok: ${issue.count}.` : ""}
      {issue.values?.length ? ` ${issue.values.join(", ")}.` : ""}
    </p>
  );

  return (
    <>
      <div className="prep-columns">
        <section
          className="card padded prep-targets"
          aria-label="UNAS-célmezők"
        >
          <h3>UNAS-célmezők</h3>
          <p>
            Húzd ide a forrásoszlopot, vagy válassz célmezőt a jobb oldalon.
          </p>
          <ul className="prep-list">
            {groups.map(({ field, slots }) => (
              <li key={field.key}>
                {slots.map((target) => {
                  const linked = bindings(assignments, target);
                  const label = targetLabel(target);
                  return (
                    <div
                      className="prep-field"
                      key={slotId(target)}
                      data-target={target.key}
                      onDragOver={editable ? allowDrop : undefined}
                      onDrop={
                        editable
                          ? (event) => dropOnTarget(event, target)
                          : undefined
                      }
                    >
                      <div className="prep-field-title">
                        <strong>
                          {label}
                          {field.required ? " *" : ""}
                        </strong>
                        {target.parameter && editable && (
                          <button
                            type="button"
                            onClick={() =>
                              setEditing({
                                parameter: target.parameter!,
                                previous: target,
                                index: linked[0]?.index,
                              })
                            }
                          >
                            Szerkesztés
                          </button>
                        )}
                      </div>
                      {(field.key === "statusz" || field.key === "afa") && (
                        <DefaultField
                          field={field.key}
                          label={label}
                          value={defaults[field.key]}
                          onChange={
                            editable
                              ? (value) => {
                                  setReport(undefined);
                                  setDefaults({
                                    ...defaults,
                                    [field.key]: value,
                                  });
                                }
                              : undefined
                          }
                        />
                      )}
                      {linked.length ? (
                        <ol
                          className="prep-bindings"
                          aria-label={`${label} hozzárendelései`}
                        >
                          {linked.map(({ index }, position) => (
                            <li key={index}>
                              <span
                                className="prep-binding-handle"
                                draggable={editable}
                                onDragStart={(event) =>
                                  dragPayload(event, index, true)
                                }
                              >
                                {sourceNames.get(index)}
                              </span>
                              {editable && (
                                <div className="prep-actions">
                                  {target.key === "kep" && (
                                    <>
                                      <button
                                        type="button"
                                        aria-label={`${sourceNames.get(index)} előrébb`}
                                        disabled={position === 0}
                                        onClick={() => {
                                          setReport(undefined);
                                          setAssignments((old) =>
                                            moveImage(old, index, -1),
                                          );
                                        }}
                                      >
                                        ↑
                                      </button>
                                      <button
                                        type="button"
                                        aria-label={`${sourceNames.get(index)} hátrébb`}
                                        disabled={
                                          position === linked.length - 1
                                        }
                                        onClick={() =>
                                          setAssignments((old) =>
                                            moveImage(old, index, 1),
                                          )
                                        }
                                      >
                                        ↓
                                      </button>
                                    </>
                                  )}
                                  <button
                                    type="button"
                                    aria-label={`${sourceNames.get(index)} hozzárendelés törlése`}
                                    onClick={() =>
                                      mapColumn(index, { state: null })
                                    }
                                  >
                                    Törlés
                                  </button>
                                </div>
                              )}
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <small>Még nincs hozzárendelve</small>
                      )}
                    </div>
                  );
                })}
                {field.multiple === "instances" && editable && (
                  <button
                    className="prep-add"
                    type="button"
                    onClick={() => {
                      if (field.key === "parameter")
                        setEditing({ parameter: blankParameter });
                      else
                        setExtraSlots((old) => [
                          ...old,
                          {
                            key: field.key,
                            instance:
                              Math.max(
                                ...slots.map((slot) => slot.instance ?? 0),
                              ) + 1,
                          },
                        ]);
                    }}
                  >
                    +{" "}
                    {field.key === "raktarkeszlet"
                      ? "Raktárkészlet"
                      : field.label}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section
          className="card padded prep-sources"
          aria-label="Beszállítói fájl és forrásoszlopok"
        >
          {sourceControls}
          <h3>Forrásoszlopok</h3>
          <p>
            {view.file.data_rows === null
              ? "A termékszám nem áll rendelkezésre"
              : `${view.file.data_rows.toLocaleString("hu-HU")} termék`}
            {" · "}
            {view.columns.length} oszlop
          </p>
          {!view.file.source_available && (
            <p>A minták a korábbi fájlelemzésből származnak.</p>
          )}
          {view.template && (
            <div className="prep-match">
              <p>
                Felismert vagy betöltött sablon:{" "}
                <strong>
                  {view.template.name} · v{view.template.version}
                </strong>
              </p>
              {view.template.missing_headers.length > 0 && (
                <p>
                  Hiányzó oszlopok: {view.template.missing_headers.join(", ")}
                </p>
              )}
              {view.template.new_headers.length > 0 && (
                <p>Új oszlopok: {view.template.new_headers.join(", ")}</p>
              )}
            </div>
          )}
          {currencyWarnings.map((issue, index) => renderIssue(issue, index))}
          <ul className="prep-list" aria-label="Forrásoszlopok">
            {view.columns.map((column) => {
              const choice = assignments[column.index];
              const label = sourceNames.get(column.index);
              const suggestion = column.suggestion;
              return (
                <li
                  key={column.index}
                  className="prep-source"
                  onDragOver={editable ? allowDrop : undefined}
                  onDrop={
                    editable
                      ? (event) => {
                          const payload = readDrop(event);
                          if (
                            payload?.binding &&
                            sourceNames.has(payload.index)
                          ) {
                            setReport(undefined);
                            setAssignments((old) =>
                              replaceBinding(old, payload.index, column.index),
                            );
                          }
                        }
                      : undefined
                  }
                >
                  <div
                    draggable={editable}
                    onDragStart={(event) =>
                      dragPayload(event, column.index, false)
                    }
                    className="prep-source-handle"
                  >
                    <strong>{label}</strong>
                    <samp>{column.sample ?? "Üres oszlop"}</samp>
                    {column.status === "new" && (
                      <small className="prep-warning">Új oszlop</small>
                    )}
                  </div>
                  {column.warnings.map((code, index) =>
                    renderIssue({ code }, index),
                  )}
                  <label>
                    Célmező
                    <select
                      aria-label={`Célmező: ${label}`}
                      disabled={!editable}
                      value={
                        choice?.state === "mapped"
                          ? slotId(choice.target)
                          : choice?.state === "unused"
                            ? "unused"
                            : ""
                      }
                      onChange={(event) => {
                        const value = event.target.value;
                        if (value === "new")
                          setEditing({
                            parameter: blankParameter,
                            index: column.index,
                          });
                        else if (value === "unused")
                          mapColumn(column.index, { state: "unused" });
                        else if (optionMap.has(value))
                          mapColumn(column.index, {
                            state: "mapped",
                            target: optionMap.get(value)!,
                          });
                        else mapColumn(column.index, { state: null });
                      }}
                    >
                      <option value="">Nincs hozzárendelve</option>
                      <option value="unused">Nem használjuk</option>
                      {options.map((target) => (
                        <option key={slotId(target)} value={slotId(target)}>
                          {targetLabel(target)}
                        </option>
                      ))}
                      {approvedTargets.length > 0 && (
                        <optgroup label="Meglévő paraméterek">
                          {approvedTargets.map((target) => (
                            <option key={slotId(target)} value={slotId(target)}>
                              {[
                                targetLabel(target),
                                target.parameter.group_name,
                                typeLabels[target.parameter.param_type],
                                target.parameter.unit,
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      <option value="new">Új paraméter…</option>
                    </select>
                  </label>
                  {suggestion && !choice?.state && editable && (
                    <button
                      type="button"
                      onClick={() =>
                        applySuggestion(column.index, suggestion.target)
                      }
                    >
                      Javaslat átvétele: {targetLabel(suggestion.target)} (
                      {Math.round(suggestion.confidence * 100)}%)
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </div>
      <section className="card padded prep-save" aria-label="Sablon mentése">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            Sablon neve
            <input
              value={name}
              maxLength={120}
              required
              disabled={!editable}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {view.template && templateId && editable && (
            <button
              type="button"
              onClick={() => {
                setTemplateId(undefined);
                setName("");
              }}
            >
              Mentés új sablonként
            </button>
          )}
          {report?.errors.map((issue, index) =>
            renderIssue(issue, index, true),
          )}
          {report?.warnings.map((issue, index) => renderIssue(issue, index))}
          {report?.fields
            .filter((field) => field.status === "computed")
            .map((field) => (
              <p key={field.key}>
                {targetLabel({ key: field.key })}: ismert ÁFA alapján
                számítható.
              </p>
            ))}
          {error && <p role="alert">{error}</p>}
          {saved ? (
            <p role="status">
              Sablon mentve: {saved.name} · v{saved.version}
            </p>
          ) : canSave ? (
            <button
              className="primary"
              type="submit"
              disabled={!editable || currencyBusy || !name.trim()}
            >
              {busy ? "Mentés folyamatban…" : "Sablon mentése"}
            </button>
          ) : (
            <p>A sablon mentéséhez jóváhagyási jogosultság szükséges.</p>
          )}
        </form>
      </section>
      {editing && (
        <ParameterDialog
          edit={editing}
          view={view}
          onClose={() => setEditing(undefined)}
          onAccept={acceptParameter}
        />
      )}
    </>
  );
}
