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
type Category = {
  id: number;
  emag_category_id: number;
  name: string;
  parent_id: number | null;
  parent_emag_id: number | null;
  parent_name: string | null;
  missing_parent: boolean;
  is_allowed: boolean | null;
  is_ean_mandatory: boolean | null;
  is_warranty_mandatory: boolean | null;
  ancestors?: Category[];
  hierarchy_error?: string | null;
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
function CategoryNode({
  category,
  onSelect,
  path = [],
}: {
  category: Category;
  onSelect: (c: Category) => void;
  path?: number[];
}) {
  const [open, setOpen] = useState(false),
    [offset, setOffset] = useState(0);
  const cycle = path.includes(category.id);
  const { data, error, loading } = useLoad<Page<Category>>(
    open && !cycle
      ? `/reference/categories?parent_id=${category.id}&offset=${offset}`
      : null,
  );
  return (
    <li>
      <div className="tree-row">
        <button
          className="tree-toggle"
          disabled={cycle}
          aria-label={`${category.name} alkategóriái`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? "−" : "+"}
        </button>
        <button className="tree-name" onClick={() => onSelect(category)}>
          {category.name}
          <small>
            eMAG {category.emag_category_id}
            {category.missing_parent ? " · Hiányzó vagy inaktív szülő" : ""}
          </small>
        </button>
      </div>
      {cycle && <p className="error">Körkörös hivatkozás</p>}
      {open && (
        <>
          <ErrorBox message={error} />
          {loading && <Empty loading />}
          {data?.items.length ? (
            <ul>
              {data.items.map((c) => (
                <CategoryNode
                  key={c.id}
                  category={c}
                  onSelect={onSelect}
                  path={[...path, category.id]}
                />
              ))}
            </ul>
          ) : (
            !loading && (
              <p className="small muted tree-note">Nincs alkategória.</p>
            )
          )}
          {data && data.total > data.limit && (
            <Pager {...data} onChange={setOffset} />
          )}
        </>
      )}
    </li>
  );
}
function ValueBrowser({ parameter }: { parameter: Parameter }) {
  const [q, setQ] = useState(""),
    [after, setAfter] = useState(0),
    [history, setHistory] = useState<number[]>([]);
  const query = useDebounce(q);
  const { data, error, loading } = useLoad<Values>(
    `/reference/parameters/${parameter.id}/values?after=${after}&q=${encodeURIComponent(query)}`,
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
function Parameters({ categoryId }: { categoryId?: number }) {
  const [q, setQ] = useState(""),
    [mandatory, setMandatory] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Parameter | null>(null);
  const query = useDebounce(q);
  const url = `/reference/parameters?offset=${offset}&q=${encodeURIComponent(query)}${categoryId ? `&category_id=${categoryId}` : ""}${mandatory ? `&mandatory=${mandatory}` : ""}`;
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
      {selected && <ValueBrowser key={selected.id} parameter={selected} />}
    </>
  );
}
function CategoryDetails({
  id,
  onSelect,
}: {
  id: number;
  onSelect: (c: Category) => void;
}) {
  const { data, error, loading } = useLoad<Category>(
    `/reference/categories/${id}`,
  );
  return (
    <>
      <ErrorBox message={error} />
      {!data ? (
        <Empty loading={loading} />
      ) : (
        <>
          <section className="card padded">
            <div className="breadcrumbs">
              {data.ancestors?.map((a) => (
                <button key={a.id} onClick={() => onSelect(a)}>
                  {a.name} /
                </button>
              ))}
            </div>
            <p className="eyebrow">KATEGÓRIA ADATLAPJA</p>
            <h2>{data.name}</h2>
            <p className="small muted">
              eMAG #{data.emag_category_id} · Belső azonosító #{data.id}
            </p>
            {data.hierarchy_error && (
              <p className="warning">
                {data.hierarchy_error === "missing_parent"
                  ? "A szülőláncban inaktív vagy hiányzó kategória található."
                  : "A hierarchia hibás vagy túl mély; a teljes szülőlánc nem jeleníthető meg."}
              </p>
            )}
            <div className="facts">
              <span>
                Engedélyezett: <Flag value={data.is_allowed} />
              </span>
              <span>
                EAN kötelező: <Flag value={data.is_ean_mandatory} />
              </span>
              <span>
                Garancia kötelező: <Flag value={data.is_warranty_mandatory} />
              </span>
            </div>
          </section>
          <Parameters key={id} categoryId={id} />
        </>
      )}
    </>
  );
}
function Categories() {
  const [q, setQ] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Category | null>(null);
  const query = useDebounce(q);
  const { data, error, loading } = useLoad<Page<Category>>(
    `/reference/categories?q=${encodeURIComponent(query)}&offset=${offset}`,
  );
  return (
    <>
      <p className="notice">
        Csak olvasható referenciaadatok. A hiányzó vagy inaktív szülőjű
        kategóriák külön figyelmeztetéssel szerepelnek a gyökérszinten.
      </p>
      <div className="browser-grid">
        <section className="card padded tree">
          <label>
            Kategóriakeresés
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
              placeholder="Név vagy eMAG-azonosító"
            />
          </label>
          <ErrorBox message={error} />
          <ul>
            {data?.items.map((c) => (
              <CategoryNode
                key={`${query}-${c.id}`}
                category={c}
                onSelect={setSelected}
              />
            ))}
          </ul>
          {!data?.items.length && <Empty loading={loading} />}{" "}
          {data && <Pager {...data} onChange={setOffset} />}
        </section>
        <div className="detail">
          {selected ? (
            <CategoryDetails id={selected.id} onSelect={setSelected} />
          ) : (
            <section className="card padded empty-detail">
              <span>⌘</span>
              <h2>Válassz egy kategóriát</h2>
              <p>
                A kategória adatai, paraméterei és megengedett értékei itt
                jelennek meg.
              </p>
            </section>
          )}
        </div>
      </div>
    </>
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
          <small>CODEX 02 · Adminisztráció</small>
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
