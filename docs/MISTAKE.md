# Mistake log

Companion: [繁體中文](MISTAKE.zh-TW.md). Only observed mistakes are recorded.

## [2026/10/17 18:24] — Shared files replaced during concurrent workspace changes

- Observation: another workflow introduced a tracked TrustLedger starter during the Nessie interview. Creating a root AGENTS file and docs index from the earlier empty-workspace assumption replaced those two existing files.
- Cause: repository state was not refreshed immediately before writing shared paths; an add-file operation can replace an existing file.
- Correction: recovered both tracked originals from Git `636ab15`, verified their original contents remain intact, and retained only additive links. Moved the new bilingual index to `docs/v0.0.0/`. Asked Q020 rather than assuming integration authority; preserved unrelated working-tree changes.
- Prevention: recheck shared-file existence and Git state before writing them after a long interview or external workspace change. Keep proposals scoped to their version directory and preserve existing project instructions, owners, contracts, and CI.

## [2026/10/17 18:24] — Interview continuation omitted after fixture delivery

- Observation: after synthetic-data generation, the response reported the completed data task without presenting the next unresolved workflow question. The user had to request continued questioning.
- Cause: a supporting deliverable was treated as the stopping point of the ongoing requirements interview.
- Correction: D004 resumed clarification, resolving data integration, timestamp comparison, persistence failure, and importer replay before drafting designs.
- Prevention: after a detour, restore the original active objective and identify the next material unresolved decision; completion of fixtures does not close the design question gate.

## [2026/10/17 18:59] — Import preflight did not cover marker drift

- Observation: independent review reproduced duplicate synthetic markers when another field changed, and bulk customer writes before detecting a changed probe transaction.
- Cause: marker detection reused full-payload equality, while bulk preflight checked only confirmed flags and balance.
- Correction: block any untracked marker, require one fully matching marker on reconciliation, and read back all eight probe entities before bulk writes. Regression tests failed before the fix and passed afterward; the same reviewer confirmed both before real continuation.
- Prevention: distinguish record identity from payload equality, and verify every dependency of a write barrier.

## [2026/10/17 19:05] — Final integration boundaries missed in initial implementation

- Observation: a delayed history list restored deleted rows; non-probe accounts could be confirmed with incorrect opening balances. Independent review reproduced both.
- Cause: history loads had no ordering guard, and Q024's static-balance change did not update the shared account matcher.
- Correction: ignore stale history generations and match all account payload fields. Both regressions failed before fixes; the same reviewer independently verified the corrected browser flow and 30 affected backend tests.
- Prevention: invalidate asynchronous reads after newer mutations, and revisit shared comparison rules when live semantics change.
