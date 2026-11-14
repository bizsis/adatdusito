import React, { useEffect, useState } from "react";
import {
  Settings2,
  Mail,
  KeyRound,
  ShieldCheck,
  LockKeyhole,
  Save,
  Send,
  PlugZap,
} from "lucide-react";
import { Help, Panel, FieldTitle } from "./ui";
type Api = <T>(url: string, method?: string, body?: unknown) => Promise<T>;
type Settings = {
  general: Record<string, string>;
  smtp: {
    host: string;
    port: number;
    security: string;
    username: string;
    from_email: string;
    from_name: string;
    password_set: boolean;
    source: string;
  };
  auth: {
    password: boolean;
    google: boolean;
    passkey: boolean;
    google_client_id: string;
    google_secret_set: boolean;
    registration: boolean;
  };
  mfa: { enabled: boolean; required_roles: number[]; passkey_mfa: boolean };
  security: Record<string, number>;
  roles: {
    id: number;
    name: string;
    owner: string;
    protected: boolean;
    tenant_name?: string;
  }[];
};
export function SystemSettings({
  api,
  canManage,
  superadmin,
  onChanged,
}: {
  api: Api;
  canManage: boolean;
  superadmin: boolean;
  onChanged: () => Promise<void>;
}) {
  const [data, D] = useState<Settings | null>(null),
    [tab, T] = useState("general"),
    [error, E] = useState(""),
    [status, S] = useState(""),
    [busy, B] = useState(false),
    [password, P] = useState(""),
    [secret, G] = useState(""),
    [recipient, R] = useState("");
  async function load() {
    D(await api<Settings>("/system/settings"));
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
  async function save(group: string, value: unknown) {
    await api("/system/settings/" + group, "PUT", value);
    P("");
    G("");
    await load();
    await onChanged();
    S("A beállítások mentve, újraindítás nélkül érvényesek.");
  }
  if (!data)
    return (
      <Panel title="Rendszerbeállítások">
        <p role={error ? "alert" : "status"}>
          {error || "Beállítások betöltése…"}
        </p>
      </Panel>
    );
  const patch = (group: keyof Settings, key: string, value: unknown) =>
    D({ ...data, [group]: { ...data[group], [key]: value } });
  const smtp = () => ({
    ...data.smtp,
    password: password || undefined,
    source: undefined,
    password_set: undefined,
  });
  const disabled = busy || !canManage;
  return (
    <>
      <div className="tabs" role="tablist" aria-label="Rendszerbeállítások">
        {[
          ["general", "Általános", Settings2],
          ["smtp", "SMTP / Levelezés", Mail],
          ["auth", "Hitelesítés és bejelentkezés", KeyRound],
          ["mfa", "Kétfaktoros hitelesítés", ShieldCheck],
          ["security", "Biztonsági szabályok", LockKeyhole],
        ].map(([key, name, Icon]) => (
          <button
            key={String(key)}
            role="tab"
            aria-selected={tab === key}
            onClick={() => T(String(key))}
          >
            {React.createElement(Icon as typeof Settings2, {
              size: 18,
              "aria-hidden": true,
            })}
            {String(name)}
          </button>
        ))}
      </div>
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
      {!canManage && (
        <p className="notice">
          A beállításokat megtekintheted; módosításhoz kezelési jogosultság
          szükséges.
        </p>
      )}
      <Panel
        title={
          {
            general: "Általános rendszerbeállítások",
            smtp: "SMTP és levelezés",
            auth: "Hitelesítés és bejelentkezés",
            mfa: "Kétfaktoros hitelesítés",
            security: "Biztonsági szabályok",
          }[tab] || "Beállítások"
        }
        help={
          tab === "general"
            ? undefined
            : tab === "security"
              ? "security"
              : (tab as "smtp" | "auth" | "mfa")
        }
      >
        {tab === "general" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() => save("general", data.general));
            }}
          >
            <div className="form-grid">
              {[
                ["display_name", "Alkalmazás megjelenített neve"],
                ["system_name", "Rendszer megnevezése"],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    required
                    maxLength={key === "display_name" ? 80 : 120}
                    disabled={disabled}
                    value={data.general[key]}
                    onChange={(e) => patch("general", key, e.target.value)}
                  />
                </label>
              ))}
              <label>
                Alapértelmezett nyelv
                <select
                  disabled={disabled}
                  value={data.general.language}
                  onChange={(e) => patch("general", "language", e.target.value)}
                >
                  <option value="hu">Magyar</option>
                </select>
              </label>
              <label>
                Alapértelmezett időzóna
                <input
                  required
                  disabled={disabled}
                  value={data.general.timezone}
                  onChange={(e) => patch("general", "timezone", e.target.value)}
                />
                <small>
                  Például Europe/Budapest vagy UTC. A megjelenített időpontokra
                  vonatkozik.
                </small>
              </label>
              <label>
                Környezet megjelenítése
                <select
                  disabled={disabled}
                  value={data.general.environment}
                  onChange={(e) =>
                    patch("general", "environment", e.target.value)
                  }
                >
                  <option value="development">Fejlesztői</option>
                  <option value="production">Üzemi</option>
                </select>
                <small>
                  Megjelenítési címke, nem telepít másik környezetet.
                </small>
              </label>
            </div>
            <button className="primary" disabled={disabled}>
              <Save size={16} />
              Általános beállítások mentése
            </button>
          </form>
        )}
        {tab === "smtp" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() => save("smtp", smtp()));
            }}
          >
            <p className="muted">
              Aktív forrás:{" "}
              {data.smtp.source === "database"
                ? "Titkosított webes beállítás"
                : "Üzemeltetői környezet"}
              .
            </p>
            <div className="form-grid">
              <label>
                SMTP-kiszolgáló
                <input
                  required
                  disabled={disabled}
                  maxLength={253}
                  value={data.smtp.host}
                  onChange={(e) => patch("smtp", "host", e.target.value)}
                />
              </label>
              <label>
                Port
                <input
                  type="number"
                  min={1}
                  max={65535}
                  required
                  disabled={disabled}
                  value={data.smtp.port}
                  onChange={(e) =>
                    patch("smtp", "port", Number(e.target.value))
                  }
                />
              </label>
              <label>
                Titkosítás
                <select
                  disabled={disabled}
                  aria-label="Titkosítás"
                  value={data.smtp.security}
                  onChange={(e) => patch("smtp", "security", e.target.value)}
                >
                  <option value="starttls">STARTTLS</option>
                  <option value="tls">TLS</option>
                </select>
              </label>
              <label>
                SMTP-felhasználónév
                <input
                  disabled={disabled}
                  maxLength={254}
                  autoComplete="off"
                  value={data.smtp.username}
                  onChange={(e) => patch("smtp", "username", e.target.value)}
                />
              </label>
              <label>
                <FieldTitle topic="secret">SMTP-jelszó</FieldTitle>
                <input
                  disabled={disabled}
                  type="password"
                  aria-label="SMTP-jelszó"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => P(e.target.value)}
                  placeholder={
                    data.smtp.password_set
                      ? "Beállítva – üresen hagyva megmarad"
                      : "Nincs beállítva"
                  }
                />
              </label>
              <label>
                Feladó e-mail-címe
                <input
                  required
                  type="email"
                  disabled={disabled}
                  value={data.smtp.from_email}
                  onChange={(e) => patch("smtp", "from_email", e.target.value)}
                />
              </label>
              <label>
                Feladó megjelenített neve
                <input
                  required
                  disabled={disabled}
                  maxLength={120}
                  value={data.smtp.from_name}
                  onChange={(e) => patch("smtp", "from_name", e.target.value)}
                />
              </label>
            </div>
            <button className="primary" disabled={disabled}>
              <Save size={16} />
              SMTP ellenőrzése és mentése
            </button>
            <p>
              Meghívók érvényessége: {data.security.invite_ttl_hours} óra.{" "}
              <button type="button" onClick={() => T("security")}>
                Meghívók lejáratának módosítása
              </button>
            </p>
            <hr />
            <h3 className="field-title">
              Kapcsolat és tesztlevél
              <Help topic="smtpTest" />
            </h3>
            <label>
              Tesztlevél címzettje
              <input
                type="email"
                value={recipient}
                onChange={(e) => R(e.target.value)}
                disabled={disabled}
              />
            </label>
            <div className="actions">
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  act(async () => {
                    const r = await api<{
                      message: string;
                      encrypted: boolean;
                      authentication: string;
                    }>("/system/settings/smtp/test", "POST", {
                      config: smtp(),
                    });
                    S(
                      r.message +
                        ` Titkosított kapcsolat: ${r.encrypted ? "igen" : "nem"}. Hitelesítés: ${r.authentication === "success" ? "sikeres" : "nincs beállítva"}.`,
                    );
                  })
                }
              >
                <PlugZap size={16} />
                Kapcsolat tesztelése
              </button>
              <button
                type="button"
                disabled={disabled || !recipient}
                onClick={() =>
                  act(async () => {
                    const r = await api<{ message: string }>(
                      "/system/settings/smtp/test",
                      "POST",
                      { config: smtp(), recipient },
                    );
                    S(r.message);
                  })
                }
              >
                <Send size={16} />
                Tesztlevél küldése
              </button>
            </div>
          </form>
        )}
        {tab === "auth" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() =>
                save("auth", {
                  ...data.auth,
                  google_secret_set: undefined,
                  google_client_secret: secret || undefined,
                }),
              );
            }}
          >
            {!superadmin && (
              <p className="notice">
                A hitelesítési módokat csak superadmin módosíthatja.
              </p>
            )}
            <fieldset disabled={disabled || !superadmin}>
              <legend>Engedélyezett bejelentkezési módok</legend>
              {[
                ["password", "Felhasználónév vagy e-mail + jelszó"],
                ["google", "Google OIDC"],
                ["passkey", "Passkey / WebAuthn"],
              ].map(([key, label]) => (
                <label className="check" key={key}>
                  <input
                    type="checkbox"
                    checked={Boolean(data.auth[key as keyof typeof data.auth])}
                    onChange={(e) => patch("auth", key, e.target.checked)}
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <div className="form-grid">
              <label>
                Google OIDC kliensazonosító
                <input
                  disabled={disabled || !superadmin}
                  maxLength={254}
                  value={data.auth.google_client_id}
                  onChange={(e) =>
                    patch("auth", "google_client_id", e.target.value)
                  }
                />
                <small>
                  A Google Cloudban a webes klienshez kapott
                  .apps.googleusercontent.com azonosító.
                </small>
              </label>
              <label>
                <FieldTitle topic="secret">Google OIDC kliens titka</FieldTitle>
                <input
                  type="password"
                  aria-label="Google OIDC kliens titka"
                  autoComplete="new-password"
                  disabled={disabled || !superadmin}
                  value={secret}
                  onChange={(e) => G(e.target.value)}
                  placeholder={
                    data.auth.google_secret_set
                      ? "Beállítva – üresen hagyva megmarad"
                      : "Nincs beállítva"
                  }
                />
              </label>
            </div>
            <p>
              Engedélyezett visszahívási cím:{" "}
              <code>{location.origin}/api/v1/auth/google/callback</code>
            </p>
            <label className="check">
              <input
                type="checkbox"
                disabled={disabled || !superadmin}
                checked={data.auth.registration}
                onChange={(e) =>
                  patch("auth", "registration", e.target.checked)
                }
              />
              Nyilvános e-mailes regisztráció
            </label>
            <Help topic="registration" label="Nyilvános regisztráció súgó" />
            <button disabled={disabled || !superadmin} className="primary">
              <Save size={16} />
              Hitelesítési módok mentése
            </button>
          </form>
        )}
        {tab === "mfa" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() => save("mfa", data.mfa));
            }}
          >
            <label className="check">
              <input
                type="checkbox"
                disabled={disabled || !superadmin}
                checked={data.mfa.enabled}
                onChange={(e) => patch("mfa", "enabled", e.target.checked)}
              />
              Új TOTP-aktiválás engedélyezése
            </label>
            <p className="muted">
              A már aktív TOTP-védelmet ez a kapcsoló nem kerüli meg.
            </p>
            <label className="check">
              <input
                type="checkbox"
                disabled={disabled || !superadmin}
                checked={data.mfa.passkey_mfa}
                onChange={(e) => patch("mfa", "passkey_mfa", e.target.checked)}
              />
              Ellenőrzött felhasználó-azonosítású passkey elfogadása második
              faktorként
            </label>
            <fieldset disabled={disabled || !superadmin}>
              <legend>Második faktorra kötelezett szerepkörök</legend>
              {data.roles.map((r) => (
                <label className="check" key={r.id}>
                  <input
                    type="checkbox"
                    checked={data.mfa.required_roles.includes(r.id)}
                    onChange={(e) =>
                      patch(
                        "mfa",
                        "required_roles",
                        e.target.checked
                          ? [...data.mfa.required_roles, r.id]
                          : data.mfa.required_roles.filter((x) => x !== r.id),
                      )
                    }
                  />
                  {r.name}
                  <small>
                    {r.owner === "system"
                      ? "Rendszerszint"
                      : r.owner === "template"
                        ? "Ügyfélszerepkör-sablon"
                        : r.tenant_name || "Helyi ügyfélszerepkör"}
                  </small>
                </label>
              ))}
            </fieldset>
            <button disabled={disabled || !superadmin} className="primary">
              <Save size={16} />
              2FA-szabályok mentése
            </button>
          </form>
        )}
        {tab === "security" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() => save("security", data.security));
            }}
          >
            <div className="form-grid">
              {[
                ["session_hours", "Munkamenet élettartama (óra)", 1, 24],
                ["login_attempts", "Belépési kísérletek korlátja", 3, 20],
                ["login_window_minutes", "Korlátozási időablak (perc)", 5, 60],
                ["password_min_length", "Jelszó minimális hossza", 12, 64],
                ["invite_ttl_hours", "Meghívók érvényessége (óra)", 1, 168],
              ].map(([key, label, min, max]) => (
                <label key={String(key)}>
                  {String(label)}
                  <input
                    type="number"
                    required
                    min={Number(min)}
                    max={Number(max)}
                    disabled={disabled || !superadmin}
                    value={data.security[String(key)]}
                    onChange={(e) =>
                      patch("security", String(key), Number(e.target.value))
                    }
                  />
                </label>
              ))}
            </div>
            <p>
              Az aktív munkameneteket a felső menü Biztonság oldalán nézheted
              meg és vonhatod vissza.
            </p>
            <button disabled={disabled || !superadmin} className="primary">
              <Save size={16} />
              Biztonsági szabályok mentése
            </button>
          </form>
        )}
      </Panel>
    </>
  );
}
