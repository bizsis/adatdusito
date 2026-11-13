import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Role = "tenant_admin" | "processor" | "reviewer";
type User = {
  id: number;
  name: string;
  email: string;
  active: boolean;
  superadmin: boolean;
};
type Tenant = { id: number; name: string; active: boolean };
type Member = User & { role: Role; membership_active: boolean };
type Me = {
  user: User;
  tenant_id: number | null;
  role: string | null;
  permissions: string[];
  memberships: { tenant_id: number; name: string; role: string }[];
  csrf_token: string;
  expires_at: string;
};
type Page<T> = { items: T[]; total: number; offset: number; limit: number };
type NavLink = {
  id: string;
  name: string;
  kind: string;
  hierarchy_status: string;
  ancestors?: NavLink[];
  path?: NavLink[];
};
type NavCategory = NavLink & {
  source_item_id: string | null;
  source_department_id: string;
  url: string | null;
  children_count: number;
  mapping_status: string;
  canonical_emag_id: number | null;
  selectable: boolean;
  parameter_count: number | null;
  mandatory_parameter_count: number | null;
  optional_parameter_count: number | null;
  ancestors: NavLink[];
  path: NavLink[];
  related_links: (NavLink & { url: string | null })[];
};
type Parameter = {
  id: number;
  category_id: number;
  emag_parameter_id: number;
  name: string;
  type_id: number | null;
  display_order: number | null;
  is_mandatory: boolean | null;
  is_filter: boolean | null;
  allow_new_value: boolean | null;
  category_name?: string;
};
type Values = {
  parameter: Parameter;
  items: { id: number; value_text: string; value_order: number | null }[];
  next_cursor: number | null;
  has_more: boolean;
  limit: number;
};
const roleNames: Record<string, string> = {
  superadmin: "Superadmin",
  tenant_admin: "Ügyféladminisztrátor",
  processor: "Adatfeldolgozó",
  reviewer: "Ellenőrző",
};
let csrf = "";
async function api<T>(
  url: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + url, {
    method,
    credentials: "same-origin",
    signal,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401 && url !== "/auth/login")
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(data?.error?.message || "A művelet sikertelen.");
  }
  return data;
}
function useLoad<T>(url: string | null, revision = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    if (!url) return;
    setLoading(true);
    api<T>(url, "GET", undefined, controller.signal)
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [url, revision]);
  return { data, error, loading };
}
function useDebounce(value: string) {
  const [v, set] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => set(value), 300);
    return () => clearTimeout(id);
  }, [value]);
  return v;
}
function ErrorBox({ message }: { message: string }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}
function Empty({ loading = false }: { loading?: boolean }) {
  return (
    <p className="empty" role="status">
      {loading ? "Betöltés…" : "Nincs megjeleníthető adat."}
    </p>
  );
}
function Pager({
  offset,
  total,
  limit,
  onChange,
}: {
  offset: number;
  total: number;
  limit: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} / ${total}`
          : "0 találat"}
      </span>
      <button
        disabled={!offset}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Előző
      </button>
      <button
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Következő
      </button>
    </div>
  );
}
function RoleSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (s: Role) => void;
}) {
  return (
    <select
      aria-label="Szerepkör"
      value={value}
      onChange={(e) => onChange(e.target.value as Role)}
    >
      {(["tenant_admin", "processor", "reviewer"] as Role[]).map((r) => (
        <option key={r} value={r}>
          {roleNames[r]}
        </option>
      ))}
    </select>
  );
}
function Flag({ value }: { value: boolean | null }) {
  return (
    <span className={"badge " + (value ? "good" : "")}>
      {value === null ? "Nincs megadva" : value ? "Igen" : "Nem"}
    </span>
  );
}
function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
}) {
  const ref = React.useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} onCancel={close}>
      <header>
        <h2>{title}</h2>
        <button aria-label="Bezárás" onClick={close}>
          ×
        </button>
      </header>
      {children}
    </dialog>
  );
}

function Login({ onLogin }: { onLogin: () => Promise<void> }) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <section>
        <div className="brandmark">
          A<span>+</span>
        </div>
        <p className="eyebrow">PAKSI INFORMATIKA</p>
        <h1>Adatdúsító</h1>
        <p className="muted">Jelentkezz be a munkaterületedre.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            setBusy(true);
            setError("");
            try {
              const result = await api<{ csrf_token: string }>(
                "/auth/login",
                "POST",
                { email: fd.get("email"), password: fd.get("password") },
              );
              csrf = result.csrf_token;
              await onLogin();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Email-cím
            <input
              required
              name="email"
              type="email"
              autoComplete="username"
              maxLength={254}
            />
          </label>
          <label>
            Jelszó
            <input
              required
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={128}
            />
          </label>
          <ErrorBox message={error} />
          <button className="primary" disabled={busy}>
            {busy ? "Bejelentkezés…" : "Bejelentkezés →"}
          </button>
        </form>
        <p className="small muted">Fejlesztői adminisztrációs felület</p>
      </section>
      <aside>
        <span>
          RENDSZEREZETT ADATOK.
          <br />
          ÁTLÁTHATÓ MUNKA.
        </span>
        <p>
          Ügyfelek, felhasználók és kategória és termékparaméter
          referenciaadatok egy helyen.
        </p>
        <div className="orbit">→</div>
      </aside>
    </div>
  );
}
function UserForm({
  tenant,
  onDone,
  close,
}: {
  tenant?: number;
  onDone: () => void;
  close: () => void;
}) {
  const [role, setRole] = useState<Role>("processor"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <Modal
      title={tenant ? "Új ügyfélfelhasználó" : "Új felhasználó"}
      close={close}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          setBusy(true);
          setError("");
          try {
            await api(tenant ? `/tenants/${tenant}/users` : "/users", "POST", {
              name: fd.get("name"),
              email: fd.get("email"),
              password: fd.get("password"),
              ...(tenant
                ? { role }
                : { superadmin: fd.get("superadmin") === "on" }),
            });
            onDone();
            close();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Név
          <input name="name" required maxLength={120} />
        </label>
        <label>
          Email-cím
          <input name="email" type="email" required maxLength={254} />
        </label>
        <label>
          Kezdeti jelszó
          <input
            name="password"
            type="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
          <small>Legalább 12 karakter; biztonságos csatornán add át.</small>
        </label>
        {tenant ? (
          <label>
            Szerepkör
            <RoleSelect value={role} onChange={setRole} />
          </label>
        ) : (
          <label className="check">
            <input type="checkbox" name="superadmin" />
            Superadmin jogosultság
          </label>
        )}
        <ErrorBox message={error} />
        <button className="primary" disabled={busy}>
          Létrehozás
        </button>
      </form>
    </Modal>
  );
}
function UserEdit({
  user,
  onDone,
  close,
}: {
  user: User;
  onDone: () => void;
  close: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <Modal title="Felhasználó szerkesztése" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          setBusy(true);
          try {
            await api(`/users/${user.id}`, "PATCH", {
              name: fd.get("name"),
              active: fd.get("active") === "on",
              superadmin: fd.get("superadmin") === "on",
              ...(fd.get("password") ? { password: fd.get("password") } : {}),
            });
            onDone();
            close();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Név
          <input
            name="name"
            defaultValue={user.name}
            required
            maxLength={120}
          />
        </label>
        <p>{user.email}</p>
        <label className="check">
          <input name="active" type="checkbox" defaultChecked={user.active} />
          Aktív
        </label>
        <label className="check">
          <input
            name="superadmin"
            type="checkbox"
            defaultChecked={user.superadmin}
          />
          Superadmin
        </label>
        <label>
          Új jelszó (opcionális)
          <input
            name="password"
            type="password"
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
        </label>
        <p className="small muted">
          Jelszó- vagy jogosultságmódosításkor a munkamenetek visszavonásra
          kerülnek.
        </p>
        <ErrorBox message={error} />
        <button className="primary" disabled={busy}>
          Mentés
        </button>
      </form>
    </Modal>
  );
}
function Users() {
  const [offset, setOffset] = useState(0),
    [q, setQ] = useState(""),
    [rev, setRev] = useState(0),
    [creating, setCreating] = useState(false),
    [edit, setEdit] = useState<User | null>(null);
  const query = useDebounce(q);
  const { data, error, loading } = useLoad<Page<User>>(
    `/users?offset=${offset}&q=${encodeURIComponent(query)}`,
    rev,
  );
  return (
    <>
      <div className="sectionbar">
        <label className="search">
          Keresés
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            placeholder="Név vagy email-cím"
          />
        </label>
        <button className="primary" onClick={() => setCreating(true)}>
          + Új felhasználó
        </button>
      </div>
      <ErrorBox message={error} />
      <div className="card tablewrap">
        <table>
          <thead>
            <tr>
              <th>Felhasználó</th>
              <th>Jogosultság</th>
              <th>Állapot</th>
              <th>Művelet</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.name}</strong>
                  <small>
                    {u.email} · #{u.id}
                  </small>
                </td>
                <td>{u.superadmin ? "Superadmin" : "Ügyféltagság szerint"}</td>
                <td>
                  <Flag value={u.active} />
                </td>
                <td>
                  <button onClick={() => setEdit(u)}>Szerkesztés</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.items.length && <Empty loading={loading} />}
      </div>
      {data && <Pager {...data} onChange={setOffset} />}
      <p className="small muted">
        A felhasználókat az Ügyfelek oldalon rendelheted szervezethez.
      </p>
      {creating && (
        <UserForm
          close={() => setCreating(false)}
          onDone={() => setRev(rev + 1)}
        />
      )}{" "}
      {edit && (
        <UserEdit
          user={edit}
          close={() => setEdit(null)}
          onDone={() => setRev(rev + 1)}
        />
      )}
    </>
  );
}
function Members({ tenant, me }: { tenant: Tenant; me: Me }) {
  const [offset, setOffset] = useState(0),
    [rev, setRev] = useState(0),
    [creating, setCreating] = useState(false),
    [edit, setEdit] = useState<Member | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const result = useLoad<Page<Member>>(
    `/tenants/${tenant.id}/members?offset=${offset}`,
    rev,
  );
  async function update(u: Member, body: unknown) {
    setBusy(true);
    setError("");
    try {
      await api(`/tenants/${tenant.id}/members/${u.id}`, "PATCH", body);
      setRev(rev + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card padded">
      <div className="sectionbar">
        <h2>{tenant.name} · Felhasználók</h2>
        <button className="primary" onClick={() => setCreating(true)}>
          + Új felhasználó
        </button>
      </div>
      <ErrorBox message={error || result.error} />
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>Név</th>
              <th>Szerepkör</th>
              <th>Tagság</th>
              <th>Profil</th>
            </tr>
          </thead>
          <tbody>
            {result.data?.items.map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.name}</strong>
                  <small>{u.email}</small>
                </td>
                <td>
                  <RoleSelect
                    value={u.role}
                    onChange={(role) => {
                      if (!busy) void update(u, { role });
                    }}
                  />
                </td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void update(u, { active: !u.membership_active })
                    }
                  >
                    {u.membership_active
                      ? "Tagság felfüggesztése"
                      : "Tagság aktiválása"}
                  </button>
                  {!u.active && (
                    <small>A felhasználó globálisan inaktív.</small>
                  )}
                </td>
                <td>
                  <button onClick={() => setEdit(u)}>Szerkesztés</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!result.data?.items.length && <Empty loading={result.loading} />}{" "}
      {result.data && <Pager {...result.data} onChange={setOffset} />}
      {me.user.superadmin && (
        <form
          className="inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            setBusy(true);
            setError("");
            try {
              await api(`/tenants/${tenant.id}/members`, "POST", {
                user_id: Number(fd.get("user_id")),
                role: fd.get("role"),
              });
              setRev(rev + 1);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Meglévő felhasználó belső azonosítója
            <input
              type="number"
              name="user_id"
              min="1"
              required
              placeholder="A Felhasználók oldalon találod"
            />
          </label>
          <label>
            Szerepkör
            <select name="role">
              {Object.entries(roleNames)
                .filter(([key]) => key !== "superadmin")
                .map(([key, name]) => (
                  <option value={key} key={key}>
                    {name}
                  </option>
                ))}
            </select>
          </label>
          <button disabled={busy}>Hozzárendelés</button>
        </form>
      )}
      {edit && (
        <Modal
          title="Ügyfélfelhasználó szerkesztése"
          close={() => setEdit(null)}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              setError("");
              setBusy(true);
              try {
                await api(`/tenants/${tenant.id}/users/${edit.id}`, "PATCH", {
                  name: fd.get("name"),
                  ...(fd.get("password")
                    ? { password: fd.get("password") }
                    : {}),
                });
                setRev(rev + 1);
                setEdit(null);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Név
              <input
                required
                name="name"
                maxLength={120}
                defaultValue={edit.name}
              />
            </label>
            <label>
              Új jelszó (opcionális)
              <input
                name="password"
                type="password"
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
              />
            </label>
            <p className="small muted">
              Több ügyfélhez tartozó vagy Superadmin-fiókot csak Superadmin
              módosíthat. A saját jelszavadat a fejlécben módosíthatod.
            </p>
            <ErrorBox message={error} />
            <button className="primary" disabled={busy}>
              Mentés
            </button>
          </form>
        </Modal>
      )}
      {creating && (
        <UserForm
          tenant={tenant.id}
          close={() => setCreating(false)}
          onDone={() => setRev(rev + 1)}
        />
      )}
    </section>
  );
}
function Tenants({ me }: { me: Me }) {
  const [offset, setOffset] = useState(0),
    [rev, setRev] = useState(0),
    [selected, setSelected] = useState<Tenant | null>(null),
    [editing, setEditing] = useState<Tenant | true | null>(null),
    [error, setError] = useState("");
  const result = useLoad<Page<Tenant>>(`/tenants?offset=${offset}`, rev);
  const manage = me.user.superadmin || me.permissions.includes("tenant.manage");
  return (
    <>
      <div className="sectionbar">
        <p className="muted">
          {me.user.superadmin
            ? "Ügyfelek és szervezeti hozzáférések kezelése."
            : "A hozzád rendelt szervezetek."}
        </p>
        {me.user.superadmin && (
          <button className="primary" onClick={() => setEditing(true)}>
            + Új ügyfél
          </button>
        )}
      </div>
      <ErrorBox message={result.error} />
      <div className="tenant-grid">
        {result.data?.items.map((t) => (
          <article className="card tenant" key={t.id}>
            <div className="avatar">{t.name.slice(0, 2).toUpperCase()}</div>
            <h2>{t.name}</h2>
            <p className="small muted">
              Ügyfél #{t.id} · {t.active ? "Aktív" : "Felfüggesztett"}
            </p>
            {manage && (
              <div className="actions">
                <button onClick={() => setSelected(t)}>Felhasználók</button>
                <button
                  onClick={() => {
                    setEditing(t);
                    setError("");
                  }}
                >
                  Szerkesztés
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
      {!result.data?.items.length && <Empty loading={result.loading} />}{" "}
      {result.data && <Pager {...result.data} onChange={setOffset} />}{" "}
      {selected && manage && (
        <Members key={selected.id} tenant={selected} me={me} />
      )}{" "}
      {editing && (
        <Modal
          title={editing === true ? "Új ügyfél" : "Ügyfél szerkesztése"}
          close={() => setEditing(null)}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              try {
                await api(
                  editing === true ? "/tenants" : `/tenants/${editing.id}`,
                  editing === true ? "POST" : "PATCH",
                  {
                    name: fd.get("name"),
                    ...(editing !== true && me.user.superadmin
                      ? { active: fd.get("active") === "on" }
                      : {}),
                  },
                );
                setRev(rev + 1);
                setSelected(null);
                setEditing(null);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <label>
              Ügyfél neve
              <input
                name="name"
                required
                maxLength={120}
                defaultValue={editing === true ? "" : editing.name}
              />
            </label>
            {editing !== true && me.user.superadmin && (
              <label className="check">
                <input
                  type="checkbox"
                  name="active"
                  defaultChecked={editing.active}
                />
                Aktív ügyfél
              </label>
            )}
            <ErrorBox message={error} />
            <button className="primary">Mentés</button>
          </form>
        </Modal>
      )}
    </>
  );
}
function ValueBrowser({
  parameter,
  view = "navigation",
}: {
  parameter: Parameter;
  view?: string;
}) {
  const [q, setQ] = useState(""),
    [after, setAfter] = useState(0),
    [history, setHistory] = useState<number[]>([]);
  const query = useDebounce(q);
  const { data, error, loading } = useLoad<Values>(
    `/reference/parameters/${parameter.id}/values?after=${after}&q=${encodeURIComponent(query)}&view=${view}`,
  );
  return (
    <section className="card padded">
      <p className="eyebrow">MEGENGEDETT ÉRTÉKEK</p>
      <h2>{parameter.name}</h2>
      <p className="small muted">
        eMAG #{parameter.emag_parameter_id} · Belső paraméterazonosító #
        {parameter.id}
      </p>
      <div className="facts">
        <span>Típus: {parameter.type_id ?? "Nincs megadva"}</span>
        <span>
          Kötelező: <Flag value={parameter.is_mandatory} />
        </span>
        <span>
          Szűrő: <Flag value={parameter.is_filter} />
        </span>
        <span>
          Új érték: <Flag value={parameter.allow_new_value} />
        </span>
        <span>Sorrend: {parameter.display_order ?? "–"}</span>
      </div>
      <label>
        Keresés az értékekben
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setAfter(0);
            setHistory([]);
          }}
          placeholder="Érték keresése…"
        />
      </label>
      <ErrorBox message={error} />
      <ul className="value-list">
        {data?.items.map((v) => (
          <li key={v.id}>
            {v.value_text}
            <small>
              #{v.id}
              {v.value_order !== null ? ` · Sorrend: ${v.value_order}` : ""}
            </small>
          </li>
        ))}
      </ul>
      {!data?.items.length && <Empty loading={loading} />}
      <div className="pager">
        <span>Legfeljebb 50 érték oldalanként</span>
        <button
          disabled={!history.length || loading}
          onClick={() => {
            setAfter(history[history.length - 1]);
            setHistory(history.slice(0, -1));
          }}
        >
          Előző
        </button>
        <button
          disabled={!data?.has_more || loading}
          onClick={() => {
            if (data?.next_cursor) {
              setHistory([...history, after]);
              setAfter(data.next_cursor);
            }
          }}
        >
          Következő
        </button>
      </div>
    </section>
  );
}
function Parameters({
  categoryId,
  view = "navigation",
  navigationId,
}: {
  categoryId?: number;
  view?: string;
  navigationId?: string;
}) {
  const [q, setQ] = useState(""),
    [mandatory, setMandatory] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Parameter | null>(null);
  const query = useDebounce(q);
  const url = `${navigationId ? `/reference/navigation/${encodeURIComponent(navigationId)}/parameters` : "/reference/parameters"}?view=${view}&offset=${offset}&q=${encodeURIComponent(query)}${categoryId ? `&category_id=${categoryId}` : ""}${mandatory ? `&mandatory=${mandatory}` : ""}`;
  const { data, error, loading } = useLoad<Page<Parameter>>(url);
  return (
    <>
      <section className="card padded">
        <div className="sectionbar">
          <h2>{categoryId ? "Kategóriaparaméterek" : "Paraméterkereső"}</h2>
          <span className="badge">{data?.total ?? "…"} paraméter</span>
        </div>
        <div className="filters">
          <label>
            Paraméter neve vagy eMAG-azonosítója
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
                setSelected(null);
              }}
              placeholder="Keresés…"
            />
          </label>
          <label>
            Kötelezőség
            <select
              value={mandatory}
              onChange={(e) => {
                setMandatory(e.target.value);
                setOffset(0);
                setSelected(null);
              }}
            >
              <option value="">Összes</option>
              <option value="true">Kötelező</option>
              <option value="false">Opcionális</option>
            </select>
          </label>
        </div>
        <ErrorBox message={error} />
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Paraméter</th>
                <th>Típus</th>
                <th>Kötelező</th>
                <th>Értéklista</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.name}</strong>
                    <small>
                      eMAG #{p.emag_parameter_id} · Belső #{p.id}
                      {!categoryId && ` · ${p.category_name}`}
                    </small>
                  </td>
                  <td>{p.type_id ?? "–"}</td>
                  <td>
                    <Flag value={p.is_mandatory} />
                  </td>
                  <td>
                    <button onClick={() => setSelected(p)}>Megnyitás →</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data?.items.length && <Empty loading={loading} />}{" "}
        {data && <Pager {...data} onChange={setOffset} />}
      </section>
      {selected && (
        <ValueBrowser key={selected.id} parameter={selected} view={view} />
      )}
    </>
  );
}
function ShopNode({
  node,
  onSelect,
  selected,
  parents = [],
}: {
  node: NavCategory;
  onSelect: (n: NavLink) => void;
  selected?: string;
  parents?: string[];
}) {
  const [open, setOpen] = useState(false),
    [offset, setOffset] = useState(0);
  const result = useLoad<Page<NavCategory>>(
    open
      ? `/reference/navigation?parent_id=${encodeURIComponent(node.id)}&offset=${offset}`
      : null,
  );
  const cycle = parents.includes(node.id);
  return (
    <li>
      <div
        className={`tree-row ${selected === node.id ? "selected" : ""} ${!node.selectable ? "structural" : ""}`}
      >
        <button
          className="tree-toggle"
          aria-label={`${node.name} alkategóriái`}
          aria-expanded={open}
          disabled={cycle || !node.children_count}
          onClick={() => setOpen(!open)}
        >
          {open ? "−" : "+"}
        </button>
        <button
          className="tree-name"
          aria-current={selected === node.id ? "true" : undefined}
          onClick={() => onSelect(node)}
        >
          {node.name}
          <small>
            {node.kind === "department"
              ? "Főcsoport"
              : node.mapping_status === "confirmed"
                ? `Igazolt eMAG #${node.canonical_emag_id}`
                : "Marketplace-megfeleltetésre vár"}
            {node.hierarchy_status === "needs_review"
              ? " · Belső szekció ellenőrzendő"
              : ""}
          </small>
          {!!node.ancestors.length && (
            <small className="tree-path">
              {node.ancestors.map((p) => p.name).join(" / ")}
            </small>
          )}
        </button>
      </div>
      {open && !cycle && (
        <>
          <ErrorBox message={result.error} />
          {result.loading && <Empty loading />}
          <ul>
            {result.data?.items.map((n) => (
              <ShopNode
                key={n.id}
                node={n}
                onSelect={onSelect}
                selected={selected}
                parents={[...parents, node.id]}
              />
            ))}
          </ul>
          {result.data && result.data.total > result.data.limit && (
            <Pager {...result.data} onChange={setOffset} />
          )}
        </>
      )}
    </li>
  );
}
function ShopDetails({
  id,
  onSelect,
  onChildren,
  onMappingUpdated,
}: {
  id: string;
  onSelect: (n: NavLink) => void;
  onChildren: (n: NavCategory) => void;
  onMappingUpdated: () => void;
}) {
  const [rev, setRev] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const result = useLoad<NavCategory>(
    `/reference/navigation/${encodeURIComponent(id)}`,
    rev,
  );
  const who = useLoad<Me>("/auth/me");
  const node = result.data;
  const kinds: Record<string, string> = {
    parameter_filter: "Paraméterszűrő",
    brand: "Márkaoldal",
    campaign: "Kampány",
    collection: "Gyűjtőoldal",
    product_finder: "Termékkereső",
    search: "Keresés",
    related_section: "Kapcsolódó szekció",
    department_link: "Főcsoport-hivatkozás",
    unknown_link: "Ellenőrzendő link",
  };
  if (!node)
    return (
      <>
        <ErrorBox message={result.error} />
        <Empty loading={result.loading} />
      </>
    );
  return (
    <>
      <section className="card padded">
        <div className="breadcrumbs">
          {node.ancestors.map((p, i) => (
            <button
              key={p.id}
              onClick={() =>
                onSelect({
                  ...p,
                  ancestors: node.ancestors.slice(0, i),
                  path: node.path.slice(0, i + 1),
                })
              }
            >
              {p.name} /
            </button>
          ))}
        </div>
        <p className="eyebrow">EGYSÉGES KATEGÓRIANAVIGÁCIÓ</p>
        <h2>{node.name}</h2>
        <p className="category-full-path">
          {node.path.map((p) => p.name).join(" / ")}
        </p>
        <span className={"badge " + (node.selectable ? "good" : "")}>
          {node.selectable
            ? "Termékbesorolásra választható"
            : node.kind === "department" || node.kind === "section"
              ? "Strukturális navigáció"
              : "Besorolás előtt ellenőrzendő"}
        </span>
        <p className="small muted">
          Webshop menüazonosító:{" "}
          {node.source_item_id || node.source_department_id} · ez nem
          Marketplace-azonosító
        </p>
        {node.canonical_emag_id && (
          <p>
            Igazolt Marketplace eMAG-ID:{" "}
            <strong>{node.canonical_emag_id}</strong>
          </p>
        )}
        {node.hierarchy_status === "needs_review" && (
          <p className="warning">
            A főcsoporthoz tartozás bizonyított, de a pontos belső
            szekciókapcsolat további forrásadatot igényel.
          </p>
        )}
        <div className="facts">
          <span>Alkategóriák / szekciók: {node.children_count}</span>
          <span>
            Paraméterek:{" "}
            {node.kind === "department"
              ? "Strukturális főcsoport"
              : (node.parameter_count ?? "Még nem ellenőrzött")}
          </span>
          {node.parameter_count !== null && (
            <>
              <span>Kötelező: {node.mandatory_parameter_count}</span>
              <span>Opcionális: {node.optional_parameter_count}</span>
            </>
          )}
        </div>
        {!!node.children_count && (
          <button className="browse-children" onClick={() => onChildren(node)}>
            Alkategóriák megnyitása
          </button>
        )}
        {!!node.ancestors.length && (
          <button
            className="browse-children"
            onClick={() => onSelect(node.ancestors[node.ancestors.length - 1])}
          >
            Feljebb
          </button>
        )}
        {node.mapping_status !== "confirmed" && node.kind === "category" && (
          <p className="notice">
            A webshop-menü bejegyzéséhez még nincs igazolt
            Marketplace-kapcsolat. Paramétereket névegyezés vagy menüazonosító
            alapján nem kapcsolunk hozzá.
          </p>
        )}
        {who.data?.permissions.includes("system.manage") &&
          ["category", "section"].includes(node.kind) && (
            <details>
              <summary>Igazolt Marketplace-megfeleltetés rögzítése</summary>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  setBusy(true);
                  setError("");
                  try {
                    await api("/reference/sources/observations", "POST", {
                      source_key: "emag_webshop",
                      source_category_id: node.id,
                      evidence_url: f.get("evidence_url"),
                      outcome: "available",
                      mapping_status: "confirmed",
                      canonical_emag_id: Number(f.get("canonical_id")),
                      evidence_kind: f.get("evidence_kind"),
                      content_sha256: f.get("hash"),
                      summary: f.get("summary"),
                    });
                    setRev(rev + 1);
                    onMappingUpdated();
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <p className="warning">
                  A menüazonosító, a névegyezés és a numerikus URL önmagában nem
                  bizonyít Marketplace-kapcsolatot. Csak külső bizonyítékkal
                  igazolt megfeleltetést rögzíts.
                </p>
                <label>
                  Marketplace eMAG-kategóriaazonosító
                  <input name="canonical_id" type="number" min="1" required />
                </label>
                <label>
                  Bizonyíték típusa
                  <select name="evidence_kind">
                    <option value="explicit_marketplace_id">
                      Explicit Marketplace-azonosító a forrásban
                    </option>
                    <option value="documented_crosswalk">
                      Dokumentált megfeleltetés
                    </option>
                  </select>
                </label>
                <label>
                  Bizonyíték publikus eMAG HTTPS-hivatkozása
                  <input
                    type="url"
                    name="evidence_url"
                    defaultValue={node.url || ""}
                    required
                    maxLength={1000}
                  />
                </label>
                <label>
                  Bizonyíték SHA-256 hash-e
                  <input
                    name="hash"
                    required
                    pattern="[a-f0-9]{64}"
                    minLength={64}
                    maxLength={64}
                  />
                </label>
                <label>
                  Azonosság indoklása
                  <textarea
                    name="summary"
                    required
                    minLength={10}
                    maxLength={2000}
                  />
                </label>
                <label className="check">
                  <input type="checkbox" required />
                  Nem pusztán név- vagy számegyezés alapján erősítem meg.
                </label>
                <ErrorBox message={error} />
                <button disabled={busy}>Megfeleltetés megerősítése</button>
              </form>
              {node.mapping_status === "confirmed" && (
                <button
                  disabled={busy}
                  onClick={async () => {
                    try {
                      await api("/reference/sources/observations", "POST", {
                        source_key: "emag_webshop",
                        source_category_id: node.id,
                        evidence_url: node.url,
                        outcome: "partial",
                        mapping_status: "pending",
                        summary:
                          "A korábbi megfeleltetés felülvizsgálatra visszavonva.",
                      });
                      setRev(rev + 1);
                      onMappingUpdated();
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  Megfeleltetés visszavonása
                </button>
              )}
            </details>
          )}
      </section>
      {node.mapping_status === "confirmed" &&
        ["category", "section"].includes(node.kind) && (
          <Parameters key={id + "-" + rev} navigationId={id} view="all" />
        )}
      {!!node.related_links.length && (
        <section className="card padded">
          <h2>Kapcsolódó linkek – nem külön termékkategóriák</h2>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Név</th>
                  <th>Típus</th>
                </tr>
              </thead>
              <tbody>
                {node.related_links.map((n) => (
                  <tr key={n.id}>
                    <td>
                      {n.url ? (
                        <a href={n.url} target="_blank" rel="noreferrer">
                          {n.name}
                        </a>
                      ) : (
                        n.name
                      )}
                    </td>
                    <td>{kinds[n.kind] || n.kind}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
function Categories() {
  const [q, setQ] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<NavLink | null>(null),
    [focus, setFocus] = useState<NavCategory | null>(null),
    [mappingRevision, setMappingRevision] = useState(0);
  const query = useDebounce(q);
  const result = useLoad<Page<NavCategory>>(
    `/reference/navigation?q=${encodeURIComponent(query)}&offset=${offset}${focus && !query ? `&parent_id=${encodeURIComponent(focus.id)}` : ""}`,
    mappingRevision,
  );
  const coverage = useLoad<{
    root_count: number;
    manifest_link_count: number;
    hierarchy_needs_review: number;
    confirmed_bindings: number;
  }>("/reference/navigation/coverage", mappingRevision);
  return (
    <>
      <p className="notice">
        A valós magyar eMAG-menü 13 főcsoportja, eredeti sorrendben. A webshop
        menüazonosítói és a Marketplace-kategóriaazonosítók különböznek;
        paraméter csak igazolt megfeleltetés után jelenik meg.
      </p>
      <ErrorBox message={coverage.error} />
      {coverage.data && (
        <div className="reference-metrics">
          {[
            [coverage.data.root_count, "Valós főcsoport"],
            [coverage.data.manifest_link_count, "Rögzített menühivatkozás"],
            [coverage.data.confirmed_bindings, "Igazolt Marketplace-kapcsolat"],
            [
              coverage.data.hierarchy_needs_review,
              "Ellenőrzendő szekciókapcsolat",
            ],
          ].map(([v, label]) => (
            <div className="card" key={String(label)}>
              <strong>{v}</strong>
              <small>{label}</small>
            </div>
          ))}
        </div>
      )}
      <div className="browser-grid">
        <section className="card padded tree">
          {focus && (
            <div className="tree-location">
              <button
                onClick={() => {
                  setFocus(null);
                  setOffset(0);
                  setQ("");
                }}
              >
                Főkategóriák
              </button>
              <span>{focus.name}</span>
            </div>
          )}
          <label>
            Kategóriakeresés
            <input
              value={q}
              placeholder="Keresés a webshop navigációjában"
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          <ErrorBox message={result.error} />
          <ul>
            {result.data?.items.map((n) => (
              <ShopNode
                key={n.id}
                node={n}
                selected={selected?.id}
                onSelect={setSelected}
              />
            ))}
          </ul>
          {!result.data?.items.length && <Empty loading={result.loading} />}{" "}
          {result.data && <Pager {...result.data} onChange={setOffset} />}
        </section>
        <div className="detail">
          {selected ? (
            <ShopDetails
              key={selected.id}
              id={selected.id}
              onMappingUpdated={() => setMappingRevision((r) => r + 1)}
              onSelect={setSelected}
              onChildren={(n) => {
                setFocus(n);
                setOffset(0);
                setQ("");
              }}
            />
          ) : (
            <section className="card padded empty-detail">
              <h2>Válassz egy főcsoportot</h2>
              <p>
                A plusz gombbal nyisd meg az almenüt. A szekciók és
                kategóriahivatkozások a bizonyított HTML-kapcsolatot követik.
              </p>
            </section>
          )}
        </div>
      </div>
      <ReferenceSources />
    </>
  );
}

function ReferenceSources() {
  const [rev, setRev] = useState(0),
    [message, setMessage] = useState("");
  const sources = useLoad<{
    items: { key: string; name: string; description: string }[];
  }>("/reference/sources");
  const observations = useLoad<
    Page<{
      id: number;
      source_key: string;
      outcome: string;
      mapping_status: string;
      summary: string;
      evidence_url: string;
      observed_at: string;
    }>
  >("/reference/sources/observations?limit=10", rev);
  const who = useLoad<Me>("/auth/me");
  return (
    <section className="card padded">
      <h2>Források és tényleges lefedettség</h2>
      <p className="warning">
        A helyi Marketplace-referencia nem bizonyítja a teljes magyar
        webshop-kategóriafa lefedettségét. Szülőparaméter-öröklést nem
        feltételezünk. Az ismeretlen megfeleltetések nem módosítják a
        kategóriafát.
      </p>
      <ErrorBox message={sources.error || observations.error} />
      <div className="source-grid">
        {sources.data?.items.map((s) => (
          <div key={s.key}>
            <strong>{s.name}</strong>
            <small>{s.description}</small>
          </div>
        ))}
      </div>
      <ul className="source-events">
        {observations.data?.items.map((o) => (
          <li key={o.id}>
            <strong>
              {sources.data?.items.find((s) => s.key === o.source_key)?.name ||
                o.source_key}{" "}
              ·{" "}
              {(
                {
                  available: "Elérhető",
                  partial: "Részleges",
                  blocked: "Tiltott",
                  unavailable: "Nem elérhető",
                } as Record<string, string>
              )[o.outcome] || o.outcome}{" "}
              ·{" "}
              {(
                {
                  pending: "Megfeleltetésre vár",
                  confirmed: "Igazolt",
                  rejected: "Elutasított",
                } as Record<string, string>
              )[o.mapping_status] || o.mapping_status}
            </strong>
            <p>{o.summary}</p>
            <small>
              {new Date(o.observed_at).toLocaleString("hu-HU")} ·{" "}
              <a href={o.evidence_url} target="_blank" rel="noreferrer">
                Forráshivatkozás
              </a>
            </small>
          </li>
        ))}
      </ul>
      {observations.data && !observations.data.total && (
        <p className="muted">
          Nincs rögzített forrásmegfigyelés. Ez nem igazolja a publikus forrás
          teljességét.
        </p>
      )}
      {who.data?.permissions.includes("system.manage") && (
        <details>
          <summary>Forrásmegfigyelés rögzítése (Superadmin)</summary>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              try {
                await api("/reference/sources/observations", "POST", {
                  source_key: fd.get("source_key"),
                  evidence_url: fd.get("url"),
                  outcome: fd.get("outcome"),
                  summary: fd.get("summary"),
                  ...(fd.get("source_category_id")
                    ? { source_category_id: fd.get("source_category_id") }
                    : {}),
                });
                setRev(rev + 1);
                setMessage(
                  "Megfigyelés rögzítve; automatikus kategória-megfeleltetés nem történt.",
                );
              } catch (e) {
                setMessage((e as Error).message);
              }
            }}
          >
            <label>
              Forrás
              <select name="source_key">
                {sources.data?.items.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Publikus eMAG HTTPS-hivatkozás
              <input type="url" name="url" required maxLength={1000} />
            </label>
            <label>
              Elérés
              <select name="outcome">
                <option value="partial">Részleges</option>
                <option value="available">Elérhető</option>
                <option value="blocked">Tiltott</option>
                <option value="unavailable">Nem elérhető</option>
              </select>
            </label>
            <label>
              Forrásazonosító (opcionális, megfeleltetésre vár)
              <input name="source_category_id" maxLength={160} />
            </label>
            <label>
              Bizonyíték / korlát
              <textarea
                name="summary"
                minLength={10}
                maxLength={2000}
                required
              />
            </label>
            <button>Megfigyelés mentése</button>
          </form>
        </details>
      )}
      <p role="status">{message}</p>
    </section>
  );
}

function SystemStatus() {
  const [rev, setRev] = useState(0);
  const { data, error, loading } = useLoad<{
    status: string;
    checks: Record<string, boolean>;
  }>("/system/status", rev);
  const names: Record<string, string> = {
    database: "Alkalmazás-adatbázis",
    reference: "eMAG-referencia",
    redis: "Redis",
    worker: "Celery worker",
  };
  // Readiness returns 503 for degraded services; retain a useful explicit message.
  return (
    <section className="card padded">
      <div className="sectionbar">
        <h2>Szolgáltatások állapota</h2>
        <button onClick={() => setRev(rev + 1)} disabled={loading}>
          Frissítés
        </button>
      </div>
      <ErrorBox message={error} />
      {data ? (
        <div className="status-grid">
          {Object.entries(data.checks).map(([key, ok]) => (
            <div key={key}>
              <span className={"status-dot " + (ok ? "ok" : "")} />
              <strong>{names[key] || key}</strong>
              <small>{ok ? "Elérhető" : "Nem elérhető"}</small>
            </div>
          ))}
        </div>
      ) : (
        loading && <Empty loading />
      )}
    </section>
  );
}
function AuditLog() {
  const [offset, setOffset] = useState(0);
  const { data, error, loading } = useLoad<
    Page<{
      id: number;
      created_at: string;
      actor_id: number;
      tenant_id: number | null;
      action: string;
      target: string;
    }>
  >(`/audit?offset=${offset}`);
  return (
    <section className="card padded">
      <h2>Adminisztrációs napló</h2>
      <ErrorBox message={error} />
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>Időpont</th>
              <th>Művelet</th>
              <th>Végrehajtó</th>
              <th>Cél</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((a) => (
              <tr key={a.id}>
                <td>{new Date(a.created_at).toLocaleString("hu-HU")}</td>
                <td>{a.action}</td>
                <td>#{a.actor_id ?? "–"}</td>
                <td>
                  {a.target}
                  {a.tenant_id && ` · Ügyfél #${a.tenant_id}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data?.items.length && <Empty loading={loading} />}{" "}
      {data && <Pager {...data} onChange={setOffset} />}
    </section>
  );
}
function Settings() {
  const [rev, setRev] = useState(0),
    [message, setMessage] = useState("");
  const { data, error } = useLoad<Record<string, string>>("/settings", rev);
  return (
    <section className="card padded">
      <h2>Rendszerkonfiguráció</h2>
      <p className="muted">
        Nyilvános szöveges beállítások. API-kulcsokat és jelszavakat itt ne adj
        meg.
      </p>
      <ErrorBox message={error} />
      {data && (
        <form
          key={rev}
          onSubmit={async (e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            try {
              for (const key of ["display_name", "admin_notice"])
                await api(`/settings/${key}`, "PUT", { value: fd.get(key) });
              setMessage("A beállítások mentve.");
              setRev(rev + 1);
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          <label>
            Rendszer megjelenített neve
            <input
              name="display_name"
              maxLength={1000}
              defaultValue={data.display_name || ""}
            />
          </label>
          <label>
            Adminisztrációs megjegyzés
            <textarea
              name="admin_notice"
              maxLength={1000}
              defaultValue={data.admin_notice || ""}
            />
          </label>
          <button className="primary">Mentés</button>
        </form>
      )}
      <p role="status">{message}</p>
    </section>
  );
}
function Password({
  close,
  onChanged,
}: {
  close: () => void;
  onChanged: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <Modal title="Saját jelszó módosítása" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          if (fd.get("password") !== fd.get("confirm")) {
            setError("A két új jelszó nem egyezik.");
            return;
          }
          setBusy(true);
          try {
            await api("/auth/password", "POST", {
              current_password: fd.get("current_password"),
              password: fd.get("password"),
            });
            onChanged();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Jelenlegi jelszó
          <input
            type="password"
            name="current_password"
            required
            maxLength={128}
            autoComplete="current-password"
          />
        </label>
        <label>
          Új jelszó
          <input
            type="password"
            name="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
        </label>
        <label>
          Új jelszó megerősítése
          <input
            type="password"
            name="confirm"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
        </label>
        <ErrorBox message={error} />
        <p className="small muted">
          A módosítás után minden eszközön újra be kell jelentkezned.
        </p>
        <button className="primary" disabled={busy}>
          Jelszó módosítása
        </button>
      </form>
    </Modal>
  );
}
function App() {
  const [me, setMe] = useState<Me | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [page, setPage] = useState("dashboard"),
    [password, setPassword] = useState(false);
  async function refresh() {
    const user = await api<Me>("/auth/me");
    csrf = user.csrf_token;
    setMe(user);
  }
  useEffect(() => {
    refresh()
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
    const expire = () => {
      csrf = "";
      setMe(null);
      setPassword(false);
    };
    window.addEventListener("session-expired", expire);
    return () => window.removeEventListener("session-expired", expire);
  }, []);
  if (loading)
    return (
      <div className="boot">
        <Empty loading />
      </div>
    );
  if (!me)
    return (
      <Login
        onLogin={async () => {
          await refresh();
          setPage("dashboard");
          setError("");
        }}
      />
    );
  const can = (permission: string) => me.permissions.includes(permission);
  const pages = [
    ["dashboard", "◫", "Áttekintés"],
    ["tenants", "▦", "Ügyfelek"],
    ...(can("users.manage") ? [["users", "♙", "Felhasználók"]] : []),
    ...(can("reference.read")
      ? [
          ["categories", "⌘", "eMAG-kategóriák"],
          ["parameters", "≡", "Paraméterkereső"],
        ]
      : []),
    ...(can("audit.read") ? [["audit", "◷", "Műveleti napló"]] : []),
    ...(can("system.manage")
      ? [["settings", "⚙", "Rendszerbeállítások"]]
      : []),
  ];
  const title = pages.find((p) => p[0] === page)?.[2] || "Áttekintés";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandmark">
            A<span>+</span>
          </div>
          <div>
            Adatdúsító<small>PAKSI INFORMATIKA</small>
          </div>
        </div>
        <div className="workspace">
          <label>
            Munkaterület
            <select
              value={me.tenant_id ?? ""}
              onChange={async (e) => {
                setError("");
                try {
                  await api("/auth/tenant", "POST", {
                    tenant_id: e.target.value ? Number(e.target.value) : null,
                  });
                  await refresh();
                  setPage("dashboard");
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              <option value="" disabled={!me.user.superadmin}>
                {me.user.superadmin ? "Rendszerszint" : "Válassz ügyfelet"}
              </option>
              {me.memberships.map((m) => (
                <option key={m.tenant_id} value={m.tenant_id}>
                  {m.name}
                </option>
              ))}
              {me.user.superadmin &&
                me.tenant_id &&
                !me.memberships.some((m) => m.tenant_id === me.tenant_id) && (
                  <option value={me.tenant_id}>Ügyfél #{me.tenant_id}</option>
                )}
            </select>
          </label>
        </div>
        <p className="nav-label">MUNKATERÜLET</p>
        <nav>
          {pages.map(([key, icon, label]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              aria-current={page === key ? "page" : undefined}
              onClick={() => {
                setPage(key);
                setError("");
              }}
            >
              <span aria-hidden>{icon}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot ok" /> Fejlesztői környezet
          <small>CODEX 03A · Referencia</small>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="crumb">
            Munkaterület / <strong>{title}</strong>
          </span>
          <div className="user-menu">
            <span className="avatar small-avatar">
              {me.user.name.slice(0, 2).toUpperCase()}
            </span>
            <div>
              <strong>{me.user.name}</strong>
              <small>
                {roleNames[me.role || ""] || "Nincs aktív szerepkör"}
              </small>
            </div>
            <button onClick={() => setPassword(true)}>Jelszó</button>
            <button
              onClick={async () => {
                setError("");
                try {
                  await api("/auth/logout", "POST");
                  csrf = "";
                  setMe(null);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Kilépés
            </button>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">ADATDÚSÍTÓ / ADMINISZTRÁCIÓ</p>
              <h1>{title}</h1>
            </div>
            <span className="badge environment">FEJLESZTŐI</span>
          </div>
          <ErrorBox message={error} />
          {page === "dashboard" && (
            <>
              <section className="welcome">
                <div>
                  <p className="eyebrow">ÜDV A MUNKATERÜLETEN</p>
                  <h2>Szia, {me.user.name}!</h2>
                  <p>
                    Kezeld a hozzáféréseket, és böngészd az eMAG
                    referenciaadatait.
                  </p>
                  <span className="badge">
                    {roleNames[me.role || ""] ||
                      "Válassz ügyfelet a folytatáshoz"}
                  </span>
                </div>
                <div className="welcome-symbol" aria-hidden>
                  →
                </div>
              </section>
              <div className="quick-grid">
                {can("reference.read") && (
                  <button
                    className="card quick"
                    onClick={() => setPage("categories")}
                  >
                    <span>⌘</span>
                    <h2>eMAG-kategóriák</h2>
                    <p>Hierarchia, paraméterek és megengedett értékek.</p>
                    <b>Referenciaböngésző →</b>
                  </button>
                )}
                <button
                  className="card quick"
                  onClick={() => setPage("tenants")}
                >
                  <span>▦</span>
                  <h2>Ügyfelek</h2>
                  <p>Szervezetek és felhasználói hozzáférések.</p>
                  <b>Ügyfelek megnyitása →</b>
                </button>
              </div>
              <SystemStatus />
              <p className="small muted">
                API-dokumentáció:{" "}
                <a href="/api/v1/docs" target="_blank" rel="noreferrer">
                  OpenAPI / Swagger UI →
                </a>
              </p>
            </>
          )}
          {page === "users" && can("users.manage") && <Users />}
          {page === "tenants" && <Tenants me={me} />}{" "}
          {page === "categories" && can("reference.read") && <Categories />}
          {page === "parameters" && can("reference.read") && <Parameters />}
          {page === "audit" && can("audit.read") && <AuditLog />}
          {page === "settings" && can("system.manage") && <Settings />}
        </main>
        <footer>
          Adatdúsító · Paksi Informatika
          <span>Biztonságos, ügyfelenként elkülönített munkaterület</span>
        </footer>
      </div>
      {password && (
        <Password
          close={() => setPassword(false)}
          onChanged={() => {
            setPassword(false);
            csrf = "";
            setMe(null);
          }}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
