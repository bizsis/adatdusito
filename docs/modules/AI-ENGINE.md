# AI enrichment engine — planned specification

**Status: planned, not implemented in CODEX 08.** The existing supplier import is not equivalent to AI enrichment.

## Target workflow
1. Supplier data ingestion with full original data retention.
2. Product identity resolution using EAN/MPN/supplier keys, with uncertainty handling and no speculative merges.
3. Curated category assignment against the approved 13-group tree.
4. eMAG parameter mapping using existing read-only source dictionaries.
5. Adaptive external research, prioritizing manufacturer and supplier sources; corroborate significant claims across multiple sources.
6. Multi-provider/model inference, normalizing Hungarian descriptions and verified product attributes.
7. Image sourcing with attribution/rights checks and manufacturer preference.
8. Quality control, confidence/explanations and human approval before sensitive changes.
9. UNAS-compatible export with manual edit protection and change tracking.

## Design constraints
- Multi-tenant, resource-scoped jobs; never mix customer-specific facts, prices, availability or source credentials.
- Version provenance, timestamp, citations and evidence per enriched attribute; manual overrides survive updates.
- Cost accounting must track provider actual spend and subscription/purchased credit buckets once billing exists.
- Per-task budget reservation, hard ceiling and explicit approval to extend; preserve partial work.
- Research only when justified by changes; avoid repeat costs for identical unchanged products.
- The reference parameter system is eMAG only; do not create a parallel competing taxonomy.

## Future implementation gates
Schema + worker job state machine; provider and source adapters; safe web/source retrieval; evidence model; budget ledger; reviewer UI; human acceptance tests with synthetic supplier samples.
