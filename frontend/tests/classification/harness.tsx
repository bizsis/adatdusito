/** Test adapter only. All HTTP paths/payloads here are synthetic, NOT backend contracts. */
import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ProductData } from "../../src/ProductData";
import { ImportClassificationSummary } from "../../src/classification/ClassificationSummary";
import {
  ClassificationConflict,
  type PresentationPorts,
} from "../../src/classification/presentation";
import "../../src/tokens.css";
import "../../src/style.css";

function Harness() {
  const [workspace, setWorkspace] = useState("one");
  const settings = new URLSearchParams(location.search);
  const readonly = settings.has("readonly");
  const missingWrites = settings.has("missing-writes");
  const ignoreAbort = settings.has("ignore-abort");
  const ports = useMemo<PresentationPorts>(() => {
    async function request<T>(
      name: string,
      payload: unknown,
      signal: AbortSignal,
    ): Promise<T> {
      const response = await fetch(
        `/__category02_test__/${workspace}/${name}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: ignoreAbort && name === "products" ? undefined : signal,
        },
      );
      if (response.status === 409)
        throw new ClassificationConflict(
          "Az adatok időközben megváltoztak (409).",
        );
      if (!response.ok)
        throw new Error(
          response.status === 403
            ? "Nincs jogosultság a művelethez."
            : "A tesztválasz hibás.",
        );
      return response.status === 204
        ? (undefined as T)
        : ((await response.json()) as T);
    }
    return {
      products: (filters, cursor, signal) =>
        request("products", { filters, cursor }, signal),
      mappings: (search, cursor, signal) =>
        request("mappings", { search, cursor }, signal),
      choices: (search, parent, cursor, signal) =>
        request("choices", { search, parent, cursor }, signal),
      selectMatching: (filters, signal) =>
        request("selection", { filters }, signal),
      preview: missingWrites
        ? undefined
        : (intent, signal) => request("preview", intent, signal),
      apply: missingWrites
        ? undefined
        : (preview, signal) => request("apply", preview, signal),
      threshold: (signal) => request("threshold-read", {}, signal),
      saveThreshold: (percent, signal) =>
        request("threshold-save", { percent }, signal),
    };
  }, [workspace, missingWrites, ignoreAbort]);
  return (
    <main className="padded">
      <h1>Csak tesztkörnyezet: CATEGORY-02B</h1>
      <button onClick={() => setWorkspace(workspace === "one" ? "two" : "one")}>
        Teszt: munkaterület váltása
      </button>
      <ImportClassificationSummary
        runCount={50000}
        assignedCount={49000}
        reviewCount={1000}
      />
      <ProductData
        api={() =>
          Promise.reject(
            new Error("The legacy API must not be used in this harness"),
          )
        }
        classification={{
          workspaceKey: workspace,
          ports,
          access: {
            editProducts: !readonly,
            editMappings: !readonly,
            bulkEdit: !readonly,
            manageThreshold: !readonly,
          },
        }}
      />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Harness />);
