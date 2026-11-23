import { useEffect, useRef, useState } from "react";
import {
  createSupplier,
  loadCatalog,
  loadPreparation,
  loadRun,
  loadRuns,
  loadSuppliers,
  loadTemplates,
  loadVersions,
  message,
  uploadRun,
  type Catalog,
  type Deleted,
  type DeletionTarget,
  type Preparation,
  type Request,
  type Run,
  type Supplier,
  type TemplateList,
  type TemplateVersion,
} from "./api";
import { ImportDeleteButton, ImportDeletionDialog } from "./ImportDeletionDialog";
import { TemplateEditor } from "./TemplateEditor";
import "./template-preparation.css";

const pageSize = 25;
const emptyTemplates: TemplateList = { templates: [], legacy: [] };

export function TemplatePreparation({
  api,
  permissions,
}: {
  api: Request;
  permissions: string[];
}) {
  const canCreate = permissions.includes("imports.create");
  const canSave = permissions.includes("imports.approve");
  const canManage = permissions.includes("imports.manage");
  const [catalog, setCatalog] = useState<Catalog>();
  const [catalogError, setCatalogError] = useState("");
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [engine, setEngine] = useState("");
  const [currency, setCurrency] = useState("HUF");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState(0);
  const [supplierName, setSupplierName] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [run, setRun] = useState<Run>();
  const [context, setContext] = useState<{
    revision: number;
    template?: number;
  }>({ revision: 0 });
  const [loaded, setLoaded] = useState<{
    key: string;
    currency: string;
    initial: Preparation;
    latest: Preparation;
  }>();
  const [detailsError, setDetailsError] = useState("");
  const [detailsRetry, setDetailsRetry] = useState(0);
  const [templates, setTemplates] = useState<{
    supplier: number;
    data: TemplateList;
  }>();
  const [versionGroup, setVersionGroup] = useState(0);
  const [versions, setVersions] = useState<{
    id: number;
    list: TemplateVersion[];
  }>();
  const [templateError, setTemplateError] = useState("");
  const [templatesRetry, setTemplatesRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [setupKey, setSetupKey] = useState<string>();
  const [savedTemplate, setSavedTemplate] = useState<{ key: string; id: number }>();
  const [deletion, setDeletion] = useState<DeletionTarget>();
  const [deletedName, setDeletedName] = useState("");
  const [error, setError] = useState("");
  const task = useRef(false);

  useEffect(() => {
    let active = true;
    loadCatalog(api)
      .then((result) => {
        if (active) setCatalog(result);
      })
      .catch((failure) => {
        if (active) setCatalogError(message(failure));
      });
    return () => {
      active = false;
    };
  }, [api, catalogRetry]);

  const [sourcesRetry, setSourcesRetry] = useState(0);
  useEffect(() => {
    if (!engine) return;
    let active = true;
    Promise.all([loadSuppliers(api), loadRuns(api)])
      .then(([entries, history]) => {
        if (!active) return;
        setSuppliers(entries);
        setRuns(history);
        setOffset(0);
        setMore(history.length === pageSize);
      })
      .catch((failure) => {
        if (active) setError(message(failure));
      });
    return () => {
      active = false;
    };
  }, [api, engine, sourcesRetry]);

  useEffect(() => {
    if (!supplierId) return;
    let active = true;
    loadTemplates(api, supplierId)
      .then((data) => {
        if (active) setTemplates({ supplier: supplierId, data });
      })
      .catch((failure) => {
        if (active) setTemplateError(message(failure));
      });
    return () => {
      active = false;
    };
  }, [api, supplierId, templatesRetry]);

  useEffect(() => {
    if (!versionGroup) return;
    let active = true;
    loadVersions(api, versionGroup)
      .then((list) => {
        if (active) setVersions({ id: versionGroup, list });
      })
      .catch((failure) => {
        if (active) setTemplateError(message(failure));
      });
    return () => {
      active = false;
    };
  }, [api, versionGroup, templatesRetry]);

  const runId = run?.id;
  const analysing = run?.state === "uploaded";
  const unusable =
    (run?.state === "cancelled" || run?.state === "failed") &&
    !run.analysis?.headers?.length;
  useEffect(() => {
    if (!runId || !analysing) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll(id: number) {
      try {
        const next = await loadRun(api, id);
        if (!active) return;
        setRun(next);
        setRuns((history) =>
          history.map((entry) => (entry.id === next.id ? next : entry)),
        );
        if (next.state === "uploaded")
          timer = setTimeout(() => void poll(id), 1800);
      } catch (failure) {
        if (active) setDetailsError(message(failure));
      }
    }
    timer = setTimeout(() => void poll(runId), 400);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, runId, analysing, detailsRetry]);

  const viewKey = `${runId ?? ""}:${context.revision}`;
  useEffect(() => {
    if (!runId || !engine || analysing || unusable) return;
    let active = true;
    loadPreparation(api, runId, engine, currency, context.template)
      .then((result) => {
        if (!active) return;
        setDetailsError("");
        setLoaded((previous) => ({
          key: viewKey,
          currency,
          latest: result,
          initial: previous?.key === viewKey ? previous.initial : result,
        }));
      })
      .catch((failure) => {
        if (active) setDetailsError(message(failure));
      });
    return () => {
      active = false;
    };
  }, [
    api,
    runId,
    engine,
    currency,
    context.template,
    viewKey,
    detailsRetry,
    analysing,
    unusable,
  ]);

  async function action(runAction: () => Promise<void>) {
    if (task.current) return;
    task.current = true;
    setBusy(true);
    setError("");
    try {
      await runAction();
    } catch (failure) {
      setError(message(failure));
    } finally {
      task.current = false;
      setBusy(false);
    }
  }

  function openRun(next: Run) {
    setDetailsError("");
    setRun(next);
    setContext((previous) => ({ revision: previous.revision + 1 }));
  }

  function changeSupplier(id: number) {
    setSupplierId(id);
    setRun(undefined);
    setVersionGroup(0);
    setTemplateError("");
    setDetailsError("");
    setError("");
  }

  function openTemplate(id: number, templateCurrency?: string) {
    setDetailsError("");
    if (templateCurrency && catalog?.currencies.includes(templateCurrency))
      setCurrency(templateCurrency);
    setContext((previous) => ({
      revision: previous.revision + 1,
      template: id,
    }));
  }

  const working = busy || saving;
  const preparation = loaded?.key === viewKey ? loaded : undefined;
  const list =
    templates?.supplier === supplierId ? templates.data : emptyTemplates;
  const versionsForGroup =
    versions?.id === versionGroup ? (versions?.list ?? []) : [];
  const validEngine = catalog?.engine.key === engine;

  function deleteButton(target: DeletionTarget) {
    const permitted = target.kind === "supplier" || target.kind === "run" ? canManage : canSave;
    return permitted && (
      <ImportDeleteButton
        target={target}
        disabled={working}
        onOpen={(item) => {
          setDeletedName("");
          setDeletion(item);
        }}
      />
    );
  }

  function afterDeletion(target: DeletionTarget, result: Deleted) {
    setDeletion(undefined);
    setDeletedName(target.name);
    if (target.kind === "supplier") {
      setSuppliers((previous) => previous.filter((item) => item.id !== target.id));
      if (supplierId === target.id) changeSupplier(0);
      setSourcesRetry((value) => value + 1);
      return;
    }
    if (target.kind === "run") {
      setRuns((previous) => previous.filter((item) => item.id !== target.id));
      if (runId === target.id) {
        setRun(undefined);
        setDetailsError("");
      }
      setSourcesRetry((value) => value + 1);
      return;
    }

    const removedIds = result.version_ids ?? [target.id];
    if (target.kind === "template") {
      setTemplates((previous) => previous && ({
        ...previous,
        data: {
          ...previous.data,
          templates: previous.data.templates.filter((item) => item.id !== target.id),
        },
      }));
      if (versionGroup === target.id) setVersionGroup(0);
    }
    setVersions((previous) => previous && ({
      ...previous,
      list: previous.list.filter((item) => !removedIds.includes(item.id)),
    }));
    const currentId =
      savedTemplate?.key === viewKey
        ? savedTemplate.id
        : context.template ?? preparation?.initial.template?.id;
    if (currentId !== undefined && removedIds.includes(currentId)) {
      openTemplate(0);
    }
    setTemplateError("");
    setTemplatesRetry((value) => value + 1);
  }

  const sourceControls = (
    <div className="prep-controls">
      <h3>Beszállító és fájl</h3>
      <label>
        Beszállító
        <select
          aria-label="Beszállító"
          value={supplierId || ""}
          disabled={working}
          onChange={(event) => changeSupplier(Number(event.target.value))}
        >
          <option value="">Válassz beszállítót</option>
          {suppliers.map((supplier) => (
            <option key={supplier.id} value={supplier.id}>
              {supplier.name}
            </option>
          ))}
        </select>
      </label>
      {canManage && suppliers.length > 0 && (
        <details>
          <summary>Beszállítók kezelése</summary>
          <ul className="prep-list">
            {suppliers.map((supplier) => (
              <li key={supplier.id} className="prep-actions">
                <span>{supplier.name}</span>
                {deleteButton({ kind: "supplier", ...supplier })}
              </li>
            ))}
          </ul>
        </details>
      )}
      {canManage && (
        <details>
          <summary>Új beszállító</summary>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!supplierName.trim()) return;
              void action(async () => {
                const supplier = await createSupplier(api, supplierName.trim());
                setSuppliers((previous) => [...previous, supplier]);
                setSupplierName("");
                changeSupplier(supplier.id);
              });
            }}
          >
            <label>
              Új beszállító neve
              <input
                maxLength={120}
                required
                value={supplierName}
                disabled={working}
                onChange={(event) => setSupplierName(event.target.value)}
              />
            </label>
            <button type="submit" disabled={working || !supplierName.trim()}>
              Beszállító létrehozása
            </button>
          </form>
        </details>
      )}
      {canCreate ? (
        <label>
          CSV, XLS, XLSX vagy XML fájl
          <input
            type="file"
            accept=".csv,.xls,.xlsx,.xml"
            disabled={!supplierId || working}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file || !supplierId) return;
              void action(async () => {
                const uploaded = await uploadRun(api, supplierId, file);
                setRuns((history) => [uploaded, ...history]);
                openRun(uploaded);
              });
            }}
          />
        </label>
      ) : (
        <p>Fájlfeltöltéshez külön jogosultság szükséges.</p>
      )}
      {supplierId > 0 && (
        <details>
          <summary>Korábban feltöltött fájlok</summary>
          <ul className="prep-list prep-history">
            {runs
              .filter((item) => item.supplier_id === supplierId)
              .map((item) => (
                <li key={item.id} className="prep-actions">
                  <button
                    type="button"
                    disabled={working}
                    onClick={() => openRun(item)}
                  >
                    #{item.id} · {item.filename}
                  </button>
                  {deleteButton({ kind: "run", id: item.id, name: item.filename })}
                </li>
              ))}
          </ul>
          {!runs.some((item) => item.supplier_id === supplierId) && (
            <p>Ezen az oldalon nincs korábbi fájl ehhez a beszállítóhoz.</p>
          )}
          {more && (
            <button
              type="button"
              disabled={working}
              onClick={() =>
                void action(async () => {
                  const next = offset + pageSize;
                  const history = await loadRuns(api, next);
                  setRuns((previous) => [
                    ...new Map(
                      [...previous, ...history].map((item) => [item.id, item]),
                    ).values(),
                  ]);
                  setOffset(next);
                  setMore(history.length === pageSize);
                })
              }
            >
              Korábbi fájlok betöltése
            </button>
          )}
        </details>
      )}
      {run && (
        <p className="prep-filename">
          <strong>{run.filename}</strong>{" "}
          {preparation?.initial.file.source_available && (
            <a href={`/api/v1/imports/runs/${run.id}/file`}>Eredeti fájl</a>
          )}
        </p>
      )}
      {(list.templates.length > 0 || list.legacy.length > 0) && (
        <details>
          <summary>Mentett sablonok és verziók</summary>
          {!run && <p>A sablon betöltéséhez válassz egy fájlt.</p>}
          <ul className="prep-list">
            {list.templates.map((template) => (
              <li key={template.id} className="prep-template-item">
                <span>
                  {template.name} · v{template.version}
                </span>
                <button
                  type="button"
                  disabled={!run || analysing || unusable || working}
                  onClick={() => openTemplate(template.id, template.currency)}
                >
                  Sablon betöltése
                </button>
                <button
                  type="button"
                  disabled={working}
                  onClick={() => {
                    setTemplateError("");
                    setVersionGroup(
                      versionGroup === template.id ? 0 : template.id,
                    );
                  }}
                >
                  Verziók
                </button>
                {deleteButton({ kind: "template", id: template.id, name: template.name })}
                {versionGroup === template.id &&
                  (versions?.id === versionGroup ? (
                    <ul aria-label={`${template.name} verziói`}>
                      {versionsForGroup.map((version) => (
                        <li key={version.id} className="prep-actions">
                          <button
                            type="button"
                            disabled={!run || analysing || unusable || working}
                            onClick={() =>
                              openTemplate(version.id, version.currency)
                            }
                          >
                            {version.name} · v{version.version} betöltése
                          </button>
                          {deleteButton({
                            kind: "version",
                            templateId: template.id,
                            id: version.id,
                            name: `${version.name} · v${version.version}`,
                          })}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    !templateError && <p role="status">Verziók betöltése…</p>
                  ))}
              </li>
            ))}
          </ul>
          {list.legacy.length > 0 && (
            <div>
              <p>Korábbi importprofilok</p>
              <ul>
                {list.legacy.map((item) => (
                  <li key={item.id}>
                    {item.name} · v{item.version}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {preparation?.initial.template && (
            <button
              type="button"
              disabled={working}
              onClick={() => openTemplate(0)}
            >
              Előkészítés sablon nélkül
            </button>
          )}
        </details>
      )}
      {templateError && <p role="alert">{templateError}</p>}
      {deletedName && <p role="status">Törölve: {deletedName}</p>}
      {busy && <p role="status">Művelet folyamatban…</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            type="button"
            disabled={working}
            onClick={() => {
              setError("");
              setSourcesRetry(sourcesRetry + 1);
            }}
          >
            Forráslista frissítése
          </button>
        </p>
      )}
      {analysing && !detailsError && (
        <p role="status">A fájl elemzése folyamatban…</p>
      )}
      {unusable && (
        <p role="alert">
          {run?.error ||
            "Ehhez az importhoz nem érhetők el elemezhető oszlopok."}
        </p>
      )}
      {run && !preparation && !analysing && !unusable && !detailsError && (
        <p role="status">Forrásoszlopok betöltése…</p>
      )}
      {detailsError && (
        <p role="alert">
          {detailsError}{" "}
          <button
            type="button"
            disabled={working}
            onClick={() => {
              setDetailsError("");
              setDetailsRetry(detailsRetry + 1);
            }}
          >
            Újrapróbálás
          </button>
        </p>
      )}
    </div>
  );

  const showSetup = !preparation || setupKey === viewKey;

  return (
    <div className="template-preparation">
      <section className="card padded prep-setup" hidden={!showSetup}>
        <h2>Előkészítés / Sablonkészítés</h2>
        <div className="prep-start">
          <label>
            Webshopmotor
            <select
              aria-label="Webshopmotor"
              value={engine}
              disabled={!catalog || working}
              onChange={(event) => {
                setEngine(event.target.value);
                changeSupplier(0);
              }}
            >
              <option value="">Válassz webshopmotort</option>
              {catalog?.engines.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Pénznem
            <select
              aria-label="Pénznem"
              value={currency}
              disabled={!catalog || working}
              onChange={(event) => {
                setDetailsError("");
                setCurrency(event.target.value);
              }}
            >
              {(catalog?.currencies ?? [currency]).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
        {validEngine && sourceControls}
        {!catalog && !catalogError && (
          <p role="status">Webshopmotor betöltése…</p>
        )}
        {catalogError && (
          <p role="alert">
            A sablonkészítés nem érhető el. {catalogError}{" "}
            <button
              type="button"
              onClick={() => {
                setCatalogError("");
                setCatalogRetry(catalogRetry + 1);
              }}
            >
              Újrapróbálás
            </button>
          </p>
        )}
      </section>
      {catalog && validEngine && preparation && showSetup && (
        <button type="button" disabled={working} onClick={() => setSetupKey(undefined)}>
          Tovább az összerendeléshez
        </button>
      )}
      {catalog && validEngine && preparation && (
        <div className="template-preparation prep-editor-stage" hidden={showSetup}>
          {!showResult && (
            <button type="button" disabled={working} onClick={() => setSetupKey(viewKey)}>
              Vissza az előkészítéshez
            </button>
          )}
          <TemplateEditor
            key={viewKey}
            api={api}
            catalog={catalog}
            view={preparation.initial}
            initialDefaults={preparation.initial.defaults}
            currency={currency}
            canSave={canSave}
            currencyWarnings={preparation.latest.warnings}
            currencyBusy={preparation.currency !== currency}
            showResult={showResult}
            setShowResult={setShowResult}
            onBusy={setSaving}
            onSaved={(saved) => {
              setSavedTemplate({ key: viewKey, id: saved.id });
              setVersionGroup(0);
              setTemplatesRetry((value) => value + 1);
            }}
          />
        </div>
      )}
      {deletion && (
        <ImportDeletionDialog
          api={api}
          target={deletion}
          onCancel={() => setDeletion(undefined)}
          onDeleted={(result) => afterDeletion(deletion, result)}
        />
      )}
    </div>
  );
}
