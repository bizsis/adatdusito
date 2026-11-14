import React from "react";
import { PermissionGrid, type PermissionRow } from "./ui";
export function PermissionOverrides({
  catalog,
  allow,
  deny,
  onChange,
  disabled,
  system,
}: {
  catalog: PermissionRow[];
  allow: string[];
  deny: string[];
  onChange: (allow: string[], deny: string[]) => void;
  disabled: boolean;
  system: boolean;
}) {
  return (
    <PermissionGrid
      catalog={catalog}
      system={system}
      controlLabel="Beállítás"
      renderControl={(p, id) => (
        <select
          aria-label={`Kivétel: ${p.code}`}
          aria-describedby={id}
          disabled={disabled}
          value={
            deny.includes(p.code)
              ? "deny"
              : allow.includes(p.code)
                ? "allow"
                : "inherit"
          }
          onChange={(e) =>
            onChange(
              allow
                .filter((x) => x !== p.code)
                .concat(e.target.value === "allow" ? [p.code] : []),
              deny
                .filter((x) => x !== p.code)
                .concat(e.target.value === "deny" ? [p.code] : []),
            )
          }
        >
          <option value="inherit">Szerepkörből örökölt</option>
          <option value="allow">Egyedi engedélyezés</option>
          <option value="deny">Egyedi tiltás</option>
        </select>
      )}
    />
  );
}
