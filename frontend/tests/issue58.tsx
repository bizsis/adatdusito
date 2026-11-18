import React from "react";
import { createRoot } from "react-dom/client";
import {
  ImportMappingWizard,
  type MappingColumn,
  type MappingReview,
  type MissingReview,
} from "../src/import-mapping/ImportMappingWizard";
import "../src/style.css";

const columns: MappingColumn[] = [
  {
    id: "0",
    name: "SKU",
    samples: ["0001", "0002", "0003"],
    savedChoice: { kind: "field", key: "sku" },
  },
  {
    id: "1",
    name: "NAME",
    samples: ["Televízió"],
    savedChoice: { kind: "field", key: "name" },
  },
  {
    id: "2",
    name: "Kategória",
    samples: ["Saját / Kijelzők"],
    savedChoice: { kind: "field", key: "category" },
  },
  {
    id: "3",
    name: "Net price",
    samples: ["25000"],
    savedChoice: { kind: "field", key: "net" },
  },
  {
    id: "4",
    name: "Bruttó ár",
    samples: ["31750"],
    suggestion: { choice: { kind: "field", key: "gross" }, confidence: 0.99 },
  },
  {
    id: "5",
    name: "Barcode",
    samples: ["0052011370618", "8,71999E+12"],
    warnings: ["Tudományos jelölésű EAN: ellenőrizd a teljes azonosítót."],
    suggestion: { choice: { kind: "field", key: "gtin" } },
  },
  {
    id: "6",
    name: "Color",
    samples: ["Fekete"],
    suggestion: {
      choice: { kind: "newParameter", name: "Szín" },
      confidence: 0.92,
    },
  },
  { id: "7", name: "Unknown_01", samples: ["Megőrzött adat"] },
];

const engines = [
  {
    id: "unas",
    name: "UNAS",
    fields: [
      { key: "sku", label: "Cikkszám", required: true },
      { key: "name", label: "Termék Név", required: true },
      { key: "category", label: "Kategória", required: true },
      { key: "net", label: "Nettó Ár", required: true },
      { key: "gross", label: "Bruttó Ár", required: true },
      { key: "status", label: "Státusz", required: true },
      { key: "gtin", label: "EAN", required: false },
    ],
    providedFields: { status: "alapértelmezett érték: 1" },
  },
];

async function approve(review: MappingReview): Promise<MissingReview> {
  window.dispatchEvent(new CustomEvent("mapping-approved", { detail: review }));
  return {
    canProceed: true,
    donorLabels: ["Televíziók"],
    parameters: [
      { key: "tv:size", name: "Képátló", required: true },
      { key: "tv:resolution", name: "Felbontás" },
      { key: "tv:size", name: "Képátló", required: true },
      { key: "tv:refresh", name: "Képfrissítés" },
    ],
  };
}

async function select(keys: readonly string[]) {
  window.dispatchEvent(new CustomEvent("mapping-parameters", { detail: keys }));
}

createRoot(document.getElementById("root")!).render(
  <main>
    <ImportMappingWizard
      fileName="beszallito.csv"
      productCount={3}
      engines={engines}
      columns={columns}
      onApproveMapping={approve}
      onSelectParameters={select}
    />
  </main>,
);
