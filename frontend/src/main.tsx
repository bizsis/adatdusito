import { auditLabel } from "./help";
import { readApiResponse, apiErrorMessage } from "./apiResponse";
import { dateTime } from "./ui";
import React, { useEffect, useState, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-ext-400.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-ext-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/inter/latin-ext-700.css";
import "./tokens.css";
import "./style.css";
import { SystemSettings } from "./SystemSettings";
import { AuthLogin, SecurityCenter, RegistrationConfirm } from "./AuthViews";
import { ProductData } from "./ProductData";
import { setDisplayTimezone } from "./ui";
import {
  LayoutDashboard,
  Building2,
  Users,
  ShieldCheck,
  Settings2,
  ScrollText,
  FileUp,
  FileDown,
  PackageSearch,
  Network,
  ListFilter,
  LockKeyhole,
  type LucideIcon,
} from "lucide-react";
function NavIcon({ name }: { name: string }) {
  const icons: Record<string, LucideIcon> = {
    dashboard: LayoutDashboard,
    tenants: Building2,
    members: Users,
    "access-system": ShieldCheck,
    settings: Settings2,
    audit: ScrollText,
    imports: FileUp,
    "export-fields": FileDown,
    products: PackageSearch,
    categories: Network,
    parameters: ListFilter,
    security: LockKeyhole,
  };
  const Icon = icons[name] || PackageSearch;
  return <Icon size={19} aria-hidden />;
}
import { AccessWorkspace, AcceptInvitation } from "./AccessWorkspace";
import { ImportWorkspace, ExportAdmin } from "./ImportWorkspace";

type User = {
  id: number;
  name: string;
  email: string | null;
  username?: string;
  must_change_password?: boolean;
  active: boolean;
  superadmin: boolean;
};
type Tenant = { id: number; name: string; active: boolean };
type Me = {
  mfa_required?: boolean;
  user: User;
  tenant_id: number | null;
  workspaces?: { tenant_id: number; name: string }[];
  workspace?: {
    tenant_id: number;
    name: string;
    onboarding_state?: string;
  } | null;
  system?: boolean;
  roles?: { id: number; name: string; code: string }[];
  resource_access?: { full: boolean; companies?: number[]; shops?: number[] };
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
type ParameterProfile = {
  source_category_id: number;
  emag_category_id: number;
  name: string;
  parameter_count: number;
  mandatory_parameter_count: number;
  optional_parameter_count: number;
};
type NavCategory = NavLink & {
  unified_category_id?: number;
  catalog_version_id?: number;
  placement_status: string;
  structural_only?: boolean;
  source_item_id: string | null;
  source_department_id: string;
  url: string | null;
  children_count: number;
  mapping_status: string;
  mapping_method: string | null;
  reference_name: string | null;
  archived: boolean;
  inactive: boolean;
  mapping_candidates: ReferenceChoice[];
  canonical_emag_id: number | null;
  selectable: boolean;
  parameter_count: number | null;
  parameter_profiles?: ParameterProfile[];
  parameter_profile_count?: number;
  mandatory_parameter_count: number | null;
  optional_parameter_count: number | null;
  ancestors: NavLink[];
  path: NavLink[];
  related_links: (NavLink & { url: string | null })[];
  related_parameter_filters?: {
    name: string;
    status: string;
    match: { parameter_name: string; value_text: string } | null;
  }[];
};
type ReferenceChoice = {
  category_id?: number;
  emag_category_id: number;
  name: string;
  path_names: string[];
  parameter_count?: number;
};
type Parameter = {
  category_constraint?: { operator: string; value_text: string };
  id: number;
  parameter_id?: number;
  category_parameter_id?: number;
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
      ...(body !== undefined && !(body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
    },
    ...(body !== undefined
      ? { body: body instanceof FormData ? body : JSON.stringify(body) }
      : {}),
  });
  const data = await readApiResponse(response);
  if (!response.ok) {
    if (response.status === 401 && url !== "/auth/login")
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(apiErrorMessage(response.status, data));
  }
  return data as T;
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
  return (
    <AuthLogin
      api={api}
      initialMfa={new URLSearchParams(location.hash.slice(1)).get("mfa") || ""}
      onAuthenticated={async (value) => {
        csrf = value;
        await onLogin();
      }}
    />
  );
}

function Tenants({
  me,
  onSwitch,
}: {
  me: Me;
  onSwitch: (id: number) => Promise<void>;
}) {
  const [offset, setOffset] = useState(0),
    [rev, setRev] = useState(0),
    [selected, setSelected] = useState<Tenant | null>(null),
    [editing, setEditing] = useState<Tenant | true | null>(null),
    [error, setError] = useState("");
  const result = useLoad<Page<Tenant>>(`/tenants?offset=${offset}`, rev);
  const manage =
    me.permissions.includes("tenants.edit") ||
    me.permissions.includes("tenants.suspend");
  return (
    <>
      <div className="sectionbar">
        <p className="muted">
          {me.user.superadmin
            ? "Ügyfelek és szervezeti hozzáférések kezelése."
            : "A hozzád rendelt szervezetek."}
        </p>
        {me.permissions.includes("tenants.create") && (
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
        <section className="card padded">
          <h3>{selected.name}</h3>
          <p>
            A munkatársak és jogosultságok a kiválasztott munkaterületen
            kezelhetők.
          </p>
          <button onClick={() => onSwitch(selected.id)}>
            Munkaterület megnyitása: {selected.name}
          </button>
        </section>
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
                    ...(editing !== true &&
                    me.permissions.includes("tenants.suspend")
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
            {editing !== true && me.permissions.includes("tenants.suspend") && (
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
  view = "all",
  navigationId,
  profileEmagId,
}: {
  categoryId?: number;
  view?: string;
  navigationId?: string;
  profileEmagId?: number;
}) {
  const [q, setQ] = useState(""),
    [mandatory, setMandatory] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Parameter | null>(null);
  const query = useDebounce(q);
  const url = `${navigationId ? `/reference/navigation/${encodeURIComponent(navigationId)}/parameters` : "/reference/parameters"}?view=${view}&offset=${offset}&q=${encodeURIComponent(query)}${categoryId ? `&category_id=${categoryId}` : ""}${profileEmagId ? `&profile_emag_id=${profileEmagId}` : ""}${mandatory ? `&mandatory=${mandatory}` : ""}`;
  const { data, error, loading } = useLoad<Page<Parameter>>(url);
  return (
    <>
      <section className="card padded">
        <div className="sectionbar">
          <h2>
            {categoryId || navigationId
              ? "Kategóriaparaméterek"
              : "Paraméterkereső"}
          </h2>
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
        <div className="table-wrap">
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
                    {p.category_constraint && (
                      <small>
                        Kategóriamegkötés: {p.category_constraint.value_text}
                      </small>
                    )}
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
  allowExpand = true,
}: {
  node: NavCategory;
  onSelect: (n: NavLink) => void;
  selected?: string;
  parents?: string[];
  allowExpand?: boolean;
}) {
  const [open, setOpen] = useState(false),
    [offset, setOffset] = useState(0);
  const result = useLoad<Page<NavCategory>>(
    open && allowExpand
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
          disabled={!allowExpand || cycle || !node.children_count}
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
              : node.kind === "section" || node.structural_only
                ? "Navigációs gyűjtőpont"
                : node.mapping_status === "confirmed"
                  ? "Paraméterforrás hozzárendelve"
                  : node.mapping_status === "pending"
                    ? "Bizonytalan paraméter-hozzárendelés"
                    : "Paraméterkészlet még nem érhető el"}
            {node.placement_status !== "verified_tree" && (
              <span> · Besorolás ellenőrzendő</span>
            )}
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
      {open && allowExpand && !cycle && (
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
function CategoryReview({
  node,
  onSaved,
}: {
  node: NavCategory;
  onSaved: () => void;
}) {
  const [query, setQuery] = useState(""),
    [reference, setReference] = useState(
      (node.parameter_profiles?.length || 0) > 1
        ? ""
        : String(node.unified_category_id || node.canonical_emag_id || ""),
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const term = useDebounce(query);
  const choices = useLoad<{ items: ReferenceChoice[]; total: number }>(
    `/reference/navigation/choices/reference?q=${encodeURIComponent(term)}`,
  );
  const current: ReferenceChoice[] =
    node.parameter_profiles?.map((p) => ({
      category_id: node.catalog_version_id ? p.source_category_id : undefined,
      emag_category_id: p.emag_category_id,
      name: p.name,
      path_names: [p.name],
      parameter_count: p.parameter_count,
    })) ||
    (node.canonical_emag_id
      ? [
          {
            category_id: node.unified_category_id,
            emag_category_id: node.canonical_emag_id,
            name: node.reference_name || node.name,
            path_names: [node.reference_name || node.name],
          },
        ]
      : []);
  const candidates = [
    ...new Map(
      [
        ...current,
        ...(node.mapping_candidates || []),
        ...(choices.data?.items || []),
      ].map((c) => [c.category_id || c.emag_category_id, c]),
    ).values(),
  ];
  async function save(body: object) {
    setBusy(true);
    setError("");
    try {
      await api(
        `/reference/navigation/${encodeURIComponent(node.id)}/assignment`,
        "POST",
        body,
      );
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>Paraméter-hozzárendelés szerkesztése (adminisztrátor)</summary>
      {(node.parameter_profiles?.length || 0) > 1 && (
        <p>
          A kézi forrásválasztás egyetlen profilra cseréli az automatikus
          hozzárendelést. Visszaállítással az összes ellenőrzött profil ismét
          elérhető.
        </p>
      )}
      {!node.id.startsWith("ref-") && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save(
              node.catalog_version_id
                ? { category_id: Number(reference) }
                : { canonical_emag_id: Number(reference) },
            );
          }}
        >
          <label>
            Paraméterforrás keresése
            <input value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label>
            Paraméterforrás kiválasztása
            <select
              aria-label="Paraméterforrás kiválasztása"
              required
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            >
              <option value="">Válassz kategóriát</option>
              {candidates.map((c) => (
                <option
                  key={c.category_id || c.emag_category_id}
                  value={c.category_id || c.emag_category_id}
                >
                  {c.path_names.join(" / ")} · eMAG {c.emag_category_id}
                  {c.parameter_count !== undefined
                    ? ` · ${c.parameter_count} paraméter`
                    : ""}
                </option>
              ))}
            </select>
          </label>
          <ErrorBox message={choices.error} />
          {choices.data && choices.data.total > 50 && (
            <p>Pontosítsd a keresést a további kategóriákhoz.</p>
          )}
          <button disabled={busy}>Paraméterforrás mentése</button>
        </form>
      )}
      <button disabled={busy} onClick={() => save({ reset: true })}>
        {node.catalog_version_id
          ? "Automatikus paraméter-hozzárendelés visszaállítása"
          : "Automatikus paraméter-hozzárendelés visszaállítása"}
      </button>
      <ErrorBox message={error} />
    </details>
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
  const [rev, setRev] = useState(0);
  const [profile, setProfile] = useState<number | null>(null);
  const result = useLoad<NavCategory>(
    `/reference/navigation/${encodeURIComponent(id)}`,
    rev,
  );
  const who = useLoad<Me>("/auth/me");
  const node = result.data;
  const profiles = node?.parameter_profiles || [];
  const activeProfile =
    profiles.find((p) => p.emag_category_id === profile) || profiles[0];
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
            : node.kind === "department" ||
                node.kind === "section" ||
                node.inactive
              ? "Strukturális / termékbesorolásra nem választható"
              : "Besorolás előtt ellenőrzendő"}
        </span>
        {node.hierarchy_status === "needs_review" && (
          <p className="warning">
            Ez a kategória nincs a normál kategóriafába besorolva, vagy inaktív.
            A paraméterei továbbra is megtekinthetők; az adminisztrátor szükség
            esetén pontosíthatja az elhelyezését.
          </p>
        )}
        {profiles.length > 1 && (
          <p>
            {profiles.length} külön hozzárendelt paraméterprofil. Megjelenített
            profil: {activeProfile?.name}.
          </p>
        )}
        <div className="facts">
          <span>Alkategóriák / szekciók: {node.children_count}</span>
          <span>
            Paraméterek:{" "}
            {node.kind === "department" ||
            node.kind === "section" ||
            node.structural_only
              ? "Navigációs gyűjtőpont"
              : (activeProfile?.parameter_count ??
                node.parameter_count ??
                "Még nem ellenőrzött")}
          </span>
          {node.parameter_count !== null && (
            <>
              <span>
                Kötelező:{" "}
                {activeProfile?.mandatory_parameter_count ??
                  node.mandatory_parameter_count}
              </span>
              <span>
                Opcionális:{" "}
                {activeProfile?.optional_parameter_count ??
                  node.optional_parameter_count}
              </span>
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
        {node.mapping_status === "pending" && node.kind === "category" && (
          <p className="notice">
            Több lehetséges paraméterforrás található. Az adminisztrátor
            pontosíthatja a paraméter-hozzárendelést.
          </p>
        )}
        {node.archived && (
          <p className="warning">
            Archivált vagy töröltnek jelölt kategória. A paraméterei
            megtekinthetők, termékbesorolásra nem választható.
          </p>
        )}
        {who.data?.permissions.includes("system.manage") &&
          node.kind === "category" &&
          !node.structural_only && (
            <CategoryReview
              key={node.id + "-" + rev}
              node={node}
              onSaved={() => {
                setRev(rev + 1);
                onMappingUpdated();
              }}
            />
          )}
      </section>
      {node.mapping_status === "confirmed" &&
        ["category", "section"].includes(node.kind) && (
          <>
            {profiles.length > 1 && (
              <section className="card padded">
                <label>
                  Paraméterprofil
                  <select
                    aria-label="Paraméterprofil"
                    value={activeProfile?.emag_category_id || ""}
                    onChange={(e) => setProfile(Number(e.target.value))}
                  >
                    {profiles.map((p) => (
                      <option
                        key={p.emag_category_id}
                        value={p.emag_category_id}
                      >
                        {p.name} · {p.parameter_count} paraméter
                      </option>
                    ))}
                  </select>
                </label>
                <p>
                  Minden felsorolt profil hozzá van rendelve a kategóriához. A
                  kötelező mezőket és megengedett értékeket profilonként, külön
                  kezeljük.
                </p>
              </section>
            )}
            <Parameters
              key={`${id}-${rev}-${activeProfile?.emag_category_id || ""}`}
              navigationId={id}
              profileEmagId={activeProfile?.emag_category_id}
              view="all"
            />
          </>
        )}
      {!!node.related_parameter_filters?.length && (
        <section className="card padded">
          <h2>Kapcsolódó televíziószűrők</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Szűrő</th>
                  <th>Paraméterkapcsolat</th>
                </tr>
              </thead>
              <tbody>
                {node.related_parameter_filters.map((filter) => (
                  <tr key={filter.name}>
                    <td>{filter.name}</td>
                    <td>
                      {filter.match
                        ? `${filter.match.parameter_name}: ${filter.match.value_text}`
                        : filter.status === "ambiguous"
                          ? "Többértelmű paraméterkapcsolat"
                          : "Nincs igazolt paraméterérték"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {!!node.related_links.length && (
        <section className="card padded">
          <h2>Kapcsolódó linkek – nem külön termékkategóriák</h2>
          <div className="table-wrap">
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
    [mappingRevision, setMappingRevision] = useState(0),
    [scope, setScope] = useState("tree");
  const query = useDebounce(q);
  const result = useLoad<Page<NavCategory>>(
    `/reference/navigation?scope=${scope}&q=${encodeURIComponent(query)}&offset=${offset}${focus && !query ? `&parent_id=${encodeURIComponent(focus.id)}` : ""}`,
    mappingRevision,
  );
  const coverage = useLoad<{
    root_count: number;
    manifest_link_count: number;
    hierarchy_needs_review: number;
    confirmed_bindings: number;
    reference_coverage?: {
      fixed_category_count: number;
      parameter_linked_category_count: number;
      ambiguous_parameter_binding_count: number;
      unavailable_parameter_binding_count: number;
      reference_total: number;
      placed_reference_count: number;
      auto_mapped_reference_count: number;
      automatically_arranged_reference_count: number;
      review_reference_count: number;
      unplaced_reference_count: number;
    };
  }>("/reference/navigation/coverage", mappingRevision);
  return (
    <>
      <p className="notice">
        A jóváhagyott magyar kategóriafa rögzített: 13 főcsoport, változatlan
        alkategóriákkal. A forrásadatbázis kizárólag paramétereket és értékeket
        biztosít; az aktív/inaktív jelzője nem módosítja ezt a fát.
      </p>
      <ErrorBox message={coverage.error} />
      {coverage.data && (
        <div className="reference-metrics">
          {[
            [coverage.data.root_count, "Valós főcsoport"],
            [
              coverage.data.reference_coverage?.fixed_category_count ?? "–",
              "Rögzített kategóriapont",
            ],
            [
              coverage.data.reference_coverage
                ?.parameter_linked_category_count ?? "–",
              "Paraméterprofillal rendelkező kategória",
            ],
            [
              coverage.data.reference_coverage
                ?.ambiguous_parameter_binding_count ?? "–",
              "Bizonytalan paraméter-hozzárendelés",
              "unclassified",
            ],
            [
              coverage.data.reference_coverage
                ?.unavailable_parameter_binding_count ?? "–",
              "Paraméterforrás még nem érhető el",
              "unavailable",
            ],
          ].map(([v, label, filter]) =>
            filter ? (
              <button
                type="button"
                className="card metric-action"
                key={String(label)}
                aria-label={`${label} – lista megnyitása`}
                onClick={() => {
                  setScope(String(filter));
                  setFocus(null);
                  setOffset(0);
                  setQ("");
                  setSelected(null);
                }}
              >
                <strong>{v}</strong>
                <small>{label}</small>
                <span className="metric-link">Lista megnyitása →</span>
              </button>
            ) : (
              <div className="card" key={String(label)}>
                <strong>{v}</strong>
                <small>{label}</small>
              </div>
            ),
          )}
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
            Nézet
            <select
              aria-label="Nézet"
              value={scope}
              onChange={(e) => {
                setScope(e.target.value);
                setFocus(null);
                setOffset(0);
              }}
            >
              <option value="tree">Közös kategóriafa</option>
              <option value="unclassified">
                Bizonytalan paraméter-hozzárendelések
              </option>
              <option value="unavailable">
                Paraméterforrás nélküli kategóriák
              </option>
            </select>
          </label>
          {scope === "unclassified" && !query && (
            <p>
              Csak a több lehetséges paraméterforrással rendelkező kategóriák. A
              gyűjtőpontokhoz nem szükséges paraméterkapcsolat.
            </p>
          )}
          {scope === "unavailable" && (
            <p>
              Azok a rögzített termékkategóriák, amelyekhez még nincs egyértelmű
              paraméterforrás. A teljes útvonal látható; a kategóriát megnyitva
              a paraméter-hozzárendelés szerkeszthető.
            </p>
          )}
          <label>
            Kategóriakeresés
            <input
              value={q}
              placeholder="Keresés a rögzített kategóriafában"
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
                key={`${scope}:${query}:${focus?.id || ""}:${n.id}`}
                node={n}
                selected={selected?.id}
                allowExpand={scope === "tree"}
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
                setScope("tree");
                setFocus(n);
                setOffset(0);
                setQ("");
              }}
            />
          ) : (
            <section className="card padded empty-detail">
              <h2>Válassz egy főcsoportot</h2>
              <p>
                A plusz gombbal nyisd meg az alkategóriákat. Kategóriaválasztás
                után megjelennek a hozzá tartozó paraméterek.
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
      mapping_method: string | null;
      reference_name: string | null;
      archived: boolean;
      inactive: boolean;
      mapping_candidates: ReferenceChoice[];
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
              {dateTime(o.observed_at)} ·{" "}
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
    reference: "Közös referenciaadatbázis",
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
      actor_name?: string;
      tenant_name?: string;
      target_name?: string | null;
      details?: unknown;
      tenant_id: number | null;
      action: string;
      target: string;
    }>
  >(`/audit?offset=${offset}`);
  return (
    <section className="card padded">
      <h2>Adminisztrációs napló</h2>
      <ErrorBox message={error} />
      <div className="table-wrap">
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
                <td>{dateTime(a.created_at)}</td>
                <td>
                  {auditLabel(a.action)}
                  <details>
                    <summary>Technikai eseménykód</summary>
                    <code>{a.action}</code>
                    {a.details != null && (
                      <pre>{JSON.stringify(a.details, null, 2)}</pre>
                    )}
                  </details>
                </td>
                <td>{a.actor_name || "Rendszer"}</td>
                <td>
                  {a.target_name || `Erőforrás-azonosító: ${a.target}`}
                  <small>{a.tenant_name || "Rendszerszint"}</small>
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
  const [branding, BR] = useState({
    display_name: "Adatdúsító",
    system_name: "Paksi Informatika",
    environment: "development",
    timezone: "Europe/Budapest",
  });
  const refreshBranding = useCallback(async () => {
    const r = await api<{ branding: typeof branding }>("/auth/methods");
    if (!r.branding || typeof r.branding.display_name !== "string") return;
    BR(r.branding);
    setDisplayTimezone(r.branding.timezone);
    document.title = r.branding.display_name;
  }, []);
  useEffect(() => {
    refreshBranding().catch(() => {});
    if (location.hash === "#security") setPage("security");
    const authError = new URLSearchParams(location.hash.slice(1)).get(
      "auth_error",
    );
    if (authError) setError(authError);
  }, [refreshBranding]);

  const [me, setMe] = useState<Me | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [page, setPage] = useState("dashboard"),
    [password, setPassword] = useState(false);
  const [invitation, setInvitation] = useState(
    () =>
      new URLSearchParams(window.location.hash.slice(1)).get("invite") || "",
  );
  const [inviteLogin, setInviteLogin] = useState(false);
  useEffect(() => {
    const changed = () => {
      setInvitation(
        new URLSearchParams(window.location.hash.slice(1)).get("invite") || "",
      );
      setInviteLogin(false);
    };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  const [workspaceQuery, WQ] = useState(""),
    [workspaceOffset, WO] = useState(0),
    [workspaceItems, WI] = useState<{ tenant_id: number; name: string }[]>([]);
  // Keep the search/form state on periodic session refreshes with identical lists.
  const workspaceSnapshot = JSON.stringify(
    me?.workspaces || me?.memberships || [],
  );
  const canSearchWorkspaces = !!me?.workspaces;
  useEffect(() => {
    WI(JSON.parse(workspaceSnapshot));
    WQ("");
    WO(0);
  }, [me?.tenant_id, workspaceSnapshot]);
  useEffect(() => {
    if (!canSearchWorkspaces) return;
    let cancelled = false;
    const timer = setTimeout(
      () =>
        api<{ items: { tenant_id: number; name: string }[] }>(
          `/access/workspaces?q=${encodeURIComponent(workspaceQuery)}&offset=${workspaceOffset}`,
        )
          .then((r) => {
            if (!cancelled)
              WI((old) => (workspaceOffset ? [...old, ...r.items] : r.items));
          })
          .catch((e) => {
            if (!cancelled) setError(String(e));
          }),
      250,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    workspaceQuery,
    workspaceOffset,
    me?.tenant_id,
    workspaceSnapshot,
    canSearchWorkspaces,
  ]);
  const authGeneration = useRef(0);
  const refresh = useCallback(async () => {
    const generation = ++authGeneration.current;
    const user = await api<Me>("/auth/me");
    if (generation !== authGeneration.current) return;
    csrf = user.csrf_token;
    setMe(user);
  }, []);
  const signedIn = !!me;
  useEffect(() => {
    if (!signedIn) return;
    const timer = setInterval(() => refresh().catch(() => {}), 30000);
    return () => clearInterval(timer);
  }, [signedIn, refresh]);
  async function switchWorkspace(id: number | null) {
    authGeneration.current++;
    setLoading(true);
    setError("");
    setPage("dashboard");
    setPassword(false);
    try {
      await api("/auth/tenant", "POST", { tenant_id: id });
      await refresh();
      WQ("");
      WO(0);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh()
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
    const expire = () => {
      authGeneration.current++;
      csrf = "";
      setMe(null);
      setPassword(false);
    };
    window.addEventListener("session-expired", expire);
    return () => window.removeEventListener("session-expired", expire);
  }, [refresh]);
  if (loading)
    return (
      <div className="boot">
        <Empty loading />
      </div>
    );
  if (invitation && !inviteLogin)
    return (
      <AcceptInvitation
        api={api}
        token={invitation}
        signedIn={!!me}
        onLogin={async () => {
          try {
            if (me) await api("/auth/logout", "POST");
          } catch {
            // Local logout must complete even if the server session has expired.
          } finally {
            authGeneration.current++;
            csrf = "";
            setMe(null);
            setInviteLogin(true);
          }
        }}
        onAccepted={async (requiresLogin: boolean, tid: number | null) => {
          if (requiresLogin) {
            try {
              if (me) await api("/auth/logout", "POST");
            } catch {
              // Invitation login still clears the old local session on failure.
            } finally {
              authGeneration.current++;
              csrf = "";
              setMe(null);
            }
          }
          window.history.replaceState(null, "", window.location.pathname);
          setInvitation("");
          setInviteLogin(false);
          if (!requiresLogin) {
            await switchWorkspace(tid);
          }
          setPage("dashboard");
        }}
      />
    );
  const registrationToken = new URLSearchParams(location.hash.slice(1)).get(
    "register",
  );
  if (registrationToken)
    return <RegistrationConfirm api={api} token={registrationToken} />;
  if (!me || me.mfa_required)
    return (
      <Login
        onLogin={async () => {
          await refresh();
          setPage("dashboard");
          setInviteLogin(false);
          setError("");
        }}
      />
    );
  const can = (permission: string) => me.permissions.includes(permission);
  const pages = [
    ["dashboard", "", "Áttekintés"],
    ...(can("tenants.read") ? [["tenants", "", "Ügyfelek"]] : []),
    ...((me.tenant_id && can("products.read")) || can("reference.read")
      ? [["products", "", "Termékadatok"]]
      : []),
    ...(can("reference.read")
      ? [
          ["categories", "", "Kategóriák"],
          ["parameters", "", "Paraméterkereső"],
        ]
      : []),
    ...(me.tenant_id && can("imports.read")
      ? [["imports", "", "Beszállítói import"]]
      : []),
    ...(can("exports.fields.manage") || can("exports.read")
      ? [["export-fields", "", "Export"]]
      : []),
    ...(can("system.users.read") || can("system.roles.read")
      ? [["access-system", "", "Rendszerhozzáférések"]]
      : []),
    ...(me.tenant_id && can("members.read")
      ? [["members", "", "Munkatársak és hozzáférések"]]
      : []),
    ...(can("system.settings.read")
      ? [["settings", "", "Rendszerbeállítások"]]
      : []),
    ...((me.tenant_id ? can("audit.read") : can("system.audit.read"))
      ? [["audit", "", "Napló / Audit"]]
      : []),
  ];
  const title =
    page === "security"
      ? "Hitelesítés és 2FA"
      : pages.find((p) => p[0] === page)?.[2] || "Áttekintés";
  const visibleWorkspaces = (
    workspaceItems.length ? workspaceItems : me.workspaces || me.memberships
  ).filter(
    (m) =>
      !workspaceQuery ||
      m.name
        .toLocaleLowerCase("hu")
        .includes(workspaceQuery.toLocaleLowerCase("hu")),
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandmark">
            A<span>+</span>
          </div>
          <div>
            {branding.display_name}
            <small>{branding.system_name}</small>
          </div>
        </div>
        <div className="workspace">
          <label>
            Munkaterület keresése
            <input
              value={workspaceQuery}
              onChange={(e) => {
                WQ(e.target.value);
                WO(0);
              }}
            />
          </label>
          <label>
            Munkaterület
            <select
              aria-label="Munkaterület"
              value={me.tenant_id ?? ""}
              onChange={(e) =>
                switchWorkspace(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="" disabled={!(me.system ?? me.user.superadmin)}>
                {(me.system ?? me.user.superadmin)
                  ? "Rendszerszint"
                  : "Válassz ügyfelet"}
              </option>
              {visibleWorkspaces.map((m) => (
                <option key={m.tenant_id} value={m.tenant_id}>
                  {m.name}
                </option>
              ))}
              {me.workspace &&
                !visibleWorkspaces.some(
                  (m) => m.tenant_id === me.workspace?.tenant_id,
                ) && (
                  <option value={me.workspace.tenant_id}>
                    {me.workspace.name}
                  </option>
                )}
            </select>
          </label>
          {workspaceItems.length >= 100 && (
            <button onClick={() => WO(workspaceOffset + 100)}>
              További munkaterületek
            </button>
          )}
        </div>
        <p className="nav-label">MUNKATERÜLET</p>
        <nav>
          {pages.map(([key, , label]) => (
            <button
              key={key}
              className={
                (page === key ? "active " : "") +
                (["categories", "parameters"].includes(key) ? "nested" : "")
              }
              aria-current={page === key ? "page" : undefined}
              onClick={() => {
                setPage(key);
                setError("");
              }}
            >
              <span aria-hidden>
                <NavIcon name={key} />
              </span>
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot ok" />{" "}
          {branding.environment === "production"
            ? "Üzemi környezet"
            : "Fejlesztői környezet"}
          <small>Biztonságos közös munkaterület</small>
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
                {me.roles?.length
                  ? me.roles.map((r) => r.name).join(", ")
                  : me.user.superadmin
                    ? "Superadmin"
                    : roleNames[me.role || ""] || "Nincs aktív szerepkör"}
              </small>
            </div>
            <button onClick={() => setPage("security")}>
              <LockKeyhole size={16} />
              Biztonság
            </button>
            <button onClick={() => setPassword(true)}>Jelszó</button>
            <button
              onClick={async () => {
                setError("");
                try {
                  await api("/auth/logout", "POST");
                  authGeneration.current++;
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
        <main
          className="content"
          key={`${me.tenant_id}-${JSON.stringify(me.permissions)}-${JSON.stringify(me.resource_access)}`}
        >
          <div className="page-heading">
            <div>
              <p className="eyebrow">ADATDÚSÍTÓ / ADMINISZTRÁCIÓ</p>
              <h1>{title}</h1>
            </div>
            <span className="badge environment">
              {branding.environment === "production" ? "ÜZEMI" : "FEJLESZTŐI"}
            </span>
          </div>
          <ErrorBox message={error} />
          {me.workspace?.onboarding_state === "pending_subscription" && (
            <p className="notice">
              Munkaterületed létrejött. Az előfizetés beállításáig a
              feldolgozási funkciók nem aktívak.
            </p>
          )}
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
                    <span>
                      <Network size={24} />
                    </span>
                    <h2>Kategóriák</h2>
                    <p>Hierarchia, paraméterek és megengedett értékek.</p>
                    <b>Referenciaböngésző →</b>
                  </button>
                )}
                <button
                  className="card quick"
                  onClick={() => setPage("tenants")}
                >
                  <span>
                    <Building2 size={24} />
                  </span>
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
          {page === "access-system" && (
            <AccessWorkspace
              key="system-access"
              api={api}
              tenantId={null}
              superadmin={me.user.superadmin}
              permissions={me.permissions}
              onRefresh={refresh}
            />
          )}
          {page === "members" && me.tenant_id && (
            <AccessWorkspace
              key={me.tenant_id}
              api={api}
              tenantId={me.tenant_id}
              permissions={me.permissions}
              onRefresh={refresh}
            />
          )}
          {page === "tenants" && <Tenants me={me} onSwitch={switchWorkspace} />}{" "}
          {page === "imports" && can("imports.read") && (
            <ImportWorkspace
              key={me.tenant_id}
              api={api}
              canManage={can("imports.manage")}
              permissions={me.permissions}
            />
          )}
          {page === "export-fields" && (
            <ExportAdmin
              key={me.tenant_id}
              api={api}
              central={can("exports.fields.manage")}
              canProfile={Boolean(me.tenant_id && can("exports.profile"))}
            />
          )}
          {page === "categories" && can("reference.read") && <Categories />}
          {page === "parameters" && can("reference.read") && <Parameters />}
          {page === "audit" &&
            (me.tenant_id ? can("audit.read") : can("system.audit.read")) && (
              <AuditLog />
            )}
          {page === "settings" && can("system.settings.read") && (
            <SystemSettings
              api={api}
              canManage={can("system.settings.manage")}
              superadmin={me.user.superadmin}
              onChanged={async () => {
                await refreshBranding();
                await refresh();
              }}
            />
          )}
          {page === "security" && (
            <SecurityCenter
              api={api}
              superadmin={me.user.superadmin}
              onLogout={() => {
                authGeneration.current++;
                csrf = "";
                setMe(null);
              }}
            />
          )}
          {page === "products" &&
            (me.tenant_id && can("products.read") ? (
              <ProductData api={api} />
            ) : can("reference.read") ? (
              <Categories />
            ) : null)}
        </main>
        <footer>
          Adatdúsító · Paksi Informatika
          <span>Biztonságos, ügyfelenként elkülönített munkaterület</span>
        </footer>
      </div>
      {(password || me.user.must_change_password) && (
        <Password
          close={() => {
            if (!me.user.must_change_password) setPassword(false);
          }}
          onChanged={() => {
            setPassword(false);
            authGeneration.current++;
            csrf = "";
            setMe(null);
          }}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
