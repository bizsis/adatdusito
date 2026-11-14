# Supplier import engine — implemented CODEX 07 baseline

**Code:** `backend/app/import_api.py`, `backend/app/import_models.py`, Celery import processing; detailed history: `docs/codex-07-import-engine.md`.

## Workflow
1. Select an accessible tenant workspace and supplier.
2. Upload CSV/XLSX, inspect normalized/header preview with source columns preserved.
3. Confirm mapping of supplier columns to internal fields. Financial semantics (net/gross, currency, VAT, buy/sell price) are not invented.
4. Choose an exact match key for later feed linking; do not merge on merely similar names.
5. Save a reusable supplier import profile and approve a run.
6. Background worker processes rows in chunks; review status/errors, source references, product/change history.

## API evidence
`/api/v1/imports/suppliers`, `/profiles`, `/runs`, `/runs/{id}/rows`, `/runs/{id}/approve`, `/runs/{id}/actions/{action}`, `/runs/{id}/errors.csv`, `/products`, `/products/{id}/changes`, `/export-profiles`, `/engines`, additional preview/mapping/settings endpoints.

## Data and safety
Entity classes: `Supplier`, `ImportProfile`, `ImportRun`, `ImportChunk`, `ImportRow`, `SupplierProduct`, `ImportChange`, `StoreEngine`, `StoreProfile`.
Preserve source field values and trace mapping decisions. Server-side authorization applies to each tenant. Upload limits and XLSX decompression safety exist; see security backlog for proxy mismatch.

## Not yet implemented by this module
AI research, fully automated 15-minute supplier polling, AI credit deductions, production UNAS API writeback, complete identity reconciliation across all suppliers. Export profile / field administration is **not** proof of completed UNAS synchronization.
