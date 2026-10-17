# User flow

Status: implemented; local browser and live API verification are recorded in [Verification](Verification.md). Companion: [繁體中文](UserFlow.zh-TW.md). View IDs: [Frontend](Frontend.md). Function IDs: [Backend](Backend.md).

## UF01 — Navigate and query

```text
WORKSPACE → NAV-ADMIN (Admin) → NAV-Q → V-QUERY idle → choose Q-FUNC → optional Q-ID → Q-RUN
  ├ invalid input: field error → correct input → Q-RUN
  └ valid: loading (Q-RUN disabled) → API outcome + independent save outcome
        ├ success object/list → table ↔ JSON
        ├ success empty list → explicit empty state
        ├ upstream HTTP failure → status + safe error body
        ├ transport failure → no HTTP status + safe error
        └ any captured outcome with persistence failure → failed to write
```

Q-FUNC updates ID requirements; changing function clears stale field errors. Q-TABLE/Q-JSON change only presentation. A successful result with `failed to write` remains visible but is unavailable in persistent history. Missing configuration or local API unavailability shows a local error distinct from a Nessie status. Retry means pressing Q-RUN again and makes one new request; no automatic retry or background refresh is introduced. Preserve a pending request's identity so a delayed response cannot be presented as another query's result.

Opening NAV-ADMIN initially chooses V-QUERY; returning restores its retained inner view. Switching to Overview & transactions or Confirmed memory preserves the Admin form/result and selection without querying again. A running query can complete into retained Admin state; navigation never automatically resubmits it. The existing dashboard source and memory consent flow remain unchanged.

NAV-H opens history and loads the first page through P05. NAV-C opens the retained comparison, or an empty selection message linking back to history. Navigation itself does not initiate a new Nessie query.

## UF02 — Inspect and select history

NAV-H: loading → populated, empty, or read error. H-MORE loads another page while retaining previous rows and selections. H-VIEW-{id} opens H-DETAIL with the saved response, source, and original time; H-TABLE/H-JSON switch its presentation. No query is recorded for inspecting saved data.

H-L-{id}/H-R-{id} choose two distinct records. H-COMPARE stays disabled with an explanation until query, resource ID, and source match. A valid selection invokes P07 and transitions to V-COMPARE. The server revalidates selection independently; 404 clears the stale selection and returns to history, while 409 leaves records intact and explains incompatibility. A database error retains the selection for a later retry.

## UF03 — Compare and return

V-COMPARE: loading → changed, unchanged, outcome-changed, or error. Show each original UTC time and duration in its own header, without marking those as data changes. C-TABLE/C-JSON switch both bodies locally. C-DIFF labels additions/removals/field changes and missing-versus-null values. C-BACK returns to V-HISTORY with existing selection and loaded rows. When there is no selection, show a route to history rather than an invented comparison.

## UF04 — Delete history

```text
H-DELETE-{id} / H-CLEAR → V-CONFIRM (scope visible)
  ├ D-CANCEL / Escape → close, restore focus, zero requests
  └ D-CONFIRM → deleting
        ├ commit succeeds → remove affected history, clear stale selection/detail
        └ error → show failure, retain rows and selection; allow retry
```

Confirmation sends `{confirm:true}` to P08/P09. It grants only the displayed local-history scope. Clearing history does not clear seed progress, delete fixture files, or issue upstream DELETE calls. If a record has already disappeared, report 404 and refresh the visible list. The action is permanent within the app; no undo or recovery system is part of this version.

## UF05 — Initial baseline setup outside the UI

The developer supplies `NESSIE_API_KEY` securely in the backend environment and runs the seed command. Validation and progress checks precede outbound writes. The integration probe covers one customer/account and six transactions; stop on incompatible server behavior before bulk continuation. Successful mappings supply real IDs for the query form.

```text
validated baseline → run scope → pending persisted → remote create/readback
  ├ confirmed → persist mapping → next dependent record
  ├ known rejection → safe error, stop
  └ ambiguous result → reconcile
        ├ unique verified match → confirmed
        └ missing/ambiguous → blocked; no blind POST retry
completed rerun → verify mappings → skip confirmed → zero new records
```

No import/reset button is added to the read-query UI. Scope/key/dataset mismatch stops for reconciliation; it does not silently recreate or delete resources. Local history clearing leaves this setup state usable.

## Coverage

UF01 covers NAV-ADMIN/Q-FUNC/Q-ID/Q-RUN/Q-TABLE/Q-JSON and AC01–AC04/AC08/AC12. UF02 covers NAV-H/H-MORE/H-VIEW/H-TABLE/H-JSON/H-L/H-R/H-COMPARE and AC04–AC06. UF03 covers NAV-C/C-BACK/C-TABLE/C-JSON and AC05–AC06. UF04 covers H-DELETE/H-CLEAR/D-CANCEL/D-CONFIRM and AC07. UF05 covers setup and AC02/AC09–AC10. Every view includes a usable loading, empty, and error return path. Design-reference-only P-STATE/P-CASE controls are excluded from product flows.
