import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiHttpError } from "../apiResponse";
import type { Request } from "../classification/category02Contract";
import { usePresentationRead } from "../classification/usePresentationRead";
import { ParameterWorkspace } from "./ParameterWorkspace";
import { LiveSlotEditor } from "./LiveSlotEditor";
import { LiveAliases } from "./LiveAliases";
import { LiveRuns } from "./LiveRuns";
import { parameterApi } from "./liveApi";
import {
  decodeProductContext,
  type Parameters,
  type ServerPreview,
  type ParameterAccess,
  type Slot,
  type RunScope,
} from "./liveContract";
import {
  ParameterRevisionConflict,
  type ParameterPorts,
  type ParameterRow,
  type ParameterValue,
} from "./presentation";

type Context = ReturnType<typeof decodeProductContext>;
type Snapshot = { stored: Parameters; preview: ServerPreview; meta: Context };
const reasonLabels: Record<string, string> = {
  exact_label_match: "Igazolt címkeegyezés",
  approved_alias: "Jóváhagyott alias",
  unit_converted: "Igazolt egységkonverzió",
  similar_label: "Hasonló címke; felülvizsgálat szükséges",
  unit_unverified: "Nem igazolt mértékegység",
  unit_mismatch: "Eltérő mértékegység",
  not_numeric: "Számérték szükséges",
  value_not_allowed: "Az érték nincs a megengedett listában",
  conflicting_sources: "Ellentmondó forrásértékek",
  would_overwrite_value: "Meglévő érték védve; új jelölt külön",
  ambiguous_number: "Kétértelmű számformátum",
  donor_param_without_source: "Hiányzó forrásadat; üres hely",
  donor_not_ready: "A donor nem kész automatikus paraméterkiegészítésre",
  source_changed_locked: "A forrás változott, a kézi érték védett",
  source_refreshed: "Frissült forrásadat",
  profile_changed: "Korábbi profilból megőrizve",
  manual_decision: "Kézi döntés",
};
function row(slot: Slot, snapshot: Snapshot): ParameterRow {
  const saved = snapshot.stored.slots.find((s) => s.slot_key === slot.slot_key);
  const sourceValue = (
    s: Slot["sources"][number],
    normalized: string | null,
  ): ParameterValue => ({
    raw: s.raw,
    rawUnit: s.unit,
    normalized,
    unit: slot.unit,
    source: `${s.header} · Futás ${s.run_id}, sor ${s.line}${s.present ? "" : " · A legutóbbi forrásból hiányzott"}`,
    conversionNote: slot.unit_conversion
      ? `${slot.unit_conversion.from} → ${slot.unit_conversion.to}; szorzó: ${slot.unit_conversion.factor}; eredeti szám: ${slot.unit_conversion.raw_number}`
      : "",
  });
  const first = slot.sources[0];
  const additional = slot.sources.slice(1).map((s, i) => ({
    key: `source-${s.key}-${i}`,
    title: `Megőrzött forrás: ${s.header}`,
    value: sourceValue(s, null),
  }));
  for (const s of slot.pending_source || [])
    additional.push({
      key: `pending-${s.key}`,
      title: "Új, el nem fogadott forrás",
      value: sourceValue(s, null),
    });
  // c05746d does not serialize pending_source, but the product endpoint exposes
  // current source attributes. Only explicit identical source keys are joined.
  if (
    slot.locked &&
    slot.reason_codes.includes("source_changed_locked") &&
    !slot.pending_source?.length
  ) {
    for (const old of slot.sources) {
      const latest = snapshot.meta.source_attributes.find(
        (s) => s.key === old.key,
      );
      if (latest && latest.raw !== old.raw)
        additional.push({
          key: `current-${latest.key}`,
          title: "Aktuális termékforrás – még nem elfogadott",
          value: {
            raw: latest.raw,
            rawUnit: latest.unit,
            normalized: null,
            unit: null,
            source: `${latest.header} · Futás ${latest.run_id}, sor ${latest.line}`,
            conversionNote: "",
          },
        });
    }
  }
  for (const candidate of slot.candidates) {
    if (!candidate.source_key || !candidate.header) continue;
    const current = snapshot.meta.source_attributes.find(
      (s) => s.key === candidate.source_key,
    );
    additional.push({
      key: `candidate-${candidate.source_key}`,
      title: `Nem elfogadott forrásjelölt: ${candidate.header}`,
      value: {
        raw: candidate.raw ?? null,
        rawUnit: current?.unit ?? null,
        normalized: null,
        unit: null,
        source: current
          ? `${current.header} · Futás ${current.run_id}, sor ${current.line}`
          : candidate.source_key,
        conversionNote: "",
      },
    });
  }
  const events = snapshot.meta.events.filter(
    (e) =>
      e.before?.slot_key === slot.slot_key ||
      e.after?.slot_key === slot.slot_key,
  );
  return {
    key: slot.slot_key,
    status: slot.state,
    match:
      slot.state === "source_only" ||
      slot.state === "detached" ||
      slot.state === "missing"
        ? "none"
        : slot.state === "review" || slot.state === "conflict"
          ? "ambiguous"
          : "confirmed",
    explanation: slot.reason_codes.map((r) => reasonLabels[r] || r).join(" · "),
    own: first
      ? {
          key: first.key,
          title: first.header,
          required: null,
          value: sourceValue(
            first,
            slot.sources.length === 1 &&
              slot.origin !== "user" &&
              slot.state === "present"
              ? slot.value
              : null,
          ),
        }
      : null,
    donor:
      slot.emag_parameter_id === null
        ? null
        : {
            key: String(slot.emag_parameter_id),
            title: slot.name,
            type: "A slot API nem közöl paramétertípust",
            unit: slot.target_unit,
            required: slot.mandatory,
            constraint: "",
          },
    additionalSources: additional,
    storedValue: saved?.value ?? null,
    storedUnit: saved?.unit ?? null,
    storedOrigin: saved
      ? {
          source: "Forrás",
          alias: "Alias",
          added_slot: "Üres hely",
          user: "Kézi döntés",
        }[saved.origin]
      : "Még nincs eltárolva",
    correction: saved?.origin === "user" ? saved.value : null,
    aliasSuggestion:
      slot.candidates
        .filter((c) => c.emag_parameter_id)
        .map((c) => c.name)
        .join(" / ") || null,
    locked: slot.locked,
    canEdit: false,
    history: events.map((e) => ({
      when: e.created_at,
      actor: e.actor_id === null ? "Rendszer" : `Felhasználó ${e.actor_id}`,
      reason: e.reason || e.kind,
      before: e.before ? JSON.stringify(e.before) : "",
      after: e.after ? JSON.stringify(e.after) : "",
    })),
  };
}
function ProfileChoice({
  request,
  meta,
  canClassify,
  onChanged,
}: {
  request: Request;
  meta: Context;
  canClassify: boolean;
  onChanged: () => void;
}) {
  const [choice, C] = useState("");
  const [confirm, F] = useState(false);
  const [busy, B] = useState(false);
  const [error, E] = useState("");
  const [reason, R] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  if (!meta.classification.donor_choices.length) return null;
  async function save() {
    if (!choice || !confirm || busy || !meta.classification.navigation_node_id)
      return;
    const c = new AbortController();
    pending.current = c;
    B(true);
    E("");
    try {
      decodeProductContext(
        await request<unknown>(
          `/workspace/products/${meta.id}/classification`,
          "PATCH",
          {
            expected_revision: meta.revision,
            action: "set",
            navigation_node_id: meta.classification.navigation_node_id,
            donor_emag_category_id: Number(choice),
            reason: reason.trim(),
          },
          c.signal,
        ),
      );
      if (!c.signal.aborted) onChanged();
    } catch (e) {
      if (!c.signal.aborted) {
        E(e instanceof Error ? e.message : "A profilválasztás nem menthető.");
        F(false);
      }
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  return (
    <section aria-label="Explicit paraméterprofil-választás">
      <h3>Explicit paraméterprofil-választás</h3>
      <p>
        Profilválasztás, nem donorjóváhagyás. A vitatott donor továbbra sem
        használható automatikus eMAG-helyekhez; a forrás és a korábbi kézi
        helyek megmaradnak.
      </p>
      {canClassify && meta.capabilities.classify ? (
        <>
          <fieldset disabled={busy || confirm || !!error}>
            <label>
              Választandó paraméterprofil
              <select
                aria-label="Választandó paraméterprofil"
                value={choice}
                onChange={(e) => C(e.target.value)}
              >
                <option value="">Válassz kifejezetten profilt</option>
                {meta.classification.donor_choices.map((d) => (
                  <option key={d.emag_category_id} value={d.emag_category_id}>
                    {d.name}
                    {d.review_state === "pending_review"
                      ? " – felülvizsgálatra vár"
                      : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Profilválasztás indoka
              <textarea
                maxLength={500}
                value={reason}
                onChange={(e) => R(e.target.value)}
              />
            </label>
          </fieldset>
          <button
            disabled={!choice || !reason.trim() || busy || !!error}
            onClick={() => F(true)}
          >
            Profilválasztás áttekintése
          </button>
          {confirm && (
            <div>
              <p>
                Helyi megerősítés, nem paraméter-dry-run. A kiválasztott profil
                csak paraméterforrás-kijelölés; ez nem dúsítási jóváhagyás.
              </p>
              <button disabled={busy} onClick={save}>
                Paraméterprofil kiválasztása
              </button>
              <button disabled={busy} onClick={() => F(false)}>
                Profilválasztás elvetése
              </button>
            </div>
          )}
        </>
      ) : (
        <p>A profilváltáshoz besorolásmódosítási jogosultság szükséges.</p>
      )}
      {error && (
        <>
          <p role="alert">{error}</p>
          <button onClick={onChanged}>Profiladatok frissítése</button>
        </>
      )}
    </section>
  );
}
export function LiveParameters({
  request,
  access,
  workspaceKey,
  product,
  onProductChanged,
}: {
  request: Request;
  access: ParameterAccess;
  workspaceKey: string;
  product: {
    key: string;
    title: string;
    ownCategory: string;
    internalPath: string;
  };
  onProductChanged: () => void;
}) {
  const api = useMemo(() => parameterApi(request), [request]);
  const [version, V] = useState(0);
  const [snapshot, S] = useState<Snapshot | null>(null);
  const holder = useRef<Snapshot | null>(null);
  const probe = useCallback(
    async (s: AbortSignal) => {
      try {
        await api.list(new URLSearchParams({ limit: "1" }), s);
        return true;
      } catch (e) {
        if (e instanceof ApiHttpError && e.status === 404) return false;
        throw e;
      }
    },
    [api],
  );
  const support = usePresentationRead(probe);
  const ports = useMemo<ParameterPorts>(() => {
    void version;
    let cache: Snapshot | null = null;
    let serial = 0;
    const previews = new Map<string, ServerPreview>();
    async function get(signal: AbortSignal) {
      if (cache) return cache;
      const stored = await api.read(product.key, signal);
      const meta = decodeProductContext(
        await request<unknown>(
          `/workspace/products/${encodeURIComponent(product.key)}`,
          "GET",
          undefined,
          signal,
        ),
      );
      const preview = await api.preview(product.key, signal);
      if (
        stored.product_id !== Number(product.key) ||
        preview.product_id !== stored.product_id ||
        meta.id !== stored.product_id ||
        stored.revision !== preview.revision ||
        meta.revision !== stored.revision
      )
        throw new ParameterRevisionConflict(
          "A termék olvasás közben megváltozott. Kérj friss paraméteradatokat.",
        );
      if (signal.aborted) throw new DOMException("Megszakítva", "AbortError");
      cache = { stored, preview, meta };
      holder.current = cache;
      S(cache);
      return cache;
    }
    return {
      read: async (_key, filters, cursor, signal) => {
        const data = await get(signal);
        let rows = data.preview.slots.map((s) => row(s, data));
        if (filters.status !== "all")
          rows = rows.filter((r) => r.status === filters.status);
        if (filters.match !== "all")
          rows = rows.filter((r) => r.match === filters.match);
        if (filters.search.trim()) {
          const q = filters.search.toLocaleLowerCase("hu-HU");
          rows = rows.filter((r) =>
            [r.own?.title, r.donor?.title, r.key].some((s) =>
              s?.toLocaleLowerCase("hu-HU").includes(q),
            ),
          );
        }
        const offset = Number(cursor || 0);
        const c = data.preview.classification;
        return {
          rows: rows.slice(offset, offset + 25),
          next: offset + 25 < rows.length ? String(offset + 25) : null,
          total: rows.length,
          totalProducts: null,
          context: { revision: data.preview.revision },
          versionLabel: `Szerver számított előnézete · ${data.stored.slots.length} tárolt / ${data.preview.slots.length} számított hely · Revízió ${data.preview.revision} · Katalógus ${data.preview.catalog_version_id ?? "nincs"} · A helyi szűrés csak erre a termékre vonatkozik.`,
          profiles:
            c.donor_emag_category_id === null
              ? []
              : [
                  {
                    key: String(c.donor_emag_category_id),
                    title:
                      data.meta.classification.donor_name ||
                      `Donor ${c.donor_emag_category_id}`,
                    path:
                      data.meta.classification.navigation_path?.join(" / ") ||
                      "",
                    review:
                      c.parameter_profile_state === "ready"
                        ? "approved"
                        : c.parameter_profile_state === "pending_review"
                          ? "pending_review"
                          : "unknown",
                  },
                ],
          activeProfileKey:
            c.donor_emag_category_id === null
              ? null
              : String(c.donor_emag_category_id),
          preparation: {
            state: data.stored.slots.length ? "review" : "unprepared",
            canApprove: false,
            explanation:
              "A tárolt vagy kiszámított hely nem felhasználói előkészítési jóváhagyás. Külön jóváhagyási API nincs bekötve.",
            audit:
              "A termék végpontjának legfeljebb 50 eseménye látható; teljes auditlapozás nincs.",
          },
        };
      },
      preview: async (intent, signal) => {
        if (intent.action !== "add_missing")
          throw new Error(
            "Ehhez a művelethez nincs általános szerveres preview API.",
          );
        const p = await api.preview(product.key, signal);
        const expected = (intent.context as { revision?: number })?.revision;
        if (p.product_id !== Number(product.key) || p.revision !== expected)
          throw new ParameterRevisionConflict(
            "A paraméterrevízió változott. Új lekérés és új előnézet szükséges.",
          );
        const handle = String(++serial);
        previews.clear();
        previews.set(handle, p);
        return {
          origin: "server",
          handle,
          summary:
            "A szerver újraszámította a helyeket. Az alkalmazás egyszerműveletes termékrevízióval történik, nem előnézeti tokennel.",
          canApply: access.edit && p.capabilities.edit,
          eligible: 1,
          preserved: p.summary.keep,
          addedEmpty: p.changes.filter(
            (c) => c.change === "create" && c.after?.state === "missing",
          ).length,
          locked: p.summary.blocked_locked,
          conflicts: p.slots.filter((s) => s.state === "conflict").length,
          blocked: p.summary.blocked_locked,
          sourceOverwrites: 0,
          changes: p.changes.map((c) => ({
            label: `${c.slot_key} · ${c.change}`,
            before: c.before
              ? `${c.before.state}: ${c.before.value ?? "üres"} ${c.before.unit || ""}`
              : "Nincs hely",
            after: c.after
              ? `${c.after.state}: ${c.after.value ?? "üres"} ${c.after.unit || ""}`
              : "Az üres hely megszűnik",
          })),
          runs: [],
        };
      },
      apply: access.edit
        ? async (preview, signal) => {
            const p = previews.get(String(preview.handle));
            if (!p)
              throw new Error(
                "Az előnézet már nem használható. Kérj friss adatokat.",
              );
            previews.delete(String(preview.handle));
            try {
              await api.apply(product.key, p.revision, signal);
              cache = null;
              return {
                message:
                  "A szerver alkalmazta a paraméterváltozásokat. A nyers forrásadatok megmaradtak.",
                job: null,
              };
            } catch (e) {
              if (e instanceof ApiHttpError && e.status === 409)
                throw new ParameterRevisionConflict(e.message);
              throw e;
            }
          }
        : undefined,
    };
  }, [api, request, product.key, version, access.edit]);
  const refresh = useCallback(() => {
    holder.current = null;
    V((v) => v + 1);
  }, []);
  const scopes = useMemo(() => {
    const all: RunScope = {
      source_category_id: null,
      navigation_node_id: null,
      supplier_id: null,
    };
    const meta = snapshot?.meta;
    const out: { key: string; label: string; scope: RunScope }[] = [];
    if (meta?.source_category)
      out.push({
        key: "own",
        label: `Saját kategória: ${meta.source_category.path}`,
        scope: { ...all, source_category_id: meta.source_category.id },
      });
    if (meta?.classification.navigation_node_id)
      out.push({
        key: "internal",
        label: `Belső kategória: ${meta.classification.navigation_path?.join(" / ") || ""}`,
        scope: {
          ...all,
          navigation_node_id: meta.classification.navigation_node_id,
        },
      });
    if (meta)
      out.push({
        key: "supplier",
        label: "A kiválasztott termék beszállítója",
        scope: { ...all, supplier_id: meta.supplier_id },
      });
    out.push({
      key: "workspace",
      label: "Az aktív munkaterület teljes termékállománya",
      scope: all,
    });
    return out;
  }, [snapshot?.meta]);
  return (
    <section aria-label="Élő paramétermunkaterület">
      <h3>Paraméter-előkészítés – valódi API</h3>
      {support.loading && <p role="status">Paraméter-API ellenőrzése…</p>}
      {support.error && <p role="alert">{support.error}</p>}
      {support.data === false && (
        <p className="notice">
          A telepített backendben a paraméter-API még nem érhető el.
        </p>
      )}
      {support.data && (
        <>
          {snapshot?.preview.classification.parameter_profile_state ===
            "pending_review" &&
            snapshot.preview.classification.donor_emag_category_id === null && (
              <p className="notice">
                A donor felülvizsgálatra vár. Automatikus eMAG-paraméterhely nem
                készül; a saját forrásadatok megmaradnak.
              </p>
            )}
          {snapshot?.preview.classification.parameter_profile_state ===
            "choice_required" && (
            <p className="notice">
              Kifejezett profilválasztás szükséges. Addig csak forráshelyek
              készülhetnek; ez nem donorjóváhagyás.
            </p>
          )}
          <button onClick={refresh}>Paraméteradatok friss lekérése</button>
          <ParameterWorkspace
            key={`${workspaceKey}:${product.key}:${version}`}
            workspaceKey={workspaceKey}
            product={{
              ...product,
              ownCategory: snapshot
                ? snapshot.meta.source_category?.path || ""
                : product.ownCategory,
              internalPath: snapshot
                ? snapshot.meta.classification.navigation_path?.join(" / ") ||
                  ""
                : product.internalPath,
            }}
            ports={ports}
            access={{
              edit: access.edit && !!snapshot?.stored.capabilities.edit,
              unlock: false,
              approve: false,
              bulk: false,
              manageJobs: false,
            }}
            allowSourcePreparation
            allowProfileChoice={false}
            preparationActionLabel="Paraméterváltozások szerveres előnézete"
            renderDetails={(r) => {
              const current = holder.current;
              const stored = current?.stored.slots.find(
                (s) => s.slot_key === r.key,
              );
              return current && stored ? (
                <LiveSlotEditor
                  key={`${stored.slot_key}:${current.stored.revision}`}
                  product={product.key}
                  revision={current.stored.revision}
                  slot={stored}
                  api={api}
                  canEdit={access.edit && current.stored.capabilities.edit}
                  onRefresh={refresh}
                />
              ) : (
                <p>
                  Előnézeti hely; kézi módosításhoz előbb alkalmazd a szerveres
                  változásokat.
                </p>
              );
            }}
          />
          {snapshot && (
            <>
              <ProfileChoice
                key={snapshot.meta.revision}
                request={request}
                meta={snapshot.meta}
                canClassify={access.classify}
                onChanged={() => {
                  refresh();
                  onProductChanged();
                }}
              />
              <details>
                <summary>Tenant- és globális aliasszabályok</summary>
                <LiveAliases
                  api={api}
                  access={access}
                  data={snapshot.preview}
                  onChanged={refresh}
                />
              </details>
              <LiveRuns
                api={api}
                canEdit={access.edit && snapshot.stored.capabilities.edit}
                scopes={scopes}
              />
            </>
          )}
          <p className="notice">
            Nincs snapshotos általános bulk-jóváhagyás, külön előkészítési
            jóváhagyás, teljes auditlapozás vagy univerzális értéklista-CRUD. AI
            nem indítható.
          </p>
        </>
      )}
    </section>
  );
}
