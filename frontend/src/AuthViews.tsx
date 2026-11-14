import { dateTime } from "./ui";
import React, { useEffect, useState } from "react";
import {
  startAuthentication,
  startRegistration,
} from "@simplewebauthn/browser";
import {
  KeyRound,
  ShieldCheck,
  Mail,
  Plus,
  Save,
  Trash2,
  RefreshCw,
  LogIn,
  UserPlus,
} from "lucide-react";
import { Help, Panel, IconButton } from "./ui";
type Api = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type LoginResult = {
  csrf_token?: string;
  mfa_required?: boolean;
  enrollment_required?: boolean;
  mfa_token?: string;
  recovery_codes?: string[];
};
type Setup = { secret: string; qr_svg: string; setup_token?: string | null };
async function passkey(api: Api, reauth = false) {
  const r = await api<{
    token: string;
    options: Parameters<typeof startAuthentication>[0]["optionsJSON"];
  }>("/auth/passkeys/login/options", "POST", { reauth });
  let credential;
  try {
    credential = await startAuthentication({ optionsJSON: r.options });
  } catch {
    throw new Error(
      "A passkey-azonosítás megszakadt vagy az eszköz nem használható. Próbáld újra, vagy válassz másik engedélyezett módot.",
    );
  }
  return api<LoginResult>("/auth/passkeys/login/verify", "POST", {
    token: r.token,
    credential,
  });
}
function Recovery({ codes }: { codes: string[] }) {
  return (
    <Panel title="Egyszer használható helyreállítási kódok" help="recovery">
      <p className="warning">
        Most mentsd el biztonságos helyre. Később nem olvashatók vissza.
      </p>
      <textarea
        aria-label="Helyreállítási kódok"
        readOnly
        value={codes.join("\n")}
        rows={10}
      />
    </Panel>
  );
}
function SetupView({ value }: { value: Setup }) {
  return (
    <div className="totp-setup">
      <img
        alt="TOTP aktiválási QR-kód"
        src={"data:image/svg+xml;base64," + btoa(value.qr_svg)}
      />
      <p>
        Olvasd be a QR-kódot Google Authenticatorral, Microsoft Authenticatorral
        vagy más TOTP-alkalmazással.
      </p>
      <p>
        Manuális kulcs:{" "}
        <code aria-label="TOTP manuális kulcs">{value.secret}</code>
      </p>
    </div>
  );
}
export function AuthLogin({
  api,
  onAuthenticated,
  initialMfa = "",
}: {
  api: Api;
  onAuthenticated: (csrf: string) => Promise<void>;
  initialMfa?: string;
}) {
  const [methods, M] = useState({
      password: true,
      google: false,
      passkey: false,
      registration: false,
      branding: {
        display_name: "Adatdúsító",
        system_name: "Paksi Informatika",
      },
    }),
    [mode, MODE] = useState("login"),
    [identifier, I] = useState(""),
    [password, P] = useState(""),
    [name, N] = useState(""),
    [workspace, W] = useState(""),
    [email, EM] = useState(""),
    [code, C] = useState(""),
    [token, T] = useState(initialMfa),
    [setup, SET] = useState<Setup | null>(null),
    [result, RES] = useState<LoginResult | null>(null),
    [error, E] = useState(
      new URLSearchParams(location.hash.slice(1)).get("auth_error") || "",
    ),
    [status, S] = useState(""),
    [busy, B] = useState(false);
  useEffect(() => {
    api<typeof methods>("/auth/methods")
      .then(M)
      .catch((e) => E(String(e)));
  }, []);
  async function act(fn: () => Promise<void>) {
    B(true);
    E("");
    S("");
    try {
      await fn();
    } catch (e) {
      E((e as Error).message);
    } finally {
      B(false);
    }
  }
  async function finish(r: LoginResult) {
    if (r.mfa_required) {
      T(r.mfa_token || "");
      P("");
      if (r.enrollment_required)
        SET(
          await api<Setup>("/auth/mfa/setup", "POST", { token: r.mfa_token }),
        );
      return;
    }
    if (r.recovery_codes) {
      RES(r);
      return;
    }
    if (r.csrf_token) {
      history.replaceState(null, "", location.pathname);
      await onAuthenticated(r.csrf_token);
    }
  }
  return (
    <div className="login">
      <section>
        <div className="brandmark">
          A<span>+</span>
        </div>
        <p className="eyebrow">{methods.branding.system_name}</p>
        <h1>{methods.branding.display_name}</h1>
        <p className="muted">
          {token
            ? "Második faktor ellenőrzése"
            : mode === "register"
              ? "Új ügyfélmunkaterület regisztrációja"
              : "Jelentkezz be a munkaterületedre."}
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {status && (
          <p className="notice" role="status">
            {status}
          </p>
        )}
        {result?.recovery_codes ? (
          <>
            <Recovery codes={result.recovery_codes} />
            <button
              className="primary"
              onClick={() => onAuthenticated(result.csrf_token || "")}
            >
              Elmentettem, tovább a munkaterülethez
            </button>
          </>
        ) : token ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () =>
                finish(
                  await api<LoginResult>("/auth/mfa/complete", "POST", {
                    token,
                    code,
                  }),
                ),
              );
            }}
          >
            {setup && <SetupView value={setup} />}
            <label>
              Hitelesítőkód vagy helyreállítási kód
              <input
                autoComplete="one-time-code"
                required
                autoFocus
                value={code}
                onChange={(e) => C(e.target.value)}
                maxLength={128}
              />
            </label>
            <button className="primary" disabled={busy}>
              <ShieldCheck size={17} />
              Második faktor ellenőrzése
            </button>
            {!setup && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act(async () =>
                    SET(await api<Setup>("/auth/mfa/setup", "POST", { token })),
                  )
                }
              >
                Még nincs második faktorom – TOTP beállítása
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                T("");
                SET(null);
                C("");
              }}
            >
              Vissza a bejelentkezéshez
            </button>
          </form>
        ) : mode === "register" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                const r = await api<{ message: string }>(
                  "/auth/register",
                  "POST",
                  { name, email, password, workspace },
                );
                P("");
                S(r.message);
              });
            }}
          >
            <label>
              Neved
              <input
                required
                maxLength={120}
                value={name}
                onChange={(e) => N(e.target.value)}
              />
            </label>
            <label>
              E-mail-cím
              <input
                type="email"
                required
                value={email}
                onChange={(e) => EM(e.target.value)}
              />
            </label>
            <label>
              Saját jelszó
              <input
                type="password"
                required
                minLength={12}
                autoComplete="new-password"
                value={password}
                onChange={(e) => P(e.target.value)}
              />
            </label>
            <label>
              Munkaterület neve
              <input
                required
                maxLength={120}
                value={workspace}
                onChange={(e) => W(e.target.value)}
              />
            </label>
            <Help topic="registration" label="Regisztráció súgó" />
            <button className="primary" disabled={busy}>
              <UserPlus size={16} />
              Ellenőrző levél kérése
            </button>
            <button type="button" onClick={() => MODE("login")}>
              Vissza a bejelentkezéshez
            </button>
          </form>
        ) : (
          <>
            {methods.password && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  act(async () =>
                    finish(
                      await api<LoginResult>("/auth/login", "POST", {
                        identifier,
                        password,
                      }),
                    ),
                  );
                }}
              >
                <label>
                  Felhasználónév vagy e-mail-cím
                  <input
                    type="text"
                    name="identifier"
                    required
                    autoComplete="username"
                    value={identifier}
                    maxLength={254}
                    onChange={(e) => I(e.target.value)}
                  />
                </label>
                <label>
                  Jelszó
                  <input
                    type="password"
                    required
                    name="password"
                    autoComplete="current-password"
                    value={password}
                    maxLength={128}
                    onChange={(e) => P(e.target.value)}
                  />
                </label>
                <button className="primary" disabled={busy}>
                  <LogIn size={16} />
                  {busy ? "Bejelentkezés…" : "Bejelentkezés →"}
                </button>
              </form>
            )}
            <div className="auth-methods">
              {methods.passkey && (
                <button
                  disabled={busy}
                  onClick={() => act(async () => finish(await passkey(api)))}
                >
                  <KeyRound size={18} />
                  Bejelentkezés passkeyjel
                </button>
              )}
              {methods.google && (
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const r = await api<{ url: string }>(
                        "/auth/google/start",
                        "POST",
                        { link: false },
                      );
                      location.assign(r.url);
                    })
                  }
                >
                  Bejelentkezés Google-fiókkal
                </button>
              )}
              {methods.registration && (
                <button
                  onClick={() => {
                    MODE("register");
                    P("");
                  }}
                >
                  <UserPlus size={17} />
                  Új munkaterület regisztrációja
                </button>
              )}
            </div>
          </>
        )}
      </section>
      <aside>
        <ShieldCheck size={64} aria-hidden />
        <span>
          Rendezett adatok.
          <br />
          Átlátható munka.
        </span>
        <p>
          Ügyfelek, felhasználók és kategória és termékparaméter
          referenciaadatok egy helyen.
        </p>
      </aside>
    </div>
  );
}
export function RegistrationConfirm({
  api,
  token,
}: {
  api: Api;
  token: string;
}) {
  const [status, S] = useState(""),
    [error, E] = useState(""),
    [busy, B] = useState(false);
  return (
    <div className="boot">
      <Panel title="E-mailes regisztráció megerősítése" help="registration">
        <p>
          A megerősítés létrehozza a munkaterületedet. Az előfizetés
          beállításáig az import nem aktív.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {status ? (
          <>
            <p role="status">{status}</p>
            <button
              onClick={() => {
                history.replaceState(null, "", location.pathname);
                location.reload();
              }}
            >
              Tovább a bejelentkezéshez
            </button>
          </>
        ) : (
          <button
            className="primary"
            disabled={busy}
            onClick={async () => {
              B(true);
              E("");
              try {
                S(
                  (
                    await api<{ message: string }>(
                      "/auth/register/confirm",
                      "POST",
                      { token },
                    )
                  ).message,
                );
              } catch (e) {
                E((e as Error).message);
              } finally {
                B(false);
              }
            }}
          >
            E-mail ellenőrzése és munkaterület létrehozása
          </button>
        )}
      </Panel>
    </div>
  );
}

type Security = {
  username: string;
  email: string | null;
  email_verified: boolean;
  mfa_enabled: boolean;
  totp_devices: { name: string; created_at: string }[];
  recovery_remaining: number;
  google_linked: boolean;
  passkeys: {
    id: number;
    name: string;
    created_at: string;
    last_used_at: string | null;
  }[];
};
export function SecurityCenter({
  api,
  superadmin = false,
  onLogout,
}: {
  api: Api;
  superadmin?: boolean;
  onLogout: () => void;
}) {
  const [data, D] = useState<Security | null>(null),
    [methods, M] = useState({ password: true, google: false, passkey: false }),
    [password, P] = useState(""),
    [code, C] = useState(""),
    [username, U] = useState(""),
    [setup, SET] = useState<Setup | null>(null),
    [codes, CO] = useState<string[]>([]),
    [keyname, K] = useState("Saját eszköz"),
    [sessions, SE] = useState<
      {
        id: string;
        current: boolean;
        method: string;
        mfa: boolean;
        created_at: string;
        expires_at: string;
      }[]
    >([]),
    [busy, B] = useState(false),
    [error, E] = useState(""),
    [status, S] = useState("");
  async function load() {
    const d = await api<Security>("/auth/security");
    D(d);
    U(d.username);
    SE(await api("/auth/sessions"));
    M(await api("/auth/methods"));
  }
  useEffect(() => {
    load().catch((e) => E(String(e)));
  }, []);
  async function act(fn: () => Promise<void>) {
    E("");
    S("");
    B(true);
    try {
      await fn();
    } catch (e) {
      E((e as Error).message);
    } finally {
      B(false);
    }
  }
  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {status && (
        <p className="notice" role="status">
          {status}
        </p>
      )}
      <Panel title="Saját fiók és újraazonosítás" help="security">
        <p>
          A hitelesítési eszközök és biztonsági beállítások módosításához öt
          percen belüli újraazonosítás kell.
        </p>
        {methods.password && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                await api("/auth/reauth", "POST", { password, code });
                P("");
                C("");
                S("Újraazonosítás sikeres, öt percig érvényes.");
              });
            }}
          >
            <div className="form-grid">
              <label>
                Jelenlegi jelszó
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => P(e.target.value)}
                />
              </label>
              {data?.mfa_enabled && (
                <label>
                  Második faktor
                  <input
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(e) => C(e.target.value)}
                    required
                  />
                </label>
              )}
            </div>
            <button disabled={busy}>
              <KeyRound size={16} />
              Újraazonosítás
            </button>
          </form>
        )}
        {methods.passkey && (
          <button
            disabled={busy}
            onClick={() =>
              act(async () => {
                await passkey(api, true);
                S("Újraazonosítás passkeyjel sikeres.");
              })
            }
          >
            Újraazonosítás passkeyjel
          </button>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await api("/auth/username", "PUT", { username });
              await load();
              S("Felhasználónév mentve.");
            });
          }}
        >
          <label>
            Felhasználónév
            <input
              required
              minLength={3}
              maxLength={80}
              pattern="[a-z0-9][a-z0-9._-]{2,79}"
              value={username}
              onChange={(e) => U(e.target.value.toLowerCase())}
            />
          </label>
          <small>Ezzel vagy a meglévő e-mail-címeddel jelentkezhetsz be.</small>
          <button disabled={busy}>
            <Save size={16} />
            Felhasználónév mentése
          </button>
        </form>
      </Panel>
      <Panel title="TOTP és helyreállítási kódok" help="recovery">
        <ul className="resource-list">
          {data?.totp_devices?.map((d) => (
            <li key={d.name}>
              <span>
                <strong>{d.name}</strong>
                <small>
                  Aktivált profil, létrehozva: {dateTime(d.created_at)}
                </small>
              </span>
            </li>
          ))}
        </ul>
        <p>
          Állapot:{" "}
          {data?.mfa_enabled ? "Aktív TOTP-eszköz" : "Nincs aktív TOTP-eszköz"}.
          Felhasználható helyreállítási kódok: {data?.recovery_remaining ?? 0}.
        </p>
        {!data?.mfa_enabled && !setup && (
          <button
            disabled={busy}
            onClick={() =>
              act(async () => SET(await api<Setup>("/auth/totp/setup", "POST")))
            }
          >
            <Plus size={16} />
            TOTP beállítása
          </button>
        )}
        {setup && (
          <>
            <SetupView value={setup} />
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  const r = await api<{ recovery_codes: string[] }>(
                    "/auth/totp/confirm",
                    "POST",
                    { code, setup_token: setup?.setup_token || undefined },
                  );
                  CO(r.recovery_codes);
                  SET(null);
                  C("");
                  await load();
                  S("A TOTP-védelem aktív, a többi munkamenet visszavonva.");
                });
              }}
            >
              <label>
                Aktiválási ellenőrzőkód
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  pattern="[0-9]{6}"
                  value={code}
                  onChange={(e) => C(e.target.value)}
                />
              </label>
              <button className="primary" disabled={busy}>
                TOTP aktiválása
              </button>
            </form>
          </>
        )}
        {data?.mfa_enabled && (
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                act(async () =>
                  SET(await api<Setup>("/auth/totp/setup", "POST")),
                )
              }
            >
              <RefreshCw size={16} />
              TOTP-eszköz cseréje
            </button>
            <button
              disabled={busy}
              onClick={() =>
                act(async () => {
                  CO(
                    (
                      await api<{ recovery_codes: string[] }>(
                        "/auth/recovery/rotate",
                        "POST",
                      )
                    ).recovery_codes,
                  );
                  await load();
                })
              }
            >
              <RefreshCw size={16} />
              Új helyreállítási kódok
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  await api("/auth/totp/disable", "POST");
                  onLogout();
                })
              }
            >
              <Trash2 size={16} />
              TOTP visszavonása és kijelentkezés
            </button>
          </div>
        )}
      </Panel>
      {codes.length > 0 && <Recovery codes={codes} />}
      <Panel title="Passkey hitelesítőeszközök" help="passkey">
        {!methods.passkey ? (
          <p>A központi szabályzat jelenleg nem engedélyezi a passkeyt.</p>
        ) : (
          <>
            <label>
              Eszköz megnevezése
              <input
                maxLength={120}
                value={keyname}
                onChange={(e) => K(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !keyname.trim()}
              onClick={() =>
                act(async () => {
                  const r = await api<{
                    token: string;
                    options: Parameters<
                      typeof startRegistration
                    >[0]["optionsJSON"];
                  }>("/auth/passkeys/register/options", "POST");
                  let credential;
                  try {
                    credential = await startRegistration({
                      optionsJSON: r.options,
                    });
                  } catch {
                    throw new Error(
                      "A passkey regisztrációja megszakadt. HTTPS-kapcsolat és felhasználó-ellenőrzésre képes eszköz szükséges.",
                    );
                  }
                  await api("/auth/passkeys/register/verify", "POST", {
                    token: r.token,
                    credential,
                    name: keyname,
                  });
                  await load();
                  S("Passkey regisztrálva.");
                })
              }
            >
              <Plus size={16} />
              Passkey hozzáadása
            </button>
          </>
        )}
        <ul className="resource-list">
          {data?.passkeys.map((p) => (
            <li key={p.id}>
              <span>
                <strong>{p.name}</strong>
                <small>Létrehozva: {dateTime(p.created_at)}</small>
              </span>
              <IconButton
                icon={Trash2}
                label={`Passkey törlése: ${p.name}`}
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await api(`/auth/passkeys/${p.id}`, "DELETE");
                    await load();
                  })
                }
              />
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Google-fiók összekapcsolása" help="auth">
        <p>
          {data?.google_linked
            ? "Google-fiók hozzákapcsolva."
            : "Nincs Google-fiók hozzákapcsolva. Az e-mail-egyezés önmagában nem kapcsol össze fiókokat."}
        </p>
        {methods.google && (
          <button
            disabled={busy}
            onClick={() =>
              act(async () => {
                if (data?.google_linked) {
                  await api("/auth/google/link", "DELETE");
                  await load();
                } else {
                  const r = await api<{ url: string }>(
                    "/auth/google/start",
                    "POST",
                    { link: true },
                  );
                  location.assign(r.url);
                }
              })
            }
          >
            {data?.google_linked
              ? "Google-kapcsolat megszüntetése"
              : "Saját Google-fiók összekapcsolása"}
          </button>
        )}
      </Panel>
      <Panel title="Aktív munkamenetek" help="security">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Munkamenet</th>
                <th>Bejelentkezési mód</th>
                <th>Lejárat</th>
                <th>Művelet</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.current ? "Ez az eszköz" : "Másik munkamenet"}</td>
                  <td>
                    {(
                      {
                        password: "Jelszó",
                        google: "Google OIDC",
                        passkey: "Passkey",
                      } as Record<string, string>
                    )[s.method] || s.method}
                    {s.mfa ? " · Második faktor ellenőrizve" : ""}
                  </td>
                  <td>{dateTime(s.expires_at)}</td>
                  <td>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await api(`/auth/sessions/${s.id}`, "DELETE");
                          if (s.current) onLogout();
                          else await load();
                        })
                      }
                    >
                      Visszavonás
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {superadmin && <AdminRecovery api={api} />}
    </>
  );
}
export function CreateSystemUser({
  api,
  roles,
  onCreated,
}: {
  api: Api;
  roles: { id: number; name: string; protected: boolean }[];
  onCreated: () => Promise<void>;
}) {
  const [name, N] = useState(""),
    [username, U] = useState(""),
    [email, E] = useState(""),
    [password, P] = useState(""),
    [active, A] = useState(true),
    [ids, I] = useState<number[]>([]),
    [busy, B] = useState(false),
    [error, ERR] = useState(""),
    [status, S] = useState("");
  return (
    <details className="account-create">
      <summary className="field-title">
        <UserPlus size={18} />
        Új rendszerfelhasználó
      </summary>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          B(true);
          ERR("");
          S("");
          try {
            await api("/auth/system-users", "POST", {
              name,
              username,
              email: email || null,
              password,
              active,
              roles: ids,
            });
            P("");
            S("Fiók létrehozva; az első belépéskor jelszócsere szükséges.");
            await onCreated();
          } catch (e) {
            ERR((e as Error).message);
          } finally {
            B(false);
          }
        }}
      >
        <div className="form-grid">
          <label>
            Név
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => N(e.target.value)}
            />
          </label>
          <label>
            Egyedi felhasználónév
            <input
              required
              pattern="[a-z0-9][a-z0-9._-]{2,79}"
              maxLength={80}
              value={username}
              onChange={(e) => U(e.target.value.toLowerCase())}
            />
          </label>
          <label>
            E-mail-cím (opcionális)
            <input
              type="email"
              value={email}
              onChange={(e) => E(e.target.value)}
            />
          </label>
          <label>
            Ideiglenes jelszó
            <input
              type="password"
              required
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              value={password}
              onChange={(e) => P(e.target.value)}
            />
          </label>
        </div>
        <fieldset>
          <legend>Rendszerszerepkörök</legend>
          {roles
            .filter((r) => !r.protected)
            .map((r) => (
              <label className="check" key={r.id}>
                <input
                  type="checkbox"
                  aria-label={`Új fiók szerepköre: ${r.name}`}
                  checked={ids.includes(r.id)}
                  onChange={(e) =>
                    I(
                      e.target.checked
                        ? [...ids, r.id]
                        : ids.filter((x) => x !== r.id),
                    )
                  }
                />
                {r.name}
              </label>
            ))}
        </fieldset>
        <label className="check">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => A(e.target.checked)}
          />
          Aktív fiók
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {status && <p role="status">{status}</p>}
        <button className="primary" disabled={busy}>
          <Save size={16} />
          Rendszerfelhasználó létrehozása
        </button>
      </form>
    </details>
  );
}
export function AdminPasswordReset({ api, id }: { api: Api; id: number }) {
  const [pwd, P] = useState(""),
    [reason, R] = useState(""),
    [status, S] = useState("");
  return (
    <details>
      <summary>Adminisztrátori ideiglenes jelszó</summary>
      <p>
        Friss újraazonosítás szükséges. Nem kapcsolja ki a második faktort,
        minden munkamenetet visszavon.
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api(`/auth/system-users/${id}/reset-password`, "POST", {
              password: pwd,
              reason,
            });
            P("");
            S("Ideiglenes jelszó beállítva, első belépéskor cserélendő.");
          } catch (e) {
            S((e as Error).message);
          }
        }}
      >
        <label>
          Új ideiglenes jelszó
          <input
            required
            type="password"
            minLength={12}
            autoComplete="new-password"
            value={pwd}
            onChange={(e) => P(e.target.value)}
          />
        </label>
        <label>
          Személyazonosság-ellenőrzés és indok
          <input
            required
            minLength={10}
            maxLength={500}
            value={reason}
            onChange={(e) => R(e.target.value)}
          />
        </label>
        <button>Ideiglenes jelszó beállítása</button>
        <p role="status">{status}</p>
      </form>
    </details>
  );
}
function AdminRecovery({ api }: { api: Api }) {
  const [q, Q] = useState(""),
    [users, U] = useState<{ id: number; name: string; email: string | null }[]>(
      [],
    ),
    [id, I] = useState(""),
    [reason, R] = useState(""),
    [token, T] = useState(""),
    [result, S] = useState("");
  useEffect(() => {
    if (q.length < 3) {
      U([]);
      return;
    }
    const timer = setTimeout(
      () =>
        api<{ items: typeof users }>("/users?q=" + encodeURIComponent(q))
          .then((r) => U(r.items))
          .catch((e) => S(String(e))),
      300,
    );
    return () => clearTimeout(timer);
  }, [q]);
  return (
    <Panel title="Felügyelt TOTP-helyreállítás" help="recoveryAdmin">
      <label>
        Érintett felhasználó keresése
        <input value={q} onChange={(e) => Q(e.target.value)} />
      </label>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api<{ approval_token: string; message: string }>(
              "/auth/admin-recovery/request",
              "POST",
              { user_id: Number(id), reason },
            );
            T(r.approval_token);
            S(r.message);
          } catch (e) {
            S((e as Error).message);
          }
        }}
      >
        <label>
          Érintett fiók
          <select required value={id} onChange={(e) => I(e.target.value)}>
            <option value="">Válassz felhasználót</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
                {u.email ? ` · ${u.email}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Az ellenőrzés dokumentált indoka
          <textarea
            required
            minLength={20}
            maxLength={500}
            value={reason}
            onChange={(e) => R(e.target.value)}
          />
        </label>
        <button>Helyreállítás jóváhagyásának kérése</button>
      </form>
      <label>
        Másik superadminnak átadandó / jóváhagyandó egyszeri kérés
        <input
          autoComplete="off"
          value={token}
          onChange={(e) => T(e.target.value)}
        />
      </label>
      <button
        disabled={!token}
        onClick={async () => {
          try {
            await api("/auth/admin-recovery/approve", "POST", { token });
            T("");
            S("Helyreállítás jóváhagyva; új TOTP-beállítás szükséges.");
          } catch (e) {
            S((e as Error).message);
          }
        }}
      >
        Másik superadminként jóváhagyom
      </button>
      <p role="status">{result}</p>
    </Panel>
  );
}
