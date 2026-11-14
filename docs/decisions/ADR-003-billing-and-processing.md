# ADR-003: Capacity plans, no row-consumption quota, separate AI credits

- **Status:** Accepted product decision; **not yet implemented**.
- **Decision:** Subscription plans regulate stored product capacity, users, suppliers, companies, stores and import technical limits. Normal imports and price/stock refreshes do not use a monthly processed-row balance. AI enrichment consumes separate credit buckets; purchased credits never expire. Automated supplier synchronization is a plan-gated feature or extra add-on.
- **Why:** High-frequency supplier stock feeds can refresh hundreds of thousands of rows without proportionate AI/provider cost; two independently diminishing balances would be confusing.
- **Supersedes:** Previous decisions that counted every imported row and renewed a monthly processing allowance.
- **Consequences:** Implement cost controls using upload/concurrency/cadence limits, not a processed-row ledger. Refer to `docs/modules/BILLING.md` for future full lifecycle.
