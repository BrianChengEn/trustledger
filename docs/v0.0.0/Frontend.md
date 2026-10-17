# Frontend design

Status: TrustLedger Admin runtime implemented with these references as its working baseline. Authority: [Q020/D008](ArchitectureDecisions.md). Companion: [繁體中文](Frontend.zh-TW.md).

Reuse the existing TrustLedger React/TypeScript shell. Add NAV-ADMIN, labeled exactly `Admin`, below Confirmed memory in the left WORKSPACE section. Keep the existing overview and consent-based memory surfaces. Admin contains NAV-Q (query), NAV-H (history), and NAV-C (comparison) as inner tabs. Do not add another app, server, router dependency, or login screen for the selected single-user local scope. Admin is a navigation label, not an authentication claim.

```text
TrustLedger sidebar          Existing main content area
WORKSPACE                    Admin · Nessie developer console
  Overview & transactions    ┌ NAV-Q ─ NAV-H ─ NAV-C ────────┐
  Confirmed memory           │ V-QUERY / V-HISTORY /         │
  NAV-ADMIN [Admin] ◀         │ V-COMPARE                     │
                             └──────────────────────────────┘
```

NAV-ADMIN first opens V-QUERY without issuing a Nessie request. Returning restores the current inner view, form, result, and history selection within the session. Preserve Admin state while visiting the other workspace entries; only Q-RUN initiates a fresh upstream request. An in-flight request retains its identity and is never silently resubmitted on navigation. Keep presentation state in React; persistence and comparison belong to the backend. Admin content uses Traditional Chinese except exact `Admin`, `failed to write`, and technical fields; retain the current shell language.

Use `frontend/src/main.tsx` for the existing tab entry, add `frontend/src/Admin.tsx` for the console, and extend the existing `api.ts` typed client and `styles.css`. The client already prefixes `/api/v1`; pass `/admin/nessie/...`, avoiding a doubled prefix. Admin query calls need the 25-second timeout described in Backend. Render provider data as text and never submit it to the AI or confirmed-memory flows.

## V-QUERY — Query and result

Selected reference: [option 1](html/view-query/option-1.html). Alternative: [option 2](html/view-query/option-2.html).

```text
┌ NAV-Q: Query ─ NAV-H: History ─ NAV-C: Comparison ┐
│ Q-FUNC [six-query selector                       ▼] │
│ Q-ID   [customer/account ID, when required         ] │
│ Q-RUN  [Query]                                     │
├ Nessie HTTP status · UTC time · duration · Q-SAVE ──┤
│ Q-TABLE [Table]    Q-JSON [JSON]                    │
│ Q-RESULT                                           │
│ ┌ _id ── field ── field ── … ────────────────────┐ │
│ │ Structured response rows, or one object row     │ │
│ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

| ID | Interaction / state |
| --- | --- |
| Q-FUNC | Six query values from Backend; changing it updates the required-ID label and clears stale validation. |
| Q-ID | Labeled customer/account text input; hidden and disabled for list queries. Same validation as P01. |
| Q-RUN | Submit one query; disabled while pending to prevent accidental duplicate submissions. |
| Q-TABLE, Q-JSON | Native toggle buttons with pressed state; switch captured data without fetching again. |
| Q-RESULT | Labeled result region; loading uses a polite live status, request errors use an alert. |
| Q-SAVE | Saved history ID, or the exact visible text `failed to write`; independent of Nessie status. |

Required states: initial instructions; invalid/missing ID; loading; successful object; successful list; empty success; non-2xx response; transport error without HTTP status; missing backend key; backend unavailable; and captured data with failed persistence. A failed write leaves result inspection available. A new pending request must not label a previous result as current; retain it only with its original time until the new outcome arrives.

Tables display the response's available keys, `_id` first; nested values are escaped compact JSON. An object is one row. Scalars/text and errors use a readable text/JSON region rather than pretending to be banking rows. The JSON view preserves all sanitized fields and original list order. Show amounts as supplied numbers, without inventing a currency or converting integer units.

## V-HISTORY — Persistent history and record detail

Selected reference: [option 1](html/view-history/option-1.html). Alternative: [option 2](html/view-history/option-2.html).

```text
┌ NAV-Q ─ NAV-H ─ NAV-C ─────────────────────────────┐
│ [H-COMPARE: Compare selected] [H-CLEAR: Clear all]   │
│ Left  Right  Time · Query · Resource · Status       │
│ (L)   (R)    …                 [View] [Delete]      │
│ H-L-{id} H-R-{id}   H-VIEW-{id} H-DELETE-{id}       │
│ [H-MORE: Load more]                                │
├ H-DETAIL: Original time · source · response status ─┤
│ H-TABLE [Table] H-JSON [JSON] · saved response body  │
└────────────────────────────────────────────────────┘
```

| ID | Interaction / state |
| --- | --- |
| H-L-{id}, H-R-{id} | Two labeled radio groups; retain selections across cursor loads. Require distinct IDs with the same query/resource/source. |
| H-COMPARE | Enabled for compatible selections; invoke P07 and show V-COMPARE. Explain incompatible selection locally. |
| H-VIEW-{id} | Fetch one saved body into H-DETAIL; no new Nessie request. |
| H-TABLE, H-JSON | Reuse result rendering for the saved response; no request. |
| H-DELETE-{id} | Open V-CONFIRM for that record. |
| H-CLEAR | Open V-CONFIRM for all local history. |
| H-MORE | Load the next metadata page; disabled during loading and hidden when exhausted. |

Required states: loading, populated, empty, list-read error, detail loading/error, deleted record 404, incompatible selection, and deletion failure. Reopening NAV-H retries a failed list read. Saved failures remain inspectable; every row shows original query time, query, resource ID, source, upstream status or transport-error category, and duration. Delete success removes affected rows, detail, and selections; failure keeps them visible.

## V-COMPARE — Two saved responses

Selected reference: [option 1](html/view-compare/option-1.html). Alternative: [option 2](html/view-compare/option-2.html).

```text
┌ NAV-Q ─ NAV-H ─ NAV-C ─────────────────────────────┐
│ C-BACK [Back to history]   C-TABLE [Table] C-JSON   │
├ Left history metadata ─────┬ Right history metadata ┤
│ ID / source / UTC time     │ ID / source / UTC time  │
│ Nessie HTTP / duration     │ Nessie HTTP / duration  │
│ C-LEFT: Original snapshot  │ C-RIGHT: Original data  │
├───────────────────────────┴────────────────────────┤
│ C-DIFF: Added / Removed / Changed, or No change      │
│ Record ID · field path · before · after             │
└────────────────────────────────────────────────────┘
```

C-BACK returns to the retained history selection. C-TABLE/C-JSON switch both sides locally. C-LEFT/C-RIGHT and C-DIFF are output regions, not editable data. Mark additions, removals, and changes with text and visual treatment rather than color alone. Distinguish a missing value from literal null. Query time/duration remain visible but do not cause difference highlighting; response business dates and outcome do.

Required states: no selection, loading, compatible data with changes, unchanged data, API-outcome change, missing selected history, incompatible records, and comparison/database error. Show a route back to history in errors. Repeated clicks never requery Nessie. On narrow windows, stack the two labeled snapshots without losing their identity.

## V-CONFIRM — History deletion confirmation

```text
┌ D-CONFIRMATION: Delete local history? ──────────────┐
│ One selected record OR all history; no remote data  │
│ [D-CANCEL: Cancel]        [D-CONFIRM: Delete]        │
└────────────────────────────────────────────────────┘
```

Use a labeled modal dialog with focus containment and return focus to its opener. Escape/cancel performs no request. Confirm disables duplicate submission until the response. Show the scope and permanence of the deletion. Only history is affected; seed mappings stay intact. API confirmation is also required under P08/P09.

## Reference scope and accessibility

Each HTML reference opens locally, uses local CSS/JavaScript and synthetic fixture data, and makes no network API calls. Both variants keep WORKSPACE → Admin in the left sidebar at desktop sizes. Option 1 places the query form beside results; option 2 stacks them and changes the inner card style. Only the inner Admin layout varies. The reference-only P-ALT link switches layouts. The query preview's P-STATE selector and comparison preview's P-CASE selector are reference-only controls to demonstrate states and precomputed examples; they are not new application features or backend actions.

All product control IDs above are stable across the two variants. References use actual fixture values from [history.json](../../datasets/nessie/history.json); their data source is explicitly synthetic. Reference deletion changes only its in-memory example list, not fixture files, SQLite, or Nessie. Native selects/buttons, explicit labels, visible focus, horizontally scrollable tables, text-safe rendering, and meaningful empty/error messages are required in both the reference and later app. See [UserFlow](UserFlow.md) for all state transitions and [Backend](Backend.md) for action mappings.
