import { ApiHttpError } from "../apiResponse";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Request } from "../classification/category02Contract";
import { usePresentationRead } from "../classification/usePresentationRead";
import { ParameterJobPanel } from "./ParameterJobPanel";
import type { ParameterJob, ParameterPorts } from "./presentation";
import {
  bulkApi,
  expired,
  type Operation,
  type Selection,
  type BulkAccess,
  type BulkFilters,
} from "./bulkApi";
import { ApprovalReview } from "./ApprovalReview";

const outcomeLabels: Record<string, string> = {
  eligible: "Alkalmazható",
  unchanged: "Változatlan",
  skipped_pending_review: "Donor felülvizsgálatra vár",
  skipped_choice_required: "Profilválasztás hiányzik",
  skipped_no_donor: "Nincs donor",
  error: "Hibás",
  applied: "Alkalmazva",
  stale: "Elavult termékrevízió",
  changed_since_preview: "Az előnézet óta megváltozott",
  approvable: "Jóváhagyható",
  blocked: "Blokkolt",
};
export function asParameterJob(op: Operation): ParameterJob {
  const partial =
    op.state === "completed" &&
    ["stale", "changed_since_preview", "error"].some(
      (k) => (op.outcomes[k] || 0) > 0,
    );
  return {
    key: String(op.id),
    context: op,
    state: partial ? "partial" : op.state === "pending" ? "queued" : op.state,
    progressPercent: op.total
      ? (100 * op.processed) / op.total
      : op.state === "completed"
        ? 100
        : null,
    processed: op.processed,
    total: op.total,
    changed: op.kind === "bulk_apply" ? op.outcomes.applied || 0 : 0,
    skipped: Object.entries(op.outcomes)
      .filter(
        ([k]) =>
          k.startsWith("skipped_") ||
          ["unchanged", "stale", "changed_since_preview", "blocked"].includes(
            k,
          ),
      )
      .reduce((n, [, v]) => n + v, 0),
    failed: op.outcomes.error || op.error_count,
    message: `${op.kind === "bulk_preview" ? "Tömeges előnézet" : op.kind === "bulk_apply" ? "Tömeges alkalmazás" : "Előkészítési ellenőrzés"} · Futások: ${op.runs} · Futáskorlát: ${op.run_limit}${partial ? " · Nem minden termék került alkalmazásra." : ""}`,
    errors: op.error ? [{ label: "Művelet", message: op.error }] : [],
    canResume: op.state === "pending" || op.stalled,
    canCancel: ["pending", "running"].includes(op.state),
  };
}
const key = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
type Intent =
  | {
      type: "apply";
      id: number;
      body: {
        preview_token: string;
        confirm: true;
        expected_eligible: number;
        idempotency_key: string;
        reason: string;
      };
    }
  | {
      type: "approve";
      body: {
        check_id: number;
        check_token: string;
        confirm: true;
        expected_approvable: number;
        idempotency_key: string;
        reason: string;
      };
    };
export function LiveBulkPreparation({
  request,
  access,
  filters,
  selectedIds,
}: {
  request: Request;
  access: BulkAccess;
  filters: BulkFilters;
  selectedIds: number[];
}) {
  const api = useMemo(() => bulkApi(request), [request]);
  const [selection, S] = useState<Selection | null>(null);
  const [op, O] = useState<Operation | null>(null);
  const [initial, J] = useState<ParameterJob | null>(null);
  const [preview, P] = useState<{ id: number; token: string } | null>(null);
  const [check, C] = useState<{ id: number; token: string } | null>(null);
  const [intent, I] = useState<Intent | null>(null);
  const [failed, F] = useState<Intent | null>(null);
  const [reason, R] = useState("");
  const [busy, B] = useState(false);
  const [error, E] = useState("");
  const [notice, N] = useState("");
  const [approvalId, A] = useState<number | null>(null);
  const [refresh, T] = useState(0);
  const [jobId, Q] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const start = (next: Operation) => {
    O(next);
    J(asParameterJob(next));
    Q(String(next.id));
    I(null);
  };
  async function act(fn: (signal: AbortSignal) => Promise<void>) {
    if (busy) return;
    const c = new AbortController();
    pending.current?.abort();
    pending.current = c;
    B(true);
    E("");
    try {
      await fn(c.signal);
    } catch (e) {
      if (!c.signal.aborted) {
        E(e instanceof Error ? e.message : "A tömeges művelet sikertelen.");
        I(null);
      }
    } finally {
      if (!c.signal.aborted) B(false);
    }
  }
  const ports = useMemo<ParameterPorts>(
    () => ({
      read: async () => {
        throw new Error("Ez a port csak a futáskártyához tartozik.");
      },
      job: async (id, s) => {
        const n = await api.job(Number(id), s);
        if (n.id !== Number(id)) throw new Error("Eltérő futásazonosító.");
        if (!s.aborted) O(n);
        return asParameterJob(n);
      },
      resume: async (j, s) => {
        const n = await api.control(Number(j.key), "resume", s);
        if (!s.aborted) {
          O(n);
          N(
            n.enqueue_failed
              ? "A folytatás sorba állítása nem sikerült; az állapot külön frissíthető."
              : "A futás folytatása kérve; az állapotát a szerver jelzi.",
          );
        }
        return asParameterJob(n);
      },
      cancel: async (j, s) => {
        const n = await api.control(Number(j.key), "cancel", s);
        if (!s.aborted) O(n);
        return asParameterJob(n);
      },
    }),
    [api],
  );
  async function select(mode: "filters" | "page") {
    await act(async (s) => {
      const n = await api.selection(
        mode === "filters" ? { filters } : { product_ids: selectedIds },
        s,
      );
      if (s.aborted) return;
      S(n);
      O(null);
      J(null);
      P(null);
      C(null);
      F(null);
      I(null);
      N("A szerver rögzítette a termékkört és annak revízióit.");
    });
  }
  async function calculate(mode: "preview" | "check") {
    await act(async (s) => {
      if (!selection || expired(selection.expires_at))
        throw new Error("A kijelölés lejárt. Rögzíts új termékkört.");
      if (mode === "preview") {
        const n = await api.preview(selection.selection_token, s);
        if (s.aborted) return;
        P({ id: n.preview.id, token: n.preview_token });
        start(n.preview);
        if (n.enqueue_failed)
          N("A sorba állítás nem sikerült. A futás kifejezetten folytatható.");
      } else {
        const n = await api.check(selection.selection_token, s);
        if (s.aborted) return;
        C({ id: n.check.id, token: n.check_token });
        start(n.check);
        if (n.enqueue_failed)
          N("A sorba állítás nem sikerült. A futás kifejezetten folytatható.");
      }
    });
  }
  async function confirm(value: Intent) {
    if (
      !(value.type === "apply" ? access.edit && access.bulk : access.approve)
    ) {
      E("Nincs jogosultság ehhez a döntéshez.");
      return;
    }
    F(value);
    await act(async (s) => {
      try {
        if (value.type === "apply") {
          const n = await api.apply(value.id, value.body, s);
          if (s.aborted) return;
          start(n.apply);
          N(
            n.enqueue_failed
              ? "A futás létrejött, de a sorba állítás nem sikerült. Kifejezetten folytatható."
              : n.replayed
                ? "A szerver a már létező alkalmazási futást adta vissza."
                : "A szerver létrehozta az alkalmazási futást. A tételes eredmények külön ellenőrizendők.",
          );
        } else {
          const n = await api.approve(value.body, s);
          if (s.aborted) return;
          A(n.id);
          T((v) => v + 1);
          I(null);
          N(
            `Előkészítési jóváhagyás létrejött: ${n.approved}; időközben elavult, kihagyott: ${n.skipped_stale}. Ez nem indít AI-kutatást.`,
          );
        }
        F(null);
      } catch (e) {
        if (e instanceof ApiHttpError && e.status >= 400 && e.status < 500)
          F(null);
        throw e;
      }
    });
  }
  const ready =
    op?.state === "completed" &&
    selection?.id === op.selection_id &&
    !expired(op.expires_at);
  const eligible = op?.outcomes.eligible || 0;
  const approvable = op?.outcomes.approvable || 0;
  const canControl =
    op?.kind !== "bulk_apply" || !!(access.edit && access.bulk);
  return (
    <section aria-label="Rögzített termékkör és előkészítési jóváhagyás">
      <h3>Rögzített termékkör, tömeges előkészítés</h3>
      <p>
        Az előnézet a szerver által rögzített termékekhez kötődik. A kijelölés
        legfeljebb 250 000 termék és 2 óráig használható; egy feldolgozási futás
        legfeljebb 50 000 termék. A következő futásokat a szerver indítja
        ugyanazon feladaton.
      </p>
      <p>
        A kijelölés ezen a nézeten használható. Kilépés vagy szűrőváltás után új
        kijelölés szükséges; a már elindult futás megmarad.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="actions">
        <button disabled={busy || !!intent} onClick={() => select("filters")}>
          Teljes szűrt termékkör rögzítése
        </button>
        <button
          disabled={
            busy || !!intent || !selectedIds.length || selectedIds.length > 100
          }
          onClick={() => select("page")}
        >
          Kijelölt termékek rögzítése ({selectedIds.length})
        </button>
      </div>
      {selection && (
        <>
          <p>
            Rögzített termékek:{" "}
            <strong>{selection.total.toLocaleString("hu-HU")}</strong> · Lejárat
            (UTC): {selection.expires_at} ·{" "}
            {selection.mode === "filters"
              ? "Teljes szűrt halmaz"
              : "Kifejezett kijelölés"}
          </p>
          <button
            disabled={
              busy || !!error || !!intent || expired(selection.expires_at)
            }
            onClick={() => calculate("preview")}
          >
            Tömeges paraméter-előnézet
          </button>
          <button
            disabled={
              busy || !!error || !!intent || expired(selection.expires_at)
            }
            onClick={() => calculate("check")}
          >
            Előkészítési ellenőrzés
          </button>
        </>
      )}
      <label>
        Meglévő tömeges futás azonosítója
        <input
          type="number"
          min="1"
          value={jobId}
          onChange={(e) => Q(e.target.value)}
        />
      </label>
      <button
        disabled={busy || !/^\d+$/.test(jobId) || Number(jobId) < 1}
        onClick={() =>
          act(async (s) => {
            const n = await api.job(Number(jobId), s);
            if (!s.aborted) start(n);
          })
        }
      >
        Tömeges futás betöltése
      </button>
      {initial && (
        <ParameterJobPanel
          initial={initial}
          ports={ports}
          access={{
            edit: false,
            unlock: false,
            approve: false,
            bulk: false,
            manageJobs: canControl,
          }}
        />
      )}
      {op && (
        <>
          <h4>Tényleges tételes összesítés</h4>
          <ul>
            {Object.entries(op.outcomes).map(([name, n]) => (
              <li key={name}>
                {outcomeLabels[name] || name}: {n.toLocaleString("hu-HU")}
              </li>
            ))}
          </ul>
          {op.slots && (
            <p>
              Új hely: {op.slots.create}; módosult: {op.slots.update}; védett:{" "}
              {op.slots.blocked_locked}; forrásfelülírás: {op.source_overwrites}
              .
            </p>
          )}
          {op.kind === "preparation_check" && (
            <p>
              Kutatandó hiány: {op.research_targets}; kötelező hiány:{" "}
              {op.mandatory_research_targets}. Az üres, kutatandó hely önmagában
              nem tiltja a jóváhagyást.
            </p>
          )}
          {op.stopped_reason && (
            <p role="alert">
              A futás leállt: {op.stopped_reason}. A már alkalmazott rész
              megmarad.
            </p>
          )}
          <OperationItems key={op.id} api={api} id={op.id} state={op.state} />
          {ready && (
            <>
              <label>
                Tömeges döntés indoka
                <textarea
                  aria-label="Tömeges döntés indoka"
                  maxLength={500}
                  value={reason}
                  onChange={(e) => {
                    R(e.target.value);
                    I(null);
                  }}
                />
              </label>
              {op.kind === "bulk_preview" &&
                preview?.id === op.id &&
                access.edit &&
                access.bulk && (
                  <button
                    disabled={
                      busy ||
                      !!error ||
                      !reason.trim() ||
                      !eligible ||
                      op.source_overwrites !== 0
                    }
                    onClick={() =>
                      I({
                        type: "apply",
                        id: op.id,
                        body: {
                          preview_token: preview.token,
                          confirm: true,
                          expected_eligible: eligible,
                          idempotency_key: key(),
                          reason: reason.trim(),
                        },
                      })
                    }
                  >
                    Tömeges alkalmazás áttekintése
                  </button>
                )}
              {op.kind === "preparation_check" &&
                check?.id === op.id &&
                access.approve && (
                  <button
                    disabled={busy || !!error || !reason.trim() || !approvable}
                    onClick={() =>
                      I({
                        type: "approve",
                        body: {
                          check_id: op.id,
                          check_token: check.token,
                          confirm: true,
                          expected_approvable: approvable,
                          idempotency_key: key(),
                          reason: reason.trim(),
                        },
                      })
                    }
                  >
                    Előkészítési jóváhagyás áttekintése
                  </button>
                )}
            </>
          )}
        </>
      )}
      {intent && (
        <section aria-label="Tömeges döntés megerősítése">
          <p>
            {intent.type === "apply"
              ? `Szerveres előnézet alapján alkalmazható: ${intent.body.expected_eligible}. A megváltozott termékek kimaradnak.`
              : `Jóváhagyható: ${intent.body.expected_approvable}. A döntés nem donorjóváhagyás és nem indít AI-kutatást.`}
          </p>
          <button
            disabled={
              busy ||
              !op ||
              expired(op.expires_at) ||
              !(intent.type === "apply"
                ? access.edit && access.bulk
                : access.approve)
            }
            onClick={() => confirm(intent)}
          >
            Tömeges döntés megerősítése
          </button>
          <button disabled={busy} onClick={() => I(null)}>
            Tömeges döntés elvetése
          </button>
        </section>
      )}
      {error && failed && (
        <button
          disabled={
            busy ||
            !(failed.type === "apply"
              ? access.edit && access.bulk
              : access.approve)
          }
          onClick={() => confirm(failed)}
        >
          Azonos kérés kézi ismétlése (idempotens)
        </button>
      )}
      <ApprovalReview
        key={approvalId ?? "list"}
        api={api}
        canApprove={!!access.approve}
        selectedId={approvalId}
        refresh={refresh}
      />
    </section>
  );
}
function OperationItems({
  api,
  id,
  state,
}: {
  api: ReturnType<typeof bulkApi>;
  id: number;
  state: string;
}) {
  const [cursor, C] = useState<number | null>(null);
  const [history, H] = useState<(number | null)[]>([]);
  const [outcome, O] = useState("");
  const [applied, A] = useState("");
  const [tick, T] = useState(0);
  const load = useCallback(
    (s: AbortSignal) => {
      void state;
      void tick;
      const q = new URLSearchParams({
        cursor: String(cursor || 0),
        limit: "25",
      });
      if (outcome) q.set("outcome", outcome);
      if (applied) q.set("apply_outcome", applied);
      return api.items(id, q, s);
    },
    [api, id, cursor, outcome, applied, state, tick],
  );
  const read = usePresentationRead(load);
  return (
    <section aria-label="Tömeges futás tételei">
      <label>
        Tétel előnézeti állapota
        <select
          aria-label="Tétel előnézeti állapota"
          value={outcome}
          onChange={(e) => {
            O(e.target.value);
            C(null);
            H([]);
          }}
        >
          <option value="">Mind</option>
          {Object.entries(outcomeLabels).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tétel alkalmazási állapota
        <select
          aria-label="Tétel alkalmazási állapota"
          value={applied}
          onChange={(e) => {
            A(e.target.value);
            C(null);
            H([]);
          }}
        >
          <option value="">Mind</option>
          {[
            "applied",
            "unchanged",
            "stale",
            "changed_since_preview",
            "error",
          ].map((k) => (
            <option key={k} value={k}>
              {outcomeLabels[k]}
            </option>
          ))}
        </select>
      </label>
      {read.error && <p role="alert">{read.error}</p>}
      <button onClick={() => T((v) => v + 1)}>Tétellista frissítése</button>
      <ul>
        {read.data?.items.map((i) => (
          <li key={i.product_id}>
            {i.name || i.sku || `Termék ${i.product_id}`} ·{" "}
            {outcomeLabels[i.outcome] || i.outcome} ·{" "}
            {i.apply_outcome
              ? outcomeLabels[i.apply_outcome] || i.apply_outcome
              : "Még nincs alkalmazási eredmény"}{" "}
            · Revízió: {i.revision_before} → {i.revision_after ?? "változatlan"}{" "}
            · {i.reasons.join(", ")}
          </li>
        ))}
      </ul>
      <button
        disabled={!history.length || read.loading}
        onClick={() => {
          C(history.at(-1) ?? null);
          H(history.slice(0, -1));
        }}
      >
        Előző műveleti tételek
      </button>
      <button
        disabled={!read.data?.next_cursor || read.loading}
        onClick={() => {
          H([...history, cursor]);
          C(read.data?.next_cursor ?? null);
        }}
      >
        Következő műveleti tételek
      </button>
    </section>
  );
}
