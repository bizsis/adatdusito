# ADR-002: Curated category tree and eMAG reference parameter system

- **Status:** Accepted; current category/catalog implementation exists.
- **Decision:** Present exactly 13 approved Hungarian first-level category groups, with curated descendants. The eMAG category/parameter/value data is a **read-only reference**. AI/product mapping must use the selected eMAG parameter system, not invent a second competing parameter ontology. Incoming upstream categories do not automatically change the visible tree.
- **Why:** Stable customer UX, consistent UNAS mappings, controlled taxonomy governance.
- **Consequences:** Version the application's own catalog; review category changes, preserve imported source category references and separation of reference DB.
- **Evidence:** `README.md`, `backend/app/reference.py`, `backend/app/catalog_import.py`.
