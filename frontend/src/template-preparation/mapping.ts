import { parameterHeader } from "../import-mapping/importMappingApi";
import type { Assignment, Field, Parameter, SourceColumn, Target } from "./api";

export type Assignments = Record<number, Assignment>;

export const normalized = (value: string) =>
  value.trim().normalize("NFC").toLocaleLowerCase("hu");
export const parameterName = (value: string) =>
  value
    .trim()
    .replace(/^(?:param[eé]ter\s*:\s*)+/iu, "")
    .trim();

export const parameterLabel = (name: string) =>
  `Paraméter: ${parameterName(name)}`;

export const displayHeader = (header: string) =>
  /^\s*param[eé]ter\s*:/iu.test(header)
    ? parameterLabel(header.split("|", 1)[0])
    : header;

export const parameterNameKey = (parameter: Parameter) =>
  JSON.stringify([
    normalized(parameter.group_name),
    normalized(parameterName(parameter.name)),
  ]);
export const firstInstance = (field: Field) =>
  field.min_instance ?? (field.key === "raktarkeszlet" ? 0 : 1);

export const lastInstance = (field: Field) => field.max_instance ?? 99;

export const slotId = (target: Target) =>
  JSON.stringify([
    target.key,
    target.instance ??
      (target.key === "alternativ_kategoria"
        ? 1
        : target.key === "raktarkeszlet"
          ? 0
          : null),
    target.parameter
      ? (target.header ?? parameterHeader(target.parameter))
      : null,
  ]);
export const bindings = (assignments: Assignments, target: Target) =>
  Object.entries(assignments)
    .flatMap(([index, choice]) =>
      choice.state === "mapped" && slotId(choice.target) === slotId(target)
        ? [{ index: Number(index), target: choice.target }]
        : [],
    )
    .sort(
      (a, b) =>
        (a.target.order ?? a.index + 1) - (b.target.order ?? b.index + 1),
    );

function reorder(assignments: Assignments, indices: number[]): Assignments {
  const next = { ...assignments };
  indices.forEach((index, position) => {
    next[index] = {
      state: "mapped",
      target: { key: "kep", order: position + 1 },
    };
  });
  return next;
}

export function assign(
  assignments: Assignments,
  index: number,
  choice: Assignment,
): Assignments {
  const next = { ...assignments, [index]: choice };
  const image = { key: "kep" };
  const priorImages = bindings(assignments, image).map((entry) => entry.index);
  if (choice.state === "mapped" && choice.target.key === "kep") {
    return reorder(
      next,
      priorImages.includes(index) ? priorImages : [...priorImages, index],
    );
  }
  if (choice.state === "mapped") {
    for (const previous of bindings(assignments, choice.target)) {
      if (previous.index !== index) next[previous.index] = { state: null };
    }
  }
  return reorder(
    next,
    priorImages.filter((entry) => entry !== index),
  );
}

export function replaceBinding(
  assignments: Assignments,
  from: number,
  to: number,
): Assignments {
  const source = assignments[from];
  if (from === to || source?.state !== "mapped") return assignments;
  const next = assign(assign(assignments, from, { state: null }), to, source);
  if (source.target.key !== "kep") return next;
  return reorder(
    next,
    bindings(assignments, { key: "kep" })
      .filter((entry) => entry.index !== to)
      .map((entry) => (entry.index === from ? to : entry.index)),
  );
}

export function moveImage(
  assignments: Assignments,
  index: number,
  direction: -1 | 1,
): Assignments {
  const ordered = bindings(assignments, { key: "kep" }).map(
    (entry) => entry.index,
  );
  const slot = ordered.indexOf(index);
  const next = slot + direction;
  if (slot < 0 || next < 0 || next >= ordered.length) return assignments;
  [ordered[slot], ordered[next]] = [ordered[next], ordered[slot]];
  return reorder(assignments, ordered);
}

export function initialAssignments(
  columns: SourceColumn[],
  fields: Field[],
): Assignments {
  const assignments: Assignments = {};
  const occupied = new Map<string, SourceColumn>();
  const nextInstance = new Map<string, number>();
  for (const column of columns) {
    const choice = column.assignment;
    // Only a stored operator decision can preselect "unused".
    if (choice?.state === "unused" && column.assignment_source === "template") {
      assignments[column.index] = choice;
    } else if (choice?.state === "mapped") {
      const field = fields.find((item) => item.key === choice.target.key);
      if (
        !field ||
        (column.assignment_source !== "template" &&
          (field.type === "price" ||
            (field.key === "parameter" &&
              !["approved_parameter", "source_parameter"].includes(
                column.suggestion?.method ?? "",
              ))))
      )
        continue;
      let target = choice.target;
      if (field.multiple === "instances" && field.key !== "parameter") {
        const next = nextInstance.get(field.key) ?? firstInstance(field);
        const instance = target.instance ?? next;
        if (instance < firstInstance(field) || instance > lastInstance(field))
          continue;
        nextInstance.set(field.key, Math.max(next, instance + 1));
        target = { ...target, instance };
      }
      if (field.multiple !== "ordered") {
        const slot = slotId(target);
        const previous = occupied.get(slot);
        if (previous) {
          // An explicit saved mapping takes precedence over an auto-suggestion.
          if (
            column.assignment_source !== "template" ||
            previous.assignment_source === "template"
          )
            continue;
          delete assignments[previous.index];
        }
        occupied.set(slot, column);
      }
      assignments[column.index] = { state: "mapped", target };
    }
  }
  return reorder(
    assignments,
    bindings(assignments, { key: "kep" }).map((entry) => entry.index),
  );
}
