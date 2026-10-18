# Architecture

This file describes the selected architecture. Jev is reached through Backboard's System One API, not through `https://api.typesafe.ai`. The direct TypeSafe route remains an unused option documented by TypeSafe. Target-design notes in [docs/00-overall-architecture-report.md](docs/00-overall-architecture-report.md) still describe the product shape.

Diagrams, preserved and still useful for the target shape:

- [docs/diagrams/architecture.mmd](docs/diagrams/architecture.mmd)
- [docs/diagrams/data-flow.mmd](docs/diagrams/data-flow.mmd)
- [docs/diagrams/review-sequence.mmd](docs/diagrams/review-sequence.mmd)
- [docs/diagrams/git-collaboration.mmd](docs/diagrams/git-collaboration.mmd)
- [docs/diagrams/threat-boundaries.mmd](docs/diagrams/threat-boundaries.mmd)
- [docs/diagrams/integration-order.mmd](docs/diagrams/integration-order.mmd)

The `.svg` files and `docs/index.html` are snapshots of that design. The Mermaid sources remain the editable diagrams. The memory node in `data-flow.mmd` now says SQLite is the store that runs.

## What runs

```mermaid
flowchart LR
  user[Demo user]
  ui[React UI]
  api[FastAPI]
  fixture[Synthetic JSON fixture]
  rules[Rules and allowlist]
  db[(SQLite local-fallback)]

  user --> ui
  ui -->|/api/v1 via Vite proxy| api
  fixture --> api
  api --> rules
  rules --> api
  api --> ui
  api -->|normal plus consent| db
  db -->|category label only| rules
```

Nessie is not called. Jev is called only through Backboard, and only when a server-side key is present. Memory writes stay in SQLite.

## Modules

| Module | Path | Runtime behavior | Owner |
|---|---|---|---|
| React UI | `frontend/src/main.tsx`, `frontend/src/api.ts` | Loads health, transactions, alerts, and memories. Posts a confirmation. Renders the preview JSON it received | Ian |
| FastAPI app | `backend/app/main.py` | Loads the synthetic fixture once, opens SQLite, adds CORS and error handlers | Benson |
| Routes | `backend/app/api/routes.py` | Lists data, runs analysis, saves confirmations, reads memories back into analysis | Benson wires; Brian defines the analysis |
| Synthetic adapter | `backend/app/adapters/synthetic.py` | Reads `fixtures/synthetic-transactions.json` | Kenny |
| Nessie adapter | `backend/app/adapters/nessie.py` | Raises `NessieNotConfigured` | Kenny |
| Transaction model | `backend/app/schemas/transaction.py` | Canonical fields, `extra=forbid` | Kenny |
| API models | `backend/app/schemas/api.py` | Health, analysis, safe payload, memory | Benson, with Brian on payload fields |
| Privacy guard | `backend/app/services/ai/privacy.py` | Builds the eight-field allowlist and the inspector rows | Brian |
| Rules | `backend/app/services/ai/rules.py` | Duplicate, amount at least 250, subscription increase over 20 percent | Brian |
| Memory policy | `backend/app/services/ai/memory_policy.py` | Writes a category sentence and parses it back to `normal` or `unknown` | Brian |
| Jev client | `backend/app/services/ai/jev_client.py` | Backboard `POST /threads/messages` when `BACKBOARD_API_KEY` is set | Brian |
| Decision merge | `backend/app/services/ai/decision.py` | Keeps the rule result. Labels Jev only after a valid response | Brian |
| Backboard memory client | `backend/app/services/ai/backboard_client.py` | `NotImplementedError`. Inference does not enable memory | Brian |
| SQLite store | `backend/app/core/store.py` | Scoped to `demo-user-001`. Idempotent confirmation. Delete by memory id | Benson |
| Settings | `backend/app/core/config.py` | Loads `backend/.env`. Empty vendor keys | Benson |

## Data flow that exists today

1. `create_app` calls `load_transactions()` in the synthetic adapter. Eight `Transaction` objects stay in memory for the process.
2. `GET /api/v1/transactions` returns those objects. The React table shows merchant, category, date, and amount. That display is local. It is not an AI request.
3. `GET /api/v1/alerts` runs `analyze` for each transaction. A non-`none` result becomes an alert. The fixture produces three: StreamWave duplicate, Tech Harbor amount, FitFlow subscription increase.
4. `GET /api/v1/privacy/preview/{id}` builds `SafePayload` from the same functions. The inspector prints `inspection` and `safe_payload`. The UI does not construct a second payload.
5. Allowed payload fields are `merchant_category`, `amount_bucket`, `currency`, `local_day_part`, `same_category_same_amount_24h_count`, `is_subscription`, `subscription_delta_bucket`, and `prior_user_confirmation`.
6. Dropped before that object: transaction id, account token, merchant display, exact amount, exact timestamp, and any unknown field.
7. The user chooses `normal` or `review`. Memory is written only when the decision is `normal`, the consent box is checked, and `ALLOW_MEMORY_WRITE` is true.
8. The stored sentence is `The demo user explicitly confirmed a {category} alert as normal. Recheck future evidence.` The category is one of the allowlisted labels, or `other`.
9. The next alerts call, analysis call, and preview call read those sentences for the demo user. A matching category sets `prior_user_confirmation` to `normal` and adds an evidence line. `needs_human` stays true. Another category stays `unknown`.
10. `DELETE /api/v1/memories/{id}` removes that row. The following preview is `unknown` again.
11. `GET /api/v1/health` returns `data_mode=synthetic`, `analysis_mode=rules-only`, and `memory_mode=local-fallback` or `off`.

`review` and consent turned off do not write a sentence. The parser therefore never returns `review` from stored memory. The schema still allows that label for a future client.

## What is mocked

| Promised integration | Code | What a caller would see |
|---|---|---|
| Jev through Backboard | `POST https://app.backboard.io/api/threads/messages` with `httpx` | `provider_mode=rules+jev-live` only after a parsed `system_one.answers` |
| Direct TypeSafe API | Not used | No request to `api.typesafe.ai` |
| Missing key | No outbound call | `provider_mode=rules-only` |
| Backboard timeout, non-200, or invalid answers | Rules kept | `provider_mode=degraded`. Not described as live Jev |
| Backboard memory | Stub | SQLite sentence, `source=local-fallback`. The inference request omits `memory` |
| Nessie | Stub | `source=synthetic` |
| Authentication | Fixed `demo-user-001` | The browser cannot select another user |
| Hosting | None | Localhost ports 5173 and 8000 |

## Selected Jev route

Official reference: [Backboard System One](https://docs.backboard.io/concepts/system-one).

```text
React → FastAPI → privacy allowlist → Backboard REST → TypeSafe Jev
```

The client sends:

- `POST https://app.backboard.io/api/threads/messages`
- Header `X-API-Key: $BACKBOARD_API_KEY`. This is the Backboard key. `JEV_API_KEY` is not sent.
- `llm_provider` = `typesafe`
- `model_name` = `jev-latest`
- `stream` = `false`
- `system_one.state` = the eight `SafePayload` fields
- `system_one.questions` = `pattern` (choice) and `needs_review` (noul)
- No `thread_id`, so each decision starts a new thread
- No `memory` parameter, so assistant memory stays off

`system_one.model` in the response is the resolved model, such as `jev-1.13.0`. The code stores that string in `model_version`. The rule's `alert_type`, severity, and `confidence=1.0` stay as they were. A Jev label is one extra evidence line. `needs_human` stays true when the rule flagged the transaction.

`GET /api/v1/alerts` calls Jev only for rows the rules already flag. `POST /api/v1/analyses` calls Jev for the requested transaction when the key is set. Health reports `rules+jev-live` or `degraded` only after one of those calls records that outcome. A key by itself does not make health say live.

### Optional direct TypeSafe route

TypeSafe also documents `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer` and `TYPESAFE_API_KEY`. TrustLedger does not call that URL and does not install `typesafe-sdk`. Do not switch to it unless the team replaces this decision. `docs/.env.example` values `JEV_BASE_URL=https://jev-ai.org/api/v1` and `JEV_MODEL=jev-1.13` are still unread leftovers.

## Backboard memory

Persistent memory is explicit CRUD. The Jev request still omits `memory`, so classification does not write assistant memory.

The local map is one `assistant_id` per demo owner, created with `POST /assistants` and reused. The browser cannot choose it. The create body is a fixed name and system prompt, with no owner id and no transaction text.

| Behavior | What the code does |
|---|---|
| Isolation | SQLite table `assistants` stores the first id for that owner. Later reads and deletes use only that id |
| Consent | Remote and local writes run only when the decision is `normal`, consent is checked, and `ALLOW_MEMORY_WRITE=true` |
| Content | The category sentence only. `add_memory` rejects any other text before the request |
| Retrieval | `GET /assistants/{assistant_id}/memories` merges approved remote sentences into `prior_confirmation`. Search is available to the adapter and is not used to decide the label, because a semantic miss would drop a known confirmation |
| Deletion | A `backboard` row is deleted remotely first. HTTP 200 with `success: true`, or HTTP 404 when it is already gone, then deletes the local row. `success: false` or another failed call returns 502 and keeps the row |
| Failure | The confirmation still commits. The sentence is stored once as `source=local-fallback` with `memory_status=failed`. It is not labeled `backboard` |
| No key | No memory HTTP call. SQLite only, `source=local-fallback`, health `local-fallback` |

Health reports `backboard-live` only after a memory call in this process returns a parsed success. A key by itself does not. A failed memory call sets `degraded`. Live memory is not verified until a real provider response succeeds.

## Nessie, when someone adds it

- Public product entry: [api.nessieisreal.com](http://api.nessieisreal.com/).
- Kenny's adapter normalizes sandbox records into `Transaction` and drops raw ids before returning.
- Benson selects it from `main.py` only behind a failure path back to the fixture.
- Endpoint paths and the key's query or header placement are UNVERIFIED here because the stub makes no request. Confirm them on the Nessie documentation page before coding a URL.

## Security boundary

The browser holds no vendor key. Vendor keys, if later set, stay in `backend/.env`. The privacy boundary is the `SafePayload` constructor, not a comment in the UI. Details and the threat list: [docs/06-security-privacy-threat-model.md](docs/06-security-privacy-threat-model.md).

## Current project status

| Item | State | Owner | Priority | Next step | Done when |
|---|---|---|---|---|---|
| Synthetic load, 3 alerts, review, inspector | DONE | Shared | — | Keep it green | `check.sh` passes and the click path works |
| SQLite memory affects the next analysis | DONE | Brian content, Benson store | — | Merged in PR #3 | Preview shows `normal` only for that category, then `unknown` after delete |
| Jev through Backboard | IMPLEMENTED behind `BACKBOARD_API_KEY` | Brian | P1 | A real response must be seen before calling the demo live | Mocked tests cover success and failure. A missing key stays `rules-only` |
| Backboard persistent memory | IMPLEMENTED behind `BACKBOARD_API_KEY` | Brian, with Benson on the route and store | P1 | A real memory response must be seen before calling the demo live | Mocked tests cover consent, isolation, read, delete, and SQLite fallback |
| Nessie live read | NOT STARTED | Kenny | P1 | Read-only mapper plus synthetic fallback | CI passes with no key and makes no network call |
| Health mode after a provider attempt | DONE | Benson's route records Brian's result | — | `rules+jev-live`, `backboard-live`, or `degraded` only after a call | A key alone changes neither mode |
| Frontend polish and small-screen pass | NOT STARTED | Ian | P1 | Use the current API | Demo path is usable without spoken help |
| Deployment | NOT STARTED | Benson | P2 | No config exists | A URL and SHA are written down, with no secrets in the repo |
| Authentication | NOT STARTED | Benson | P2 | Out of the local demo unless the team cuts scope elsewhere | Not required for the synthetic localhost demo |
| Branch `backend` doc and line endings | IN PROGRESS | Benson | P2 | Open a PR from that branch when ready | `.gitattributes` and `backend/README.md` reviewed without replacing this role doc |
| CI on `main` | DONE | Benson | P0 | Re-run on each PR | The PR #3 merge run `39075769257` passed |
| Branch protection | UNVERIFIED | Benson | P1 | Private-repo API returned HTTP 403 | Settings show required CI, or the team accepts the limit in writing |

No task above is blocked on a missing repository path. Live Jev and live Backboard memory still need a real provider response. Nessie is still a stub. Do not put keys in Git.
