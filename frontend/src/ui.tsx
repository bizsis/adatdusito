import React, { useId } from "react";
import { CircleHelp, ShieldCheck, type LucideIcon } from "lucide-react";
import {
  helpText,
  type HelpKey,
  groupLabels,
  permissionDescriptions,
} from "./help";
export function Help({
  topic,
  label = "Súgó",
}: {
  topic: HelpKey;
  label?: string;
}) {
  const id = useId();
  return (
    <details
      className="help"
      onKeyDown={(e) => {
        if (e.key === "Escape") e.currentTarget.open = false;
      }}
    >
      <summary aria-label={label} aria-controls={id}>
        <CircleHelp size={16} />
      </summary>
      <span id={id} role="note" className="help-text">
        {helpText[topic]}
      </span>
    </details>
  );
}
export function FieldTitle({
  children,
  topic,
}: {
  children: React.ReactNode;
  topic?: HelpKey;
}) {
  return (
    <span className="field-title">
      {children}
      {topic && <Help topic={topic} />}
    </span>
  );
}
export function IconButton({
  icon: Icon,
  label,
  ...props
}: {
  icon: LucideIcon;
  label: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={label}
      title={label}
      {...props}
    >
      <Icon size={18} aria-hidden="true" />
    </button>
  );
}
export function Panel({
  title,
  help,
  children,
}: {
  title: string;
  help?: HelpKey;
  children: React.ReactNode;
}) {
  return (
    <section className="card padded">
      <h2 className="field-title">
        {title}
        {help && <Help topic={help} />}
      </h2>
      {children}
    </section>
  );
}
export type PermissionRow = {
  code: string;
  label: string;
  group: string;
  level: string;
  delegatable: boolean;
};
export function PermissionGrid({
  catalog,
  system = false,
  controlLabel = "Engedély",
  renderControl,
}: {
  catalog: PermissionRow[];
  system?: boolean;
  controlLabel?: string;
  renderControl: (p: PermissionRow, descriptionId: string) => React.ReactNode;
}) {
  const prefix = useId();
  return (
    <div className="permission-matrix">
      {[...new Set(catalog.map((p) => p.group))].map((g) => (
        <details key={g} open>
          <summary>{groupLabels[g] || g}</summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Jogosultság neve</th>
                  <th>{controlLabel}</th>
                  <th>Leírás</th>
                </tr>
              </thead>
              <tbody>
                {catalog
                  .filter((p) => p.group === g && (system || p.delegatable))
                  .map((p) => (
                    <tr key={p.code}>
                      <td>
                        {p.label}
                        {p.level === "system" && (
                          <span className="badge protected">
                            <ShieldCheck size={12} />
                            Rendszerszintű
                          </span>
                        )}
                        <details className="technical">
                          <summary>Technikai kód</summary>
                          <code>{p.code}</code>
                        </details>
                      </td>
                      <td>{renderControl(p, prefix + p.code)}</td>
                      <td id={prefix + p.code}>
                        {permissionDescriptions[p.code] ||
                          "A megnevezett funkció használata a kiosztott munkaterületi körben."}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </div>
  );
}
export function PermissionMatrix({
  catalog,
  value,
  onChange,
  disabled = false,
  system = false,
}: {
  catalog: PermissionRow[];
  value: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
  system?: boolean;
}) {
  return (
    <PermissionGrid
      catalog={catalog}
      system={system}
      renderControl={(p, id) => (
        <input
          aria-label={p.label}
          aria-describedby={id}
          type="checkbox"
          checked={value.includes(p.code)}
          disabled={disabled}
          onChange={(e) =>
            onChange(
              e.target.checked
                ? [...value, p.code]
                : value.filter((x) => x !== p.code),
            )
          }
        />
      )}
    />
  );
}
let displayTimezone = "Europe/Budapest";
export function setDisplayTimezone(timezone: string) {
  displayTimezone = timezone;
}
export function dateTime(value: string | null | undefined) {
  if (!value) return "–";
  const normalized = /[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : value + "Z";
  return new Date(normalized).toLocaleString("hu-HU", {
    timeZone: displayTimezone,
  });
}
