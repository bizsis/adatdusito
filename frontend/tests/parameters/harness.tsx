/** Test-only transport. These synthetic URLs/payloads are NOT CATEGORY-03A API proposals. */
import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ParameterWorkspace } from "../../src/parameters/ParameterWorkspace";
import {
  ParameterRevisionConflict,
  type ParameterPorts,
  type ParameterServices,
} from "../../src/parameters/presentation";
import { ProductData } from "../../src/ProductData";
import { ImportWorkspace } from "../../src/ImportWorkspace";
import type { ClassificationPresentation } from "../../src/classification/presentation";
import "../../src/tokens.css";
import "../../src/style.css";
function Harness() {
  const [workspace, setWorkspace] = useState("one");
  const [jobKey, setJobKey] = useState("job-A");
  const q = new URLSearchParams(location.search);
  const readonly = q.has("readonly");
  const missing = q.has("missing-writes");
  const ports = useMemo<ParameterPorts>(() => {
    async function request<T>(
      operation: string,
      payload: unknown,
      signal: AbortSignal,
    ): Promise<T> {
      const response = await fetch(
        `/__category03b_test__/${workspace}/${operation}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: q.has("ignore-abort") ? undefined : signal,
        },
      );
      if (response.status === 409)
        throw new ParameterRevisionConflict(
          "A paraméterrevízió időközben megváltozott (409).",
        );
      if (!response.ok)
        throw new Error(`Tesztelt API-hiba (${response.status}).`);
      return response.json() as Promise<T>;
    }
    return {
      read: (productKey, filters, cursor, s) =>
        request("diff", { productKey, filters, cursor }, s),
      values: (rowKey, search, cursor, s) =>
        request("values", { rowKey, search, cursor }, s),
      preview: missing
        ? undefined
        : (intent, s) => request("preview", intent, s),
      apply: missing ? undefined : (preview, s) => request("apply", preview, s),
      snapshot: missing
        ? undefined
        : (productKey, s) => request("snapshot", { productKey }, s),
      job: (key, s) => request("job", { key }, s),
      resume: (job, s) => request("resume", job, s),
      cancel: (job, s) => request("cancel", job, s),
    };
  }, [workspace, missing]);
  const services: ParameterServices = {
    ports,
    access: {
      edit: !readonly,
      unlock: !readonly,
      approve: !readonly,
      bulk: !readonly,
      manageJobs: !readonly,
    },
  };
  const product = {
    key: "product-1",
    title: "Mosógép – paraméterteszt",
    ownCategory: "Saját / Mosógépek",
    internalPath: "Háztartási gépek és klíma / Elöltöltős mosógépek",
  };
  const classification = useMemo<ClassificationPresentation>(
    () => ({
      workspaceKey: workspace,
      parameterPreparation: services,
      access: {
        editProducts: false,
        editMappings: false,
        bulkEdit: false,
        manageThreshold: false,
      },
      ports: {
        products: async () => ({
          items: [
            {
              key: product.key,
              title: product.title,
              identifier: "0001",
              source: "Teszt beszállító",
              originalCategory: product.ownCategory,
              ownCategory: product.ownCategory,
              internalCategory: null,
              group: "review",
              explanation: "Teszt",
              confidencePercent: null,
              alternatives: [],
              origin: "Teszt",
              protectedEdit: false,
              auditText: "",
              donorText: "",
              editContext: null,
            },
          ],
          next: null,
          total: 125000,
          categories: [],
          sources: [],
        }),
      },
    }),
    [workspace, ports, readonly],
  );
  return (
    <main className="padded">
      <p className="notice">
        Csak tesztmock – nem valódi paraméter-API-integráció.
      </p>
      <button onClick={() => setWorkspace(workspace === "one" ? "two" : "one")}>
        Teszt: munkaterület váltása
      </button>
      {q.has("import-integration") && (
        <button onClick={() => setJobKey("job-B")}>Teszt: futás váltása</button>
      )}
      {q.has("product-integration") ? (
        <ProductData
          api={() => Promise.reject(new Error("No legacy API in this test"))}
          classification={classification}
        />
      ) : q.has("import-integration") ? (
        <ImportWorkspace
          api={async <T,>(path: string) => [] as T}
          canManage={false}
          parameterJob={{
            ...services,
            initial: {
              key: jobKey,
              context: {},
              state: "paused",
              progressPercent: null,
              processed: 0,
              total: null,
              changed: 0,
              skipped: 0,
              failed: 0,
              message: "Tesztfutás",
              errors: [],
              canResume: true,
              canCancel: false,
            },
          }}
        />
      ) : (
        <ParameterWorkspace
          workspaceKey={workspace}
          product={product}
          {...services}
        />
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Harness />);
