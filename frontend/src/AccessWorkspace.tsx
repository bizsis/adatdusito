import React, { useEffect, useState } from "react";
type Api = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Role = {
  id: number;
  owner: string;
  code: string;
  name: string;
  permissions: string[];
  protected: boolean;
};
type Permission = {
  code: string;
  label: string;
  level: string;
  delegatable: boolean;
  group: string;
};
type Person = {
  id: number;
  name: string;
  email: string;
  active: boolean;
  superadmin: boolean;
  membership_active?: boolean;
};
type Org = { id: number; name: string; company_id?: number; active?: boolean };
type UserState = {
  user: Person;
  roles: Role[];
  exceptions: { permission: string; allowed: boolean }[];
  tenant_mode: string;
  tenants: number[];
  tenant_choices?: { id: number; name: string }[];
  resource_mode: string;
  companies: number[];
  shops: number[];
  permissions: string[];
  sources: Record<
    string,
    { roles: string[]; exception?: string; scope?: string; allowed: boolean }
  >;
};
const selected = (list: number[], id: number, on: boolean) =>
  on ? [...new Set([...list, id])] : list.filter((x) => x !== id);
function Checks({
  label,
  items,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  items: { id: number; name: string }[];
  value: number[];
  onChange: (v: number[]) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset>
      <legend>{label}</legend>
      {items.map((x) => (
        <label key={x.id}>
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.includes(x.id)}
            onChange={(e) => onChange(selected(value, x.id, e.target.checked))}
          />
          {x.name}
        </label>
      ))}
    </fieldset>
  );
}
export function AccessWorkspace({
  api,
  tenantId,
  permissions,
  onRefresh,
  superadmin = false,
}: {
  api: Api;
  tenantId: number | null;
  permissions: string[];
  onRefresh: () => Promise<void>;
  superadmin?: boolean;
}) {
  const system = tenantId === null,
    can = (p: string) => permissions.includes(p),
    suffix = system ? "" : `?tenant_id=${tenantId}`;
  const userRead = system ? can("system.users.read") : can("members.read"),
    userWrite = system ? can("system.users.manage") : can("members.manage"),
    roleRead = system ? can("system.roles.read") : can("members.read"),
    roleWrite = system
      ? can("system.roles.manage")
      : can("members.roles.manage"),
    inviteWrite = system ? userWrite : can("members.invite");
  const [userRevision, UR] = useState(0);
  const [tab, T] = useState(userRead ? "users" : "roles"),
    [users, U] = useState<Person[]>([]),
    [q, Q] = useState(""),
    [page, PG] = useState(0),
    [roles, R] = useState<Role[]>([]),
    [catalog, C] = useState<Permission[]>([]),
    [companies, CO] = useState<Org[]>([]),
    [shops, SH] = useState<Org[]>([]),
    [tenants, TE] = useState<{ id: number; name: string }[]>([]),
    [tenantSearch, TS] = useState(""),
    [tenantPage, TP] = useState(0),
    [error, E] = useState(""),
    [notice, N] = useState(""),
    [busy, B] = useState(false),
    [user, US] = useState<UserState | null>(null),
    [editingRole, ER] = useState<Role | null>(null),
    [roleName, RN] = useState(""),
    [roleCode, RC] = useState(""),
    [rolePerms, RP] = useState<string[]>([]),
    [roleIds, RI] = useState<number[]>([]),
    [allow, AL] = useState<string[]>([]),
    [deny, DE] = useState<string[]>([]),
    [tenantMode, TM] = useState("none"),
    [tenantIds, TI] = useState<number[]>([]),
    [resourceMode, RM] = useState("all"),
    [companyIds, CI] = useState<number[]>([]),
    [shopIds, SI] = useState<number[]>([]),
    [email, EM] = useState(""),
    [invites, IN] = useState<
      {
        id: number;
        email: string;
        state: string;
        delivery: string;
        expires_at: string;
      }[]
    >([]),
    [companyName, CN] = useState(""),
    [shopName, SN] = useState(""),
    [parent, PA] = useState(""),
    [history, HI] = useState<
      { action: string; created_at: string; details: unknown }[]
    >([]);
  const act = async (fn: () => Promise<void>) => {
    E("");
    N("");
    B(true);
    try {
      await fn();
    } catch (e) {
      E(String(e));
      if (tab === "invites" && inviteWrite)
        try {
          IN(await api("/invitations" + suffix));
        } catch {}
    } finally {
      B(false);
    }
  };
  async function load() {
    if (roleRead) {
      R(await api("/access/roles" + suffix));
      C(await api("/access/catalog"));
    }
    if (!system) {
      if (can("companies.read")) CO(await api("/access/companies"));
      if (can("webshops.read")) SH(await api("/access/webshops"));
    }
    if (inviteWrite) IN(await api("/invitations" + suffix));
  }
  useEffect(() => {
    act(load);
  }, [tenantId]);
  useEffect(() => {
    if (!userRead) return;
    const timer = setTimeout(() => {
      api<{ items: Person[] }>(
        system
          ? q.length >= 3
            ? `/users?q=${encodeURIComponent(q)}&offset=${page * 25}`
            : `/access/system-users?q=${encodeURIComponent(q)}&offset=${page * 25}`
          : `/tenants/${tenantId}/members?q=${encodeURIComponent(q)}&offset=${page * 25}`,
      )
        .then((r) => U(r.items))
        .catch((e) => E(String(e)));
    }, 250);
    return () => clearTimeout(timer);
  }, [q, page, tenantId, userRevision]);
  useEffect(() => {
    if (!system) return;
    const timer = setTimeout(
      () =>
        api<{ items: { tenant_id: number; name: string }[] }>(
          `/access/workspaces?q=${encodeURIComponent(tenantSearch)}&offset=${tenantPage * 100}`,
        )
          .then((r) =>
            TE(r.items.map((x) => ({ id: x.tenant_id, name: x.name }))),
          )
          .catch((e) => E(String(e))),
      250,
    );
    return () => clearTimeout(timer);
  }, [tenantSearch, tenantPage]);
  function roleEdit(r: Role | null) {
    ER(r);
    RN(r?.name || "");
    RC(r?.code || "");
    RP(r?.permissions || []);
  }
  async function openUser(id: number) {
    const x = await api<UserState>(`/access/users/${id}` + suffix);
    US(x);
    RI(x.roles.map((r) => r.id));
    AL(x.exceptions.filter((e) => e.allowed).map((e) => e.permission));
    DE(x.exceptions.filter((e) => !e.allowed).map((e) => e.permission));
    TM(x.tenant_mode);
    TI(x.tenants);
    RM(x.resource_mode);
    CI(x.companies);
    SI(x.shops);
    HI(await api(`/access/history/${id}` + suffix));
  }
  const body = () => ({
    roles: roleIds,
    allow,
    deny,
    tenant_mode: tenantMode,
    tenants: tenantIds,
    resource_mode: resourceMode,
    companies: companyIds,
    shops: shopIds,
  });
  const canAssign = system ? userWrite : can("members.roles.manage");
  const groupName = (g: string) =>
    ({
      system: "Rendszeradminisztráció",
      tenants: "Ügyfelek",
      members: "Munkatársak",
      imports: "Import",
      exports: "Export",
      reference: "Referenciák",
      products: "Termékadatok",
      companies: "Cégek",
      webshops: "Webáruházak",
      audit: "Audit",
    })[g] || g;
  const roleOptions = roles
    .filter((r) => !r.protected)
    .map((r) => ({ id: r.id, name: r.name }));
  const scopeFields = (
    <>
      {system ? (
        <>
          <label>
            Ügyfélhozzáférés
            <select
              value={tenantMode}
              onChange={(e) => TM(e.target.value)}
              disabled={!userWrite || (system && !can("tenants.access.manage"))}
            >
              <option value="none">Kizárólag központi funkciók</option>
              <option value="all">Összes aktív ügyfél, a későbbiek is</option>
              <option value="selected">Csak kijelölt ügyfelek</option>
            </select>
          </label>
          {tenantMode === "selected" && (
            <>
              <label>
                Ügyfelek keresése
                <input
                  value={tenantSearch}
                  onChange={(e) => {
                    TS(e.target.value);
                    TP(0);
                  }}
                />
              </label>
              <Checks
                label="Engedélyezett ügyfelek"
                items={[
                  ...new Map(
                    [...tenants, ...(user?.tenant_choices || [])].map((t) => [
                      t.id,
                      t,
                    ]),
                  ).values(),
                ]}
                value={tenantIds}
                onChange={TI}
                disabled={
                  !userWrite || (system && !can("tenants.access.manage"))
                }
              />
              <button disabled={!tenantPage} onClick={() => TP(tenantPage - 1)}>
                Előző ügyfelek
              </button>
              <button
                disabled={tenants.length < 100}
                onClick={() => TP(tenantPage + 1)}
              >
                További ügyfelek
              </button>
              <p>Kijelölt ügyfelek száma: {tenantIds.length}</p>
            </>
          )}
        </>
      ) : (
        <>
          <label>
            Adathozzáférés
            <select
              value={resourceMode}
              onChange={(e) => RM(e.target.value)}
              disabled={!userWrite || (system && !can("tenants.access.manage"))}
            >
              <option value="all">
                Teljes ügyfél, később létrehozott erőforrásokkal
              </option>
              <option value="selected">Csak kijelölt cégek/webáruházak</option>
            </select>
          </label>
          {resourceMode === "selected" && (
            <>
              <Checks
                label="Kijelölt cégek"
                items={companies}
                value={companyIds}
                onChange={CI}
                disabled={
                  !userWrite || (system && !can("tenants.access.manage"))
                }
              />
              <Checks
                label="Kijelölt webáruházak"
                items={shops}
                value={shopIds}
                onChange={SI}
                disabled={
                  !userWrite || (system && !can("tenants.access.manage"))
                }
              />
              <p>
                Új cég és új webáruház nem adódik hozzá automatikusan. A régi,
                még be nem sorolt importadatokhoz teljes ügyfél-hozzáférés
                szükséges.
              </p>
            </>
          )}
        </>
      )}
    </>
  );
  const groups = [...new Set(catalog.map((p) => p.group))];
  return (
    <section className="card padded">
      <h2>{system ? "Rendszerhozzáférések" : "Munkatársak és hozzáférések"}</h2>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div>
        {[
          [userRead, "users", system ? "Rendszerfelhasználók" : "Munkatársak"],
          [roleRead, "roles", "Szerepkörök"],
          [inviteWrite, "invites", "Meghívások"],
          [roleRead, "catalog", "Jogosultsági katalógus"],
          [!system && can("companies.read"), "org", "Cégek és webáruházak"],
        ]
          .filter(([allowed]) => allowed)
          .map(([, k, label]) => (
            <button
              key={String(k)}
              onClick={() => {
                T(String(k));
                US(null);
                if (String(k) === "invites") {
                  RI([]);
                  AL([]);
                  DE([]);
                  TM("none");
                  TI([]);
                  RM("all");
                  CI([]);
                  SI([]);
                }
                E("");
              }}
            >
              {label}
            </button>
          ))}
      </div>
      {tab === "users" && (
        <>
          <label>
            {system
              ? "Név/e-mail keresése (3 karaktertől globális adminisztrátori keresés)"
              : "Munkatárs keresése név vagy e-mail alapján"}
            <input
              value={q}
              onChange={(e) => {
                Q(e.target.value);
                PG(0);
              }}
            />
          </label>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Név</th>
                  <th>E-mail</th>
                  <th>Állapot</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}</td>
                    <td>{u.email}</td>
                    <td>
                      {u.active && u.membership_active !== false
                        ? "Aktív"
                        : "Inaktív"}
                    </td>
                    <td>
                      <button onClick={() => act(() => openUser(u.id))}>
                        Hozzáférések: {u.name}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button disabled={!page} onClick={() => PG(page - 1)}>
            Előző oldal
          </button>
          <button disabled={users.length < 25} onClick={() => PG(page + 1)}>
            Következő oldal
          </button>
        </>
      )}
      {tab === "users" && user && (
        <section>
          <h3>
            {user.user.name} – {user.user.email}
          </h3>
          {user.user.superadmin ? (
            <p>
              Védett Superadmin: teljes hozzáférése nem gyengíthető ezzel az
              űrlappal.
            </p>
          ) : (
            <>
              <Checks
                label="Szerepkörök (több is választható)"
                items={roleOptions}
                value={roleIds}
                onChange={RI}
                disabled={!userWrite || !canAssign}
              />
              {scopeFields}
              <details>
                <summary>Egyedi engedélyek és tiltások</summary>
                {groups.map((g) => (
                  <fieldset key={g}>
                    <legend>{groupName(g)}</legend>
                    {catalog
                      .filter((p) => p.group === g && (system || p.delegatable))
                      .map((p) => (
                        <label key={p.code}>
                          {p.label}
                          <select
                            aria-label={`Kivétel: ${p.code}`}
                            disabled={!userWrite || !canAssign}
                            value={
                              deny.includes(p.code)
                                ? "deny"
                                : allow.includes(p.code)
                                  ? "allow"
                                  : "inherit"
                            }
                            onChange={(e) => {
                              AL(
                                allow
                                  .filter((x) => x !== p.code)
                                  .concat(
                                    e.target.value === "allow" ? [p.code] : [],
                                  ),
                              );
                              DE(
                                deny
                                  .filter((x) => x !== p.code)
                                  .concat(
                                    e.target.value === "deny" ? [p.code] : [],
                                  ),
                              );
                            }}
                          >
                            <option value="inherit">
                              Szerepkörből örökölt
                            </option>
                            <option value="allow">Egyedi engedélyezés</option>
                            <option value="deny">Egyedi tiltás</option>
                          </select>
                        </label>
                      ))}
                  </fieldset>
                ))}
              </details>
              {userWrite && (
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      if (!system && !canAssign)
                        await api(
                          `/access/users/${user.user.id}/resources` + suffix,
                          "PUT",
                          {
                            resource_mode: resourceMode,
                            companies: companyIds,
                            shops: shopIds,
                          },
                        );
                      else
                        await api(
                          `/access/users/${user.user.id}` + suffix,
                          "PUT",
                          body(),
                        );
                      await openUser(user.user.id);
                      await onRefresh();
                      N(
                        "Hozzáférések mentve; az új engedélyek azonnal érvényesek.",
                      );
                    })
                  }
                >
                  Hozzáférések mentése
                </button>
              )}
            </>
          )}
          <details open>
            <summary>Ténylegesen érvényes jogosultságok és forrásuk</summary>
            <ul>
              {Object.entries(user.sources).map(([code, s]) => (
                <li key={code}>
                  {catalog.find((p) => p.code === code)?.label || code}:{" "}
                  {s.allowed ? "Engedélyezett" : "Tiltott"} ·{" "}
                  {(s.roles || []).join(", ") || "Nincs szerepkörforrás"}
                  {s.scope &&
                    " · Erőforráskorlátozás: teljes ügyfél-hozzáférést igénylő, még be nem sorolt adatok"}
                  {s.exception &&
                    ` · Egyedi ${s.exception === "deny" ? "tiltás" : "engedély"}`}
                </li>
              ))}
            </ul>
          </details>
          {userWrite && (!user.user.superadmin || (system && superadmin)) && (
            <button
              disabled={busy}
              onClick={() =>
                act(async () => {
                  if (system)
                    await api(`/users/${user.user.id}`, "PATCH", {
                      active: !user.user.active,
                    });
                  else
                    await api(
                      `/tenants/${tenantId}/members/${user.user.id}`,
                      "PATCH",
                      { active: user.user.membership_active === false },
                    );
                  US(null);
                  await load();
                  U([]);
                  UR((x) => x + 1);
                  N(
                    system
                      ? "A fiók állapota módosult."
                      : "A tagság megszűnt; a globális fiók és más ügyfelek tagságai megmaradtak.",
                  );
                })
              }
            >
              {system
                ? user.user.active
                  ? "Fiók letiltása"
                  : "Fiók aktiválása"
                : user.user.membership_active === false
                  ? "Ügyféltagság visszaállítása"
                  : "Ügyféltagság megszüntetése"}
            </button>
          )}
          {system && superadmin && !user.user.superadmin && (
            <SystemResources api={api} userId={user.user.id} />
          )}
          {system && superadmin && userWrite && (
            <details>
              <summary>Védett Superadmin-műveletek</summary>
              <p>
                A Superadmin minden munkaterülethez és funkcióhoz hozzáfér. Az
                utolsó aktív Superadmin nem vonható vissza.
              </p>
              <button
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await api(`/users/${user.user.id}`, "PATCH", {
                      superadmin: !user.user.superadmin,
                    });
                    await openUser(user.user.id);
                    UR((x) => x + 1);
                    await onRefresh();
                    N("A védett rendszerszerep módosult.");
                  })
                }
              >
                {user.user.superadmin
                  ? "Védett Superadmin-hozzáférés visszavonása"
                  : "Védett Superadmin-hozzáférés megadása"}
              </button>
            </details>
          )}
          <h4>Jogosultsági előzmények</h4>
          <ul>
            {history.map((h, i) => (
              <li key={i}>
                {new Date(h.created_at).toLocaleString("hu-HU")} · {h.action}
                <details>
                  <summary>Változás</summary>
                  <pre>{JSON.stringify(h.details, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}
      {tab === "roles" && (
        <>
          <ul>
            {roles.map((r) => (
              <li key={r.id}>
                {r.name} ·{" "}
                {r.protected
                  ? "Védett"
                  : r.owner === "template"
                    ? "Beépített ügyfélszerepkör"
                    : "Egyedi szerepkör"}{" "}
                <button onClick={() => roleEdit(r)}>Megnyitás: {r.name}</button>
                {roleWrite && !r.protected && r.owner !== "template" && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      act(async () => {
                        await api(`/access/roles/${r.id}` + suffix, "DELETE");
                        await load();
                        roleEdit(null);
                      })
                    }
                  >
                    Szerepkör törlése
                  </button>
                )}
              </li>
            ))}
          </ul>
          {roleWrite && (
            <button onClick={() => roleEdit(null)}>Új szerepkör</button>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                const r = await api<Role>(
                  "/access/roles" +
                    (editingRole ? "/" + editingRole.id : "") +
                    suffix,
                  editingRole ? "PUT" : "POST",
                  { code: roleCode, name: roleName, permissions: rolePerms },
                );
                await load();
                roleEdit(r);
                await onRefresh();
                N("Szerepkör mentve.");
              });
            }}
          >
            <label>
              Szerepkör neve
              <input
                value={roleName}
                onChange={(e) => RN(e.target.value)}
                required
                disabled={!roleWrite || editingRole?.protected}
              />
            </label>
            <label>
              Szerepkör technikai kódja
              <input
                value={roleCode}
                onChange={(e) => RC(e.target.value)}
                required
                pattern="[a-z][a-z0-9_]{1,47}"
                disabled={!roleWrite || editingRole?.protected}
              />
            </label>
            {groups.map((g) => (
              <fieldset key={g}>
                <legend>{groupName(g)}</legend>
                {catalog
                  .filter((p) => p.group === g && (system || p.delegatable))
                  .map((p) => (
                    <label key={p.code}>
                      <input
                        type="checkbox"
                        disabled={!roleWrite || editingRole?.protected}
                        checked={rolePerms.includes(p.code)}
                        onChange={(e) =>
                          RP(
                            e.target.checked
                              ? [...rolePerms, p.code]
                              : rolePerms.filter((x) => x !== p.code),
                          )
                        }
                      />
                      {p.label}
                    </label>
                  ))}
              </fieldset>
            ))}
            {roleWrite && !editingRole?.protected && (
              <button disabled={busy}>Szerepkör mentése</button>
            )}
            <p>
              A beépített ügyfélszerepkör módosítása csak ebben az ügyfélben
              készít saját változatot.
            </p>
          </form>
        </>
      )}
      {tab === "catalog" && (
        <>
          <p>
            Csak megvalósított funkciókhoz tartozó jogosultságok. A tiltás
            elsőbbséget élvez.
          </p>
          {groups.map((g) => (
            <details key={g} open>
              <summary>{groupName(g)}</summary>
              <ul>
                {catalog
                  .filter((p) => p.group === g)
                  .map((p) => (
                    <li key={p.code}>
                      {p.label} ·{" "}
                      {p.level === "system"
                        ? "Rendszerszintű, ügyfélhez nem delegálható"
                        : "Ügyfélszintre delegálható"}
                      <small>{p.code}</small>
                    </li>
                  ))}
              </ul>
            </details>
          ))}
        </>
      )}
      {tab === "invites" && (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                await api("/invitations" + suffix, "POST", {
                  email,
                  ...body(),
                });
                EM("");
                await load();
                N(
                  "Meghívás elküldve. A meghívott saját maga hagyja jóvá a hozzáférést.",
                );
              });
            }}
          >
            <label>
              Meghívott e-mail-címe
              <input
                type="email"
                required
                value={email}
                onChange={(e) => EM(e.target.value)}
              />
            </label>
            <Checks
              label="Meghívás szerepkörei"
              items={roleOptions}
              value={roleIds}
              onChange={RI}
            />
            {scopeFields}
            <button disabled={busy}>Meghívás küldése</button>
            <p>
              Meglévő fióknál is a tulajdonos fogadja el az új tagságot. Más
              ügyfél tagságai nem jelennek meg.
            </p>
          </form>
          <ul>
            {invites.map((i) => (
              <li key={i.id}>
                {i.email} ·{" "}
                {{
                  pending: "Függőben",
                  accepted: "Elfogadva",
                  expired: "Lejárt",
                  revoked: "Visszavonva",
                }[i.state] || i.state}{" "}
                ·{" "}
                {i.delivery === "sent"
                  ? "E-mail elküldve"
                  : i.delivery === "failed"
                    ? "Küldési hiba"
                    : "Küldésre vár"}{" "}
                · {new Date(i.expires_at).toLocaleString("hu-HU")}
                {["pending", "expired"].includes(i.state) && (
                  <>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await api(`/invitations/${i.id}/resend`, "POST");
                          await load();
                          N("Új meghívó elküldve; a korábbi link érvénytelen.");
                        })
                      }
                    >
                      Újraküldés
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await api(`/invitations/${i.id}/revoke`, "POST");
                          await load();
                        })
                      }
                    >
                      Visszavonás
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {tab === "org" && (
        <>
          <h3>Cégek</h3>
          <ul>
            {companies.map((c) => (
              <li key={c.id}>{c.name}</li>
            ))}
          </ul>
          {can("companies.manage") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api("/access/companies", "POST", { name: companyName });
                  CN("");
                  await load();
                });
              }}
            >
              <label>
                Új cég neve
                <input
                  value={companyName}
                  onChange={(e) => CN(e.target.value)}
                  required
                />
              </label>
              <button disabled={busy}>Cég létrehozása</button>
            </form>
          )}
          <h3>Webáruházak</h3>
          <ul>
            {shops.map((s) => (
              <li key={s.id}>
                {s.name} ·{" "}
                {companies.find((c) => c.id === s.company_id)?.name ||
                  "Hozzárendelt cég"}
              </li>
            ))}
          </ul>
          {can("webshops.manage") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api("/access/webshops", "POST", {
                    name: shopName,
                    company_id: Number(parent),
                  });
                  SN("");
                  await load();
                });
              }}
            >
              <label>
                Cég
                <select
                  value={parent}
                  onChange={(e) => PA(e.target.value)}
                  required
                >
                  <option value="">Válassz céget</option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Új webáruház neve
                <input
                  value={shopName}
                  onChange={(e) => SN(e.target.value)}
                  required
                />
              </label>
              <button disabled={busy}>Webáruház létrehozása</button>
            </form>
          )}
          <p>
            Ez szervezeti nyilvántartás; webáruház-integráció és automatikus
            termékhozzárendelés nem történik.
          </p>
        </>
      )}
    </section>
  );
}

export function AcceptInvitation({
  api,
  token,
  signedIn,
  onLogin,
  onAccepted,
}: {
  api: Api;
  token: string;
  signedIn: boolean;
  onLogin: () => void;
  onAccepted: (requiresLogin: boolean, tenantId: number | null) => void;
}) {
  const [info, I] = useState<{
      email: string;
      workspace: string;
      existing_account: boolean;
    } | null>(null),
    [name, N] = useState(""),
    [password, P] = useState(""),
    [error, E] = useState(""),
    [busy, B] = useState(false),
    [done, D] = useState(false);
  const [result, RES] = useState<{
    login_required: boolean;
    tenant_id: number | null;
  }>({ login_required: true, tenant_id: null });
  useEffect(() => {
    api<typeof info>("/invitations/inspect", "POST", { token })
      .then(I)
      .catch((e) => E(String(e)));
  }, [token]);
  return (
    <main className="login-page">
      <section className="card padded">
        <h1>Adatdúsító – meghívás elfogadása</h1>
        {error && <p role="alert">{error}</p>}
        {info && (
          <>
            <p>
              {info.workspace} · {info.email}
            </p>
            {done ? (
              <>
                <p role="status">A meghívást elfogadtad. A tagság aktív.</p>
                <button
                  onClick={() =>
                    onAccepted(result.login_required, result.tenant_id)
                  }
                >
                  Tovább a bejelentkezéshez / munkaterülethez
                </button>
              </>
            ) : info.existing_account && !signedIn ? (
              <>
                <p>
                  A meglévő fiókoddal jelentkezz be; a jelszavad nem változik.
                </p>
                <button onClick={onLogin}>
                  Bejelentkezés a meglévő fiókkal
                </button>
              </>
            ) : (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  B(true);
                  E("");
                  try {
                    const accepted = await api<{
                      login_required: boolean;
                      tenant_id: number | null;
                    }>("/invitations/accept", "POST", {
                      token,
                      ...(!info.existing_account && { name, password }),
                    });
                    RES(accepted);
                    D(true);
                    P("");
                  } catch (e) {
                    E(String(e));
                  } finally {
                    B(false);
                  }
                }}
              >
                {!info.existing_account && (
                  <>
                    <label>
                      Neved
                      <input
                        value={name}
                        onChange={(e) => N(e.target.value)}
                        required
                        autoComplete="name"
                      />
                    </label>
                    <label>
                      Saját jelszó
                      <input
                        type="password"
                        value={password}
                        onChange={(e) => P(e.target.value)}
                        minLength={12}
                        maxLength={128}
                        required
                        autoComplete="new-password"
                      />
                    </label>
                  </>
                )}
                <button disabled={busy}>Meghívás elfogadása</button>
              </form>
            )}
          </>
        )}
      </section>
    </main>
  );
}

function SystemResources({ api, userId }: { api: Api; userId: number }) {
  const [q, Q] = useState(""),
    [options, O] = useState<{ tenant_id: number; name: string }[]>([]),
    [tenant, T] = useState(""),
    [mode, M] = useState("all"),
    [companies, C] = useState<number[]>([]),
    [shops, S] = useState<number[]>([]),
    [co, CO] = useState<Org[]>([]),
    [so, SO] = useState<Org[]>([]),
    [message, N] = useState(""),
    [loaded, L] = useState(false);
  useEffect(() => {
    const t = setTimeout(
      () =>
        api<{ items: typeof options }>(
          `/access/workspaces?q=${encodeURIComponent(q)}`,
        )
          .then((r) => O(r.items))
          .catch((e) => N(String(e))),
      250,
    );
    return () => clearTimeout(t);
  }, [q]);
  return (
    <details>
      <summary>Rendszerfelhasználó cég-/webáruház-hozzáférése</summary>
      <label>
        Ügyfél keresése erőforrás-kezeléshez
        <input value={q} onChange={(e) => Q(e.target.value)} />
      </label>
      <label>
        Erőforrások ügyfélmunkaterülete
        <select
          value={tenant}
          onChange={(e) => {
            T(e.target.value);
            L(false);
          }}
        >
          <option value="">Válassz ügyfelet</option>
          {options.map((o) => (
            <option key={o.tenant_id} value={o.tenant_id}>
              {o.name}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={!tenant}
        onClick={async () => {
          try {
            const r = await api<{
              mode: string;
              companies: number[];
              shops: number[];
              company_options: Org[];
              shop_options: Org[];
            }>(`/access/users/${userId}/resources?tenant_id=${tenant}`);
            M(r.mode);
            C(r.companies);
            S(r.shops);
            CO(r.company_options);
            SO(r.shop_options);
            L(true);
            N("");
          } catch (e) {
            N(String(e));
          }
        }}
      >
        Erőforrás-hozzáférés betöltése
      </button>
      {loaded && (
        <>
          <label>
            Rendszerfelhasználó erőforrásmódja
            <select value={mode} onChange={(e) => M(e.target.value)}>
              <option value="all">Teljes ügyfél</option>
              <option value="selected">Csak kijelölt erőforrások</option>
            </select>
          </label>
          {mode === "selected" && (
            <>
              <Checks
                label="Rendszerfelhasználó cégei"
                items={co}
                value={companies}
                onChange={C}
              />
              <Checks
                label="Rendszerfelhasználó webáruházai"
                items={so}
                value={shops}
                onChange={S}
              />
            </>
          )}
          <button
            onClick={async () => {
              try {
                await api(
                  `/access/users/${userId}/resources?tenant_id=${tenant}`,
                  "PUT",
                  { resource_mode: mode, companies, shops },
                );
                N("Erőforrás-hozzáférés mentve.");
              } catch (e) {
                N(String(e));
              }
            }}
          >
            Rendszerfelhasználó erőforrásainak mentése
          </button>
        </>
      )}
      <p role="status">{message}</p>
    </details>
  );
}
