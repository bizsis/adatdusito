# Subscription, AI credits and billing — approved design, NOT implemented

**Status:** product decisions awaiting later development. No production payment/invoice or credit-deduction service is implied.

## Plans and trials
- Public email/password and Google registration should create an own tenant and time-limited trial after secure registration is built.
- Trial limited by configurable days, stored product count and trial AI credits, with admin/customer overrides.
- Trial credits expire on trial end. Trial/expired paid tenants have default **30-day configurable read/export-only grace**; afterward data stays locked/retained, not auto-deleted.
- Plans have monthly/annual prepaid pricing, storage/capacity features and bundled AI credits. On annual subscriptions credits are still issued **monthly**.

## Three credit buckets
1. Trial credits expire with trial.
2. Subscription credits roll over or expire as configured per plan; monthly grant and optional cap.
3. Purchased credits never expire.
Consumption: earliest-expiring first, then non-expiring subscription bucket, then purchased credits. Ledger must preserve prices, consumption source and cost of underlying AI provider calls.

## Consumption
- Provider-specific actual input/output cost and configurable FX, markup, rate and model. If an AI provider charges for a failed task, associated credits can be consumed; no charge without real provider use.
- Reserve per-task budget; stop and request approval when projected charge crosses cap; retain partial results.
- Optional auto top-up with threshold, package and monthly spend cap; disabled by default, credit only on confirmed payment, idempotent transaction handling.

## Capacity and feed pricing
- **No monthly processed-row quota** and no per-import processing unit balance (prior decisions superseded).
- Normal CSV/XLSX imports and stock/price refreshes are included in the subscription, subject to configurable plan-level file size, row count, concurrency and cadence limits.
- Automatic supplier synchronization is a separately enabled plan feature or add-on.
- Stored product, supplier, user, company and shop capacity limits are configurable.
- Stackable plan-compatible add-ons may be one-off or recurring monthly/yearly. Recurring add-on upgrades are prorated; downgrades effective at paid-through date.
- Over-capacity state is read/export-only, never destructive.

## Lifecycle
- Upgrade: immediate on successful prorated charge, including prorated subscription-credit difference until monthly grant date.
- Downgrade: at next renewal. Cancellation: paid-through expiry; monthly grants continue while prepaid coverage remains.
- After expiration, configurable grace; purchased credits retained.

## Payment and invoicing
- Provider-agnostic architecture. Initial payment provider undecided (e.g., Stripe or Barion).
- Initial invoicing provider undecided (Billingo or Számlázz.hu); **Paksi Informatika issues all SaaS invoices**.
- Tenant can manage own billing profile and view invoices, not provide a tenant-owned invoicing account for SaaS service fees.

## Decisions still open
Provider order; transfer/card/manual payment; supported currencies, VAT and cross-border invoicing; stored product/variant counting; duration of one-off add-ons; credit rollover on cancellation/reactivation; refunds and chargebacks; hard budget-stop resume flow; price changes and notice; retention/erasure policy.

No arbitrary numeric plan prices, trial allowances or tax rules should be fabricated.
