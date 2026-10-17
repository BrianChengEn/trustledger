# v0.0.0 Questions and Decisions

Status: v0.0.0 Admin runtime and live baseline import implemented. Q001–Q024 are resolved; Q023/Q024 supersede the initial ID and live-balance assumptions. See D012 and Verification.md.

Source: [user-authored idea](../../idea.md). The explicitly supplied root file is the source of intent and remains read-only; no duplicate idea file is required for this interview.

Companion: [Traditional Chinese](ArchitectureDecisions.zh-TW.md).

## D001 — Current scope

- Recorded: [2026/10/17 17:16] America/New_York.
- Status: confirmed by the user's request.
- Decision: begin the v0.0.0 requirements interview, asking one focused question at a time in Traditional Chinese. Record questions and answers in this bilingual pair.
- Rationale: the user explicitly requested the question phase; product implementation and deployment are outside the current request.

## D002 — Stated concept and constraints

- Recorded: [2026/10/17 17:16] America/New_York.
- Status: user-stated intent; architectural details remain unresolved.
- Source answer: the first stage of an MCP project should follow Occam's razor and use the smallest program. A React frontend lets users select functions and enter instructions to retrieve data. Python translates these actions into Nessie API calls. A database holds sensitive information and temporarily returned data. Results appear in the frontend. The supplied reference is https://prod.nessieisreal.com/.
- Decision: preserve these requirements as the interview baseline. The meaning of MCP, exact request flow, API coverage, credential handling, storage model, and acceptance criteria require clarification.
- Rationale: recording the proposal does not establish unconfirmed technical contracts or storage choices.
- Clarification: [2026/10/17 17:19] America/New_York — Q002 supersedes the original MCP wording with MVP. The remaining user-stated requirements still apply.

## Q001 — Primary use case

- Asked: [2026/10/17 17:16] America/New_York.
- Question: What is the primary use case for the first version?
- Choices:
  - A. A hackathon demonstration, allowing judges to operate the complete data-query flow.
  - B. A developer testing console, making Nessie API queries easier to exercise manually.
  - C. An end-user tool, helping users complete a specific banking-data query.
  - A different use case may be supplied in free text.
- Answered: [2026/10/17 17:17] America/New_York.
- Answer: B — a developer testing console.
- Decision: the first version serves developers manually testing Nessie API queries.
- Rationale: the primary use case determines the minimum workflow and success criteria before selecting features.
- Status: confirmed.

## Q002 — MCP scope in the first version

- Asked: [2026/10/17 17:17] America/New_York.
- Question: What does “the first stage of MCP” require in v0.0.0?
- Choices:
  - A. First build the React, Python, and Nessie testing console; add MCP integration later. Recommended for the smallest initial scope.
  - B. Include an MCP server in this version so an MCP client can also invoke the functions.
  - C. MCP refers to something other than Model Context Protocol; explain its meaning.
- Answered: [2026/10/17 17:19] America/New_York.
- Answer: C — the user meant MVP, not MCP.
- Decision: interpret the concept as a minimum viable product. Remove MCP-specific assumptions from the current scope; no MCP server or future MCP integration is requested.
- Rationale: the term MCP is not defined in the idea, and its inclusion changes the interfaces and acceptance criteria.
- Status: confirmed; original terminology corrected by the user.

## Q003 — Required Nessie queries

- Asked: [2026/10/17 17:19] America/New_York.
- Question: Which Nessie queries must the MVP support?
- Response guidance: list the required queries for the first version. For example, desired queries might include listing customers, querying a customer's accounts, or querying an account's transaction history. These examples describe possible requirements, not verified API contracts.
- Responded: [2026/10/17 17:22] America/New_York.
- Answer: the user requested subagent brainstorming and a list of necessary Nessie queries, emphasizing high priority, before selecting the scope.
- Decision: obtain an independent product-scope proposal and verify candidate paths against official documentation. The proposed query set remains unapproved.
- Rationale: defining the query set establishes the minimum functional scope before choosing API mappings, forms, and stored response data.
- Status: requested analysis completed; all six proposed queries were selected in Q004 on [2026/10/17 17:26] America/New_York. The original recommendation below is retained as proposal history.

### Proposed priorities, not finalized requirements

- Recorded: [2026/10/17 17:23] America/New_York.
- Subagent: `/root/query_priorities`, read-only product brainstorming. It recommended an account-first route with an account list, account details, and one transaction category; customer discovery and other transaction categories can follow.
- Integration judgment: use deposits as the initial transaction category because the retrieved official specification explicitly defines its account-level list. The subagent's initial purchase-list suggestion was provisional and was replaced during verification.

| Priority | Proposed query | Official GET path | Reason |
| --- | --- | --- | --- |
| P0 | List accounts | `/accounts` | Discover account IDs without requiring another tool or a customer lookup. |
| P0 | Retrieve one account | `/accounts/{id}` | Exercise a user-supplied ID and inspect balance, account type, and customer ID. |
| P0 | List an account's deposits | `/accounts/{id}/deposits` | Exercise a related collection, transaction fields, and empty results using the same account ID. |
| P1 | List customers | `/customers` | Discover customer IDs for customer-oriented testing. |
| P1 | List a customer's accounts | `/customers/{id}/accounts` | Test the customer-account relationship. |
| P1 | List an account's withdrawals | `/accounts/{id}/withdrawals` | Add an outflow transaction category after the initial flow works. |

- Recommendation: implement only the three P0 queries initially. An account-first route needs fewer discovery calls than a customer-first route. These are product priorities inferred from the agreed developer-console purpose, not priorities asserted by Nessie.
- Deferred proposal: single-customer details, merchants, ATMs, branches, loans, bills, enterprise queries, and write operations. Account-level purchase and transfer lists require separate verification because they are absent from the retrieved specification; absence from the specification is not proof that the server rejects them. Do not invent a generic transactions endpoint or a merged transaction feed.
- Evidence: [official Nessie OpenAPI 1.0.0](https://prod.nessieisreal.com/nessie-openapi-spec.yaml), retrieved [2026/10/17 17:23] America/New_York, linked by the [official documentation](https://prod.nessieisreal.com/docs) application. All six proposed paths declare GET operations. Raw site assets and the specification are retained at `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-nessie-q003-bte1h09t/`.
- Documentation fallback: Context7 returned only the unrelated Project Nessie data-lake catalog, so no matching library was selected or queried. Official published documentation was used instead.
- Verification limit: no authenticated API request was made, no credentials were accessed, and data availability and actual server responses remain unverified. Product code and `idea.md` remain unchanged.

## Q004 — Select the proposed query scope

- Asked: [2026/10/17 17:23] America/New_York.
- Question: Should the first version include A, only P0, or B, P0 plus P1?
- Choices:
  - A. Only the three P0 queries. Recommended for the smallest complete testing flow.
  - B. All six P0 and P1 queries, including customer-account relationships and withdrawals.
  - The user may propose a different subset.
- Answered: [2026/10/17 17:26] America/New_York.
- Answer: B — include P0 and P1.
- Decision: v0.0.0 must include all six GET queries: account list, account details, account deposits, customer list, customer accounts, and account withdrawals. This selection supersedes the proposed three-query initial scope in Q003.
- Question rationale: select the required query set from the concrete analysis proposal.
- Decision rationale: the user explicitly selected the broader six-query option, including customer-account relationships and withdrawals.
- Status: confirmed.

## Q005 — Meaning of entering instructions

- Asked: [2026/10/17 17:26] America/New_York.
- Question: How should the frontend's instruction input work?
- Choices:
  - A. Select a query function, fill in the required customer ID or account ID fields, and press Query. Recommended.
  - B. Enter a text command in a text box; provide one example of an input that should be supported.
- Answered: [2026/10/17 17:27] America/New_York.
- Answer: A — select a query function and enter its required IDs in form fields.
- Decision: use a function selector, the applicable customer ID or account ID fields, and a Query button. The two top-level list queries require no resource ID. A text-command language is outside the selected input model.
- Rationale: the idea mentions selecting functions and entering instructions but does not define whether instructions mean structured query parameters or a command language. This determines the input controls and parsing responsibilities.
- Decision rationale: the user explicitly selected structured form input.
- Status: confirmed.

## Q006 — Intended access scope

- Asked: [2026/10/17 17:27] America/New_York.
- Question: Who will have access to the first version?
- Choices:
  - A. Only the user, running it locally on their own computer. Recommended for the initial developer console.
  - B. A limited team sharing the console.
  - C. Public users accessing it over the internet.
- Answered: [2026/10/17 17:32] America/New_York.
- Answer: A — only the user, running it locally on their own computer.
- Decision: target a single-user, local-only developer console. Team sharing and public hosting are outside the selected access scope. Credential handling remains to be resolved.
- Rationale: intended exposure and number of users determine the necessary authentication boundary and credential ownership model. This question establishes requirements; a choice does not authorize deployment.
- Decision rationale: the user explicitly selected local use on their own computer.
- Status: confirmed.

## Q007 — Database contents and credential location

- Asked: [2026/10/17 17:32] America/New_York.
- Question: Which data must the database store?
- Choices:
  - A. Store query results, including customer, account, and transaction data, in the database; provide the Nessie API key through a backend environment variable. Recommended.
  - B. Store both query results and the Nessie API key in the database.
  - The user may specify other required data categories without supplying any secret values.
- Answered: [2026/10/17 17:34] America/New_York.
- Answer: A — store query results in the database and provide the Nessie API key through a backend environment variable.
- Decision: the database stores returned customer, account, and transaction query data. The Nessie API key is backend configuration supplied through an environment variable, not database content or a frontend setting. Retention remains unresolved.
- Rationale: the idea assigns sensitive information and temporary responses to the database but does not identify whether sensitive information includes credentials or only returned banking data. This choice determines the storage boundary; retention and protection details remain separate unresolved requirements.
- Decision rationale: the user explicitly selected separating backend credentials from stored query results.
- Status: confirmed.

## Q008 — Query-result retention

- Asked: [2026/10/17 17:34] America/New_York.
- Question: How should temporary query results be retained?
- Choices:
  - A. Keep only the latest successful result for each query and resource ID during the current backend run; discard it when the backend exits. Recommended.
  - B. Keep the latest successful result for each query and resource ID across restarts, until overwritten or manually cleared.
  - C. Keep a persistent history of each query execution for later comparison.
- Answered: [2026/10/17 17:35] America/New_York.
- Answer: C — retain a persistent history of each query execution for later comparison.
- Decision: append query-execution history and preserve it across backend restarts instead of replacing previous results for the same query and resource ID. This refines the original temporary-response requirement into persistent history. The retention period and history inspection interface remain unresolved; an automated comparison feature is not established by this choice.
- Rationale: the idea specifies temporary returned data but does not define its lifetime or whether historical versions are needed. This determines whether storage must survive a restart and whether records are replaced or appended. Cache reuse when executing a new query is a separate behavior, not established by this retention choice.
- Decision rationale: the user explicitly selected retaining each query execution for later comparison.
- Status: confirmed.

## Q009 — History retention period

- Asked: [2026/10/17 17:35] America/New_York.
- Question: How long should query history be retained?
- Choices:
  - A. Retain it until the user manually clears it, with no automatic deletion. Recommended.
  - B. Automatically delete history after a fixed number of days; specify the number of days.
- Answered: [2026/10/17 17:36] America/New_York.
- Answer: A — retain history until the user manually clears it, with no automatic deletion.
- Decision: history persists without a time-based deletion policy. Provide a user-initiated history-clearing action; its exact scope and interaction remain to be specified. Do not automatically expire or prune query history.
- Rationale: persistent history does not specify a deletion policy. Resolve this before defining destructive cleanup behavior and storage growth expectations.
- Decision rationale: the user explicitly chose continued retention with manual clearing. Local storage can grow until records are cleared.
- Status: confirmed.

## Q010 — Query-result presentation

- Asked: [2026/10/17 17:36] America/New_York.
- Question: How should query results be displayed?
- Choices:
  - A. Formatted JSON with HTTP status and request duration. Recommended for the developer console.
  - B. A data table with an option to switch to formatted JSON; also show HTTP status and request duration.
- Answered: [2026/10/17 17:37] America/New_York.
- Answer: B — a data table with a formatted JSON view, HTTP status, and request duration.
- Decision: present query results as a table with a switch to formatted JSON. Show HTTP status and request duration alongside the result. Exact layout and field presentation remain part of the subsequent frontend design.
- Rationale: the idea requires displaying returned data but does not define the presentation. JSON directly exposes the response structure for API testing; a table adds a separate field presentation requirement. This is a content and interaction choice, not a finalized visual layout.
- Decision rationale: the user explicitly selected the table and JSON presentation option.
- Status: confirmed.

## Q011 — History inspection and comparison

- Asked: [2026/10/17 17:37] America/New_York.
- Question: What history inspection and comparison capability should the first version provide?
- Choices:
  - A. A history list; open one record in the table or JSON view and compare records manually. Recommended.
  - B. Select two history records for the same query and resource ID, display them side by side, and highlight differences.
- Answered: [2026/10/17 17:40] America/New_York.
- Answer: B — select two records for the same query and resource ID, display them side by side, and highlight differences.
- Decision: include a history list, individual record inspection, and a comparison action for two historical results with the same query function and resource ID. The comparison displays both results side by side and highlights differences. For top-level list queries, the resource ID is absent on both records. This resolves the comparison scope left open in Q008.
- Rationale: Q008 requests history for later comparison but does not determine whether viewing records individually is sufficient or an explicit difference-comparison interaction is required. This choice establishes the minimum history interface before designing its views.
- Decision rationale: the user explicitly selected built-in comparison and difference highlighting.
- Status: confirmed.

## Q012 — Manual history deletion scope

- Asked: [2026/10/17 17:40] America/New_York.
- Question: Which manual history deletion operations should be provided?
- Choices:
  - A. Only clear all history, after confirmation. Recommended for the smallest implementation.
  - B. Delete an individual record or clear all history, with confirmation before either operation.
- Answered: [2026/10/17 17:41] America/New_York.
- Answer: B — support deleting one record and clearing all history, with confirmation before either operation.
- Decision: provide individual history-record deletion and complete local-history clearing. Each operation requires an in-app confirmation before changing stored records. Deletion applies to locally saved query history. This resolves the manual-clearing scope left open in Q009.
- Rationale: Q009 requires manual clearing but leaves the deletion scope unresolved. The selected operations determine the controls, confirmation states, and affected historical records.
- Decision rationale: the user explicitly selected both deletion operations with confirmation.
- Status: confirmed.

## Q013 — Data source when executing a query

- Asked: [2026/10/17 17:41] America/New_York.
- Question: What should happen when the Query button is pressed?
- Choices:
  - A. Call Nessie on every execution and save a new query-history record. Recommended for testing the API.
  - B. Prefer the most recently saved result for the same query and resource ID, calling Nessie when none exists; provide a separate Refresh action to make a new API request.
- Answered: [2026/10/17 17:42] America/New_York.
- Answer: A — call Nessie on every execution and save a new query-history record.
- Decision: each Query action makes a new Nessie API request and appends its execution to local history. Saved results are used for history inspection and comparison, rather than as the response to a new query. The content retained for failed executions is addressed in Q014.
- Rationale: Q008 establishes persistent history but does not establish cache reuse. The query action's data source must be explicit so the frontend can distinguish a new API response from a saved result and define the required controls.
- Decision rationale: the user explicitly selected a live API request on each query execution.
- Status: confirmed.

## Q014 — Error content retained in failed-query history

- Asked: [2026/10/17 17:42] America/New_York.
- Question: How much error content should failed-query history retain?
- Choices:
  - A. Retain the API error-response content after removing credentials, to support debugging. Recommended.
  - B. Retain only a short error summary.
- Common metadata: both choices retain the query timestamp, function and resource ID, HTTP status when a response exists, and request duration. Credentials must be excluded from stored records.
- Answered: [2026/10/17 17:44] America/New_York.
- Answer: A — retain the API error-response content after removing credentials.
- Decision: save sanitized API error-response content with the common execution metadata so failures can be inspected later. When there is no HTTP response, retain a safe transport-error description and leave the upstream HTTP status and response body absent. Exclude credentials from stored and displayed error content.
- Rationale: retaining every execution includes failures, but the required detail of stored error content remains unresolved. This affects historical debugging and comparison as well as the stored response fields. A failure without an HTTP response cannot have an upstream HTTP status or response body.
- Decision rationale: the user explicitly selected detailed error-response retention for debugging.
- Status: confirmed.

## Q015 — Live integration prerequisites

- Asked: [2026/10/17 17:44] America/New_York.
- Question: Are the Nessie API key and test data ready for live connection verification?
- Choices:
  - A. An API key is available, and customer, account, deposit, and withdrawal test data are ready.
  - B. An API key is available, but test data are missing or their availability is uncertain.
  - C. No API key is available yet.
- Response boundary: report readiness only; no secret value is requested.
- Answered: [2026/10/17 17:46] America/New_York.
- Answer: B — an API key is available; test data should be generated synthetically by the agent. The user explicitly requested generating a series of synthetic datasets first.
- Decision: prepare local, clearly labeled synthetic datasets before continuing the requirements interview. API-key availability is user-reported and has not been verified. Generating fixtures does not authorize uploading them or replacing the live-query requirement from Q013.
- Rationale: the selected scope requires real API requests for all six query functions. Determine the prerequisite state before defining the integration probe and acceptance evidence. This question does not establish successful authentication or authorize creating or changing upstream data.
- Decision rationale: the user selected agent-generated test data and explicitly requested dataset preparation as the next deliverable.
- Status: confirmed; requested local datasets generated and checked under D003.

## D003 — Local synthetic-data preparation

- Authorized: [2026/10/17 17:46] America/New_York.
- Recorded: [2026/10/17 17:50] America/New_York.
- Status: local data artifacts generated; verification recorded below.
- Decision: create five deterministic snapshot datasets, simulated query history and comparison cases, and a manifest under [datasets/nessie](../../datasets/nessie/README.md). Retain a standard-library-only [generator and self-check](../../scripts/generate_synthetic_data.py). This is a supporting data task while product requirements remain in clarification; it does not start application implementation or finalize its architecture.
- Scope: baseline, changed, empty, boundary, and volume snapshots. They contain 124, 130, 0, 10, and 750 entity records respectively, plus 32 synthetic history records and seven comparison cases. Counts include separate versions of entities across snapshots, not globally distinct customers or accounts.
- Rationale: cover all six query functions, valid relationships, empty results, nested and scalar changes, additions and removals, ordering-only differences, unchanged results, error history, and representative table input sizes using a small reproducible fixture set.
- Contract evidence: reuse the official OpenAPI 1.0.0 and resource examples already retrieved under Q003. Customer, account, and deposit fields follow the published schema. Withdrawal list schemas are generic in that specification; the fixture uses the published resource-example fields. Snapshot envelopes and history metadata are local fixture formats, not finalized application storage contracts.
- Data conventions: IDs and account numbers are invented, with 24 hexadecimal characters and 16 decimal digits respectively. Integer amounts are used. A local opening-balance map and completed-only transaction rule make synthetic balances consistent; this convention is not an assertion about every server-side financial behavior.
- Authority boundary: local files only; no credentials read, network requests, upstream imports, application changes, deployments, or dependency installations performed. Synthetic IDs require mapping to server-assigned IDs before any separately authorized Nessie import. Live behavior and the import workflow remain unverified.
- Verification: `python3 scripts/generate_synthetic_data.py --check` passed for all seven JSON files, six query examples, and seven comparison cases. Independent negative mutations were rejected for an orphan account, duplicate transaction ID, incorrect balance, and non-integer amount. Python syntax parsing also passed.
- Language and source preservation: dataset usage instructions are provided in English and Traditional Chinese. The user-authored `idea.md` remains read-only.

## D004 — Continue the requirements interview to design readiness

- Recorded: [2026/10/17 17:54] America/New_York.
- Status: confirmed by the user's explicit instruction.
- Request: determine whether the questions are complete; if not, continue asking until the other Markdown documents can be created.
- Decision: resume focused, one-at-a-time clarification. Resolve material gaps in data-source integration, comparison behavior, failure paths, and testable acceptance before drafting the remaining application design documents. Reuse prior answers and evidence instead of restarting the interview.
- Rationale: producing synthetic data completed a supporting task, not the application-design question gate. In particular, Q013 requires live Nessie calls, while D003 created only local fixtures; the intended connection between them still needs a decision.

## Q016 — Connecting synthetic data to the query workflow

- Asked: [2026/10/17 17:54] America/New_York.
- Question: How should the synthetic datasets be used in the first version's query workflow?
- Choices:
  - A. Use the baseline dataset as the source for seeding Nessie, then query Nessie through Python; keep changed, empty, boundary, volume, and error fixtures for local testing. Recommended because this preserves Q013's live-query requirement.
  - B. Query a local Nessie-simulating service first and integrate the real Nessie API later. This would revise Q013's requirement to make live Nessie calls in the first version.
- Answered: [2026/10/17 17:55] America/New_York.
- Answer: A — seed Nessie from the baseline dataset and make live queries through Python; use the other fixtures for local testing.
- Decision: baseline seeding is part of the intended initial setup, while the application retains its six read-only live-query functions. Preserve the original local fixture IDs and map them to server-assigned IDs for remote relationships and query examples. Changed, empty, boundary, volume, and error fixtures remain local test inputs. This preserves Q013 and resolves the data-source gap identified in D004.
- Rationale: local JSON files do not become remotely queryable Nessie records merely by being generated. The choice determines the external integration, any data-import preparation, and the acceptance environment. This question selects the intended data workflow; it does not itself execute an import.
- Decision rationale: the user explicitly selected live Nessie integration with baseline seeding.
- Execution state: no import has been performed; the requirements interview continues.
- Status: confirmed.

## Q017 — Collection ordering in historical comparisons

- Asked: [2026/10/17 17:56] America/New_York.
- Question: If two query results contain the same records in a different order, should the comparison flag that ordering change?
- Choices:
  - A. Ignore ordering changes. Match records by `_id` and highlight additions, removals, and field changes. Recommended.
  - B. Also flag ordering changes, while still matching records by `_id` for data comparison.
- Answered: [2026/10/17 17:59] America/New_York.
- Answer: A — ignore ordering changes; the user also noted that timestamps will differ.
- Decision: align top-level resource collections by `_id` and highlight additions, removals, and response-field changes, excluding ordering-only changes. Show each execution's query timestamp and duration separately in the comparison header, but do not count those local execution metadata differences as data changes. Business date/time fields within the response body, such as `transaction_date`, remain comparable; do not blanket-ignore response fields because their names contain time or date. Compare HTTP outcome/status as response information rather than ignoring all execution metadata indiscriminately.
- Rationale: Q011 establishes difference highlighting but does not specify whether collection order is meaningful. The fixtures include an ordering-only example, CMP004; its factual expectation does not select the product behavior.
- Decision rationale: the user selected record-based comparison and identified naturally different query times. The existing history format separates local `requested_at` and `duration_ms` from `response_body`, so different execution times do not imply changed response data.
- Verification: [2026/10/17 18:00] America/New_York — CMP005 already contains identical response bodies with different query timestamps and durations: H003 and H025. Direct checks confirmed all three facts.
- Status: confirmed; timestamp observation incorporated into comparison semantics.

## Q018 — Successful API response when history persistence fails

- Asked: [2026/10/17 18:00] America/New_York.
- Question: If Nessie returns data successfully but saving query history fails, what should the frontend display?
- Choices:
  - A. Display the returned data and clearly mark it as not saved to history. Recommended.
  - B. Treat the operation as failed, display the storage error, and do not display the returned query data.
- Answered: [2026/10/17 18:02] America/New_York.
- Answer: A — display the data and use the exact label `failed to write` for history persistence failure.
- Decision: preserve and display the successful Nessie response even if local history insertion fails. Show `failed to write` as a distinct persistence state, without misrepresenting the upstream request as failed or claiming the result was saved. An unsaved result has no persistent history record available for later selection or comparison.
- Rationale: the intended flow includes persistent query history, but external API success and local database success can differ. This determines the failure branch, response contract, user-visible state, and whether the current result can still be inspected. An unsaved response cannot be selected from persistent history for later comparison.
- Decision rationale: the user explicitly selected displaying the result and supplied the required English persistence-failure label.
- Status: confirmed.

## Q019 — Re-running baseline data import

- Asked: [2026/10/17 18:03] America/New_York.
- Question: What should happen when the baseline importer is run again?
- Choices:
  - A. Reuse the saved import progress and ID mappings, skip confirmed completed records, and create only missing records. Recommended.
  - B. Create a new batch every time and retain previously imported data.
- Safety boundary: neither choice deletes pre-existing Nessie data. Under A, ambiguous creation outcomes or missing progress require reconciliation before issuing another create request; do not blindly retry uncertain writes.
- Answered: [2026/10/17 18:09] America/New_York.
- Answer: A — reuse saved progress and ID mappings, skip confirmed completed records, and create only missing records.
- Decision: persist baseline import progress and ID mappings; resume confirmed work without creating another batch. Reconcile uncertain outcomes before further writes, and stop if a unique remote match cannot be established. Preserve unrelated remote data and import mappings when clearing query history.
- Rationale: Q016 selects remote baseline seeding, but repeat execution could otherwise create unintended duplicates. Resolve this final known material setup choice before documenting the importer, persistent mappings, failure paths, and acceptance criteria. Routine implementation details can be selected from the confirmed local, single-user scope.
- Decision rationale: the user explicitly selected resumable import rather than repeated batches.
- Status: confirmed; all known material requirements are resolved sufficiently to write the application designs.

## D005 — Initial v0.0.0 design baseline

- Recorded: [2026/10/17 18:09] America/New_York.
- Status: initial requirements gate passed; standalone file placement and setup assumptions are superseded by D008 after Q020. The six-query behavior and AC01–AC12 remain effective.
- Purpose: this system helps one local developer test six Nessie read queries, inspect responses, and compare persistent query history.
- Architecture decision: a React frontend built with Vite, a Python FastAPI HTTP boundary, standard-library `urllib.request` for outbound calls, and standard-library `sqlite3` for one local SQLite database. A separate Python setup command imports baseline data. FastAPI reduces handwritten request validation; SQLite avoids an additional database service. No MCP, natural-language parsing, bank-write controls, public hosting, or automatic history expiration is part of this version.
- Actual flow: React sends a local HTTP request to Python; Python calls the Nessie REST API, sanitizes its response, attempts history persistence, and returns the captured result with its independent persistence status. Swagger UI is a documentation/testing interface, not an intermediate server hop. History inspection reads SQLite without calling Nessie.
- Boundaries: bind locally, keep `NESSIE_API_KEY` in the backend environment, and protect `var/nessie.sqlite3` as local private data. Store response snapshots rather than adding duplicate customer/account ledger tables. Baseline ID mappings and import progress survive history deletion.
- Comparison decision: compute differences in Python over saved snapshots. Align top-level success collections by unique `_id`; preserve original bodies and ordering for JSON inspection. Compare response values and outcome, display execution timestamps/durations separately, and preserve the difference between a missing field and JSON null.
- Working UI reference: option 1 for each view is the primary agent's selected baseline; option 2 supplies a distinct layout with the same functions. Layout styling is an implementation choice, not an additional unresolved product requirement.
- Evidence: Nessie contracts from Q003 are reused. Context7 `/websites/fastapi_tiangolo` was resolved once and queried for JSON request validation; relevant official pages are [request bodies](https://fastapi.tiangolo.com/tutorial/body/) and [error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/). Framework versions are not installed or locked in this documentation task; initial setup must verify current compatible stable versions before creating lockfiles.
- Delivery scope: bilingual design documents, local HTML references, repository guidance, and the initial plan. Future product work stays unchecked in the plan; no credentials, remote writes, installations, release, or deployment are performed by this design task.

### Acceptance criteria

| ID | Required result |
| --- | --- |
| AC01 | Each of the six allowlisted queries makes a fresh Nessie request; required IDs are validated before any request. |
| AC02 | The key is backend-only and absent from browser data, persistent snapshots, errors, and logs. |
| AC03 | Successful data supports table and JSON views with upstream status, UTC query time, and duration. Empty success is distinct from error. |
| AC04 | Every attempted upstream query can produce a persistent success/error history record; saved history survives restart and retains source identity. |
| AC05 | Opening history or comparing records does not reissue API queries; viewing old data is labeled with its original time. |
| AC06 | Compatible snapshots compare side by side with additions/removals/field changes; ordering, query time, and duration alone produce no data difference. Business dates and response outcome remain meaningful. |
| AC07 | Deleting one/all history requires explicit confirmation and changes only history, preserving seed progress and Nessie data. |
| AC08 | History insertion failure preserves the captured response and shows exactly `failed to write`; the result has no saved history ID. |
| AC09 | Baseline setup maps local IDs to remote IDs, verifies parent relationships, resumes confirmed progress, and stops on ambiguous writes without blind retries. A completed rerun creates zero new records. |
| AC10 | The app is single-user and loopback-only, validates Host/Origin and JSON writes, and offers no runtime upstream write endpoints. |
| AC11 | Five deterministic fixture sets, 32 synthetic history records, and seven comparison cases remain available and labeled; synthetic evidence is distinct from live evidence. |
| AC12 | Live verification covers all six queries and server-assigned mappings. A transport failure has no invented upstream HTTP status/body. Documentation and planned checks are not reported as executed product tests. |

### Effective document map

| Component | Design | Working HTML references |
| --- | --- | --- |
| Frontend | [Frontend.md](Frontend.md) | [Query](html/view-query/option-1.html), [History](html/view-history/option-1.html), [Comparison](html/view-compare/option-1.html) |
| API, functions, setup | [Backend.md](Backend.md) | None: service and CLI contracts |
| Data movement | [DataFlow.md](DataFlow.md) | None: chains and verification criteria |
| User states | [UserFlow.md](UserFlow.md) | View/control IDs from Frontend |
| Local storage | [Database.md](Database.md) | None: local persistent model |
| Initial execution | [Plan.md](Plan.md) | Documentation checks and future spikes |

The corresponding Traditional Chinese files use `.zh-TW.md`. The [Nessie design index](README.md) indexes both languages. There is no additional product frontend for Swagger, seeding, or MCP, and no redundant design document set.

## D006 — Preserve the concurrently introduced TrustLedger workspace

- Recorded: [2026/10/17 18:21] America/New_York.
- Evidence: Git HEAD `636ab15` contains a TrustLedger starter, existing `AGENTS.md`, team ownership, CI, and `contracts/internal-api.openapi.yaml`. These appeared during the earlier question/data task; their runtime and product scope differ from this Nessie query-console proposal.
- Decision: preserve that application and its project constraints. The shared AGENTS/index files were restored verbatim from their tracked version, retaining only additive links to this proposal; the new bilingual Nessie index moved to this version directory. Do not weaken team CI or replace the existing contract.
- Status: workspace preservation completed; intended integration scope awaits Q020. The proposed documents are drafts until that boundary is selected. Reference verification can proceed independently.

## Q020 — Scope relative to the existing TrustLedger application

- Asked: [2026/10/17 18:21] America/New_York, through an asynchronous question.
- Question: The workspace gained a TrustLedger application and team contract during this interview. Should this Nessie console remain a separate design or be integrated into TrustLedger?
- Choices:
  - A. Keep a separate Nessie developer-console design and preserve the TrustLedger application/contract. Recommended.
  - B. Integrate with TrustLedger and align the design with its contract and team ownership.
- Answer recorded: [2026/10/17 18:29] America/New_York.
- Answer: B — integrate with TrustLedger; add Admin under the frontend left WORKSPACE section.
- Decision: the existing TrustLedger shell gains NAV-ADMIN; its content contains the query/history/comparison views. Align file placement, storage, and proposed additive API paths with existing team-owned modules.
- Rationale: the user selected integration and supplied the exact navigation placement. Preserve the existing synthetic demonstration and consent-based memory flows.
- Status: confirmed; the question gate is complete for the design deliverable. Runtime implementation remains in S1–S5.

## D007 — Design artifact verification receipt

- Recorded: [2026/10/17 18:25] America/New_York.
- Status: independent artifact checks passed; Q020 is still pending, so integration planning and implementation remain incomplete.
- Delivered: bilingual Frontend, Backend, Database, DataFlow, UserFlow, Plan, and version README files; six local HTML references with shared local assets; additive links preserving original tracked AGENTS/index content; timestamped CHANGELOG and real MISTAKE entries.
- Checks: fixture self-check passed; local Markdown links resolve; bilingual question, function, flow, view, and spike IDs match; Plan checkbox states match; original tracked AGENTS/index contents remain intact; six HTML files have unique static IDs and valid local asset links; JavaScript syntax and Git whitespace checks passed.
- Browser evidence: existing Playwright 1.64.1 with local Chrome, no new installations. Both variants passed eight grouped checks with no page errors: six query examples, table/JSON switches, `failed to write` with data retained, timeout/empty states, history viewing, cancel/single/all deletion, compatible comparison, ordering/timestamp exclusion, HTTP outcome change, and mobile overflow. Final receipt/screenshots: `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-5LJ8z9/`.
- Existing application check: `bash scripts/check.sh` passed backend lint and 15 tests, frontend typecheck and three tests, and build. This evidence concerns the existing TrustLedger starter, not the proposed Nessie implementation. A dependency deprecation warning was observed; no unrelated dependency fix was attempted.
- Preservation: existing app sources, API contract, CI workflows, and unrelated working-tree changes were not edited. No Nessie key read, remote request/import, release, or deployment occurred in this design task.

## D008 — Effective TrustLedger Admin integration

- Recorded: [2026/10/17 18:29] America/New_York; follows the user's Q020 B answer and explicit WORKSPACE/Admin placement.
- Status: confirmed integration design; supersedes D005's standalone module/storage/setup assumptions. Q001–Q020 are resolved for this design deliverable. Historical D006/D007 pending states describe their recording time.
- Frontend: add NAV-ADMIN labeled `Admin` under the existing left WORKSPACE section, after Confirmed memory. Reuse React/TypeScript tab state in `frontend/src/main.tsx`; add `Admin.tsx` with query/history/comparison inner tabs and extend existing `api.ts`/`styles.css`. Retain Admin state across navigation; entering it never automatically queries Nessie. Both HTML variants keep the desktop left sidebar.
- API: extend the existing FastAPI `create_app` with `app/api/admin_nessie.py`, strict `app/schemas/admin_nessie.py`, and orchestration/comparison in `app/services/nessie_console.py`. Proposed additive endpoints use `/api/v1/admin/nessie`; preserve every current endpoint, safe error/request-ID behavior, and security middleware. The Integrator must agree on contract additions before runtime implementation; this task leaves `contracts/internal-api.openapi.yaml` unchanged.
- Data: extend the Data-owned `app/adapters/nessie.py` for the six read queries; keep the synthetic transaction adapter and its dashboard wiring. The separate `app/adapters/seed_nessie.py` is a future baseline-only setup command. Provider snapshots/IDs never enter AI or confirmed-memory services.
- Storage: extend the existing Store and `Settings.database_path`, default `backend/data/trustledger-demo.db`, with query history and independent seed-run/record tables. Scope operations to server-selected `demo_user_id`. Additive initialization preserves existing confirmations, memories, and normal-confirmation-plus-consent policy. History deletion affects only that owner's query history; no seed, consent/memory, fixture, or remote data is removed.
- Configuration/dependencies: reuse existing Settings secret, Vite proxy, package locks, pytest/ruff, Vitest/TypeScript, and installed Playwright. No bootstrap or framework upgrade. The current frontend client aborts after 8 seconds, shorter than the planned 15-second upstream wait; only Admin queries will allow 25 seconds, including SQLite commit/response margin. Keep other calls unchanged.
- Safety/exposure: single local demo identity; Admin is a navigation surface, not production authorization. Default synthetic source and all existing consent/privacy boundaries remain. The future Nessie API key targets only synthetic sandbox data; no live bank data or automatic financial actions.
- Acceptance additions: WORKSPACE → Admin opens the inner console; existing overview/memory flows still work; navigation preserves state and triggers no fresh Nessie query; new API/history behavior passes AC01–AC12 without changing existing contract behavior. Required `bash scripts/check.sh` remains mandatory.
- Deliverable boundary: finish the bilingual design bundle, synthetic fixtures, and usable HTML references. S1–S5 remain unchecked for implementation, live import, and live verification. No credentials, remote writes, commit, PR, release, or deployment are part of this design task.

## D009 — Integrated design verification and closeout

- Recorded: [2026/10/17 18:35] America/New_York.
- Status: S0 complete; Q001–Q020 resolved. S1–S5 remain unchecked. The completed deliverable is design/documents/fixtures/references, not the Admin runtime.
- Static verification: eight bilingual version-document pairs have matching stable IDs and Plan checkbox states; all 20 questions are recorded; local links across 23 authored Markdown files resolve; all six references have unique IDs and valid local links/assets. Both tracked shared-file originals remain intact as prefixes. Existing backend/frontend sources, OpenAPI contract, and CI workflows were not edited by this task.
- Browser verification: 12 grouped checks passed in local Chrome using the installed Playwright, with no page errors. Both layouts keep WORKSPACE/Admin in the left sidebar with three inner tabs. Verified six query examples, table/JSON, `failed to write` with response retained, timeout/empty states, history inspection, deletion cancel/focus return/single/all, comparison, timestamp/order exclusion, response-outcome changes, and all three views at 320px/390px without document overflow. Screenshots were visually inspected. Receipt/screenshots: `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-i110PE/`.
- Other checks: `python3 scripts/generate_synthetic_data.py --check`, JavaScript syntax checks, and `git diff --check` passed. Required `bash scripts/check.sh` passed ruff, 15 backend tests, frontend typecheck, three Vitest tests, and build; its existing Starlette/httpx deprecation warning remains. Existing application checks do not prove the future Admin implementation.
- Scope: no key access, authenticated Nessie request, remote seed/import, new installation, commit, PR, release, or deployment. `idea.md` and unrelated script changes are preserved. Reviewed MISTAKE; its actual corrections remain documented.

## Q021 — Additive Admin API agreement

- Asked: [2026/10/17 18:39] America/New_York.
- Question: Approve the query/history/compare/confirmed-delete contracts under `/api/v1/admin/nessie` in Backend.md while preserving existing endpoints and synthetic/consent behavior?
- Status: approved by the user, conditional on checking the latest PR; D011 records the compatibility check.
- Rationale: the project requires contract agreement before implementation. The user requested latest-PR synchronization, v0.0.0 implementation, and a PR.

## D010 — Implementation baseline

- Recorded: [2026/10/17 18:39] America/New_York.
- Latest merged PR: #3, included in `origin/main` at `5be26c1`. Working branch: `feat/nessie-admin-v0`. Existing uncommitted design/fixture/script changes are retained.
- Risk: substantial cross-module API, persistence, and sandbox setup; use existing S1–S5 plan and a 90-minute checkpoint. No deployment is requested.
- Baseline: `bash scripts/check.sh` passed ruff, 17 backend tests, three frontend tests, typecheck and build; fixture check passed.
- Credential gate: `NESSIE_API_KEY` is not configured. Live probe/import and AC12 remain unverified; isolated tests cannot substitute for them. Context7 has no Capital One Nessie entry; the official OpenAPI was retrieved directly.

- Answered: [2026/10/17 18:40] America/New_York. User approves the existing v0.0.0 contracts, conditional on checking the newest PR for conflict.

## D011 — Contract approval and isolated delivery

- Recorded: [2026/10/17 18:44] America/New_York.
- Q021 outcome: approved. The latest PR remains #3; its full diff changes only consented AI memory feedback, routes, dashboard refresh and tests. It does not change OpenAPI, Store or the API client; no conflict with the additive Admin contract was found. Preserve its behavior and tests.
- User decision: complete code and isolated tests first; clearly mark live Nessie verification pending in the PR. This explicitly defers live S1/S5 gates without representing synthetic evidence as live verification. Runtime spikes proceed after their local checks pass.
- Verification: transport/import tests passed; query/history tests passed; CMP001–CMP007 and presence/type/date checks passed. Live credentials, writes and queries have not been used.

## Q022 — Live verification authority

- Asked: [2026/10/17 18:51] America/New_York. Whether the backend key can be configured or live verification deferred.
- Initial answer: complete code/isolated tests and mark live verification pending in the PR.
- Superseding answer: the user explicitly requested real Nessie queries/import in this execution. Live sandbox read/write setup is now authorized; deployment is not.
- Credential handling: a newly nonempty tracked sample was moved to ignored `backend/.env` with mode 0600 and its safe template restored. No secret was printed or staged.

## Q023 — Observed remote ID incompatibility

- Asked: [2026/10/17 18:51] America/New_York. Approve 24-hex or canonical UUID IDs and reconcile the already-created customer before continuing?
- Evidence: actual `customers.list` returned HTTP 200; the first create produced one marker-matched synthetic customer with a 36-character UUID, contrary to the published 24-character schema and original P01 design.
- Status: pending user agreement. Import stopped with one pending customer, zero accounts/transactions; no POST retry occurred. No remote IDs or response bodies are recorded here.

- Q023 final answer: [2026/10/17 18:54] America/New_York — user approves both 24-hex and canonical UUID remote IDs. An intervening UUID-only instruction was superseded by the latest explicit two-format answer. Trim/lowercase both forms; allow no arbitrary path input. Additive history migration preserves IDs, rows and AUTOINCREMENT progress.

## Q024 — Observed sandbox balance semantics

- Asked: [2026/10/17 18:54] America/New_York. Accept opening-balance accounts and independent transaction creation, document the difference from offline computed balances, and avoid changing existing remote balances?
- Evidence: all eight probe entities now reconcile, using server-assigned UUIDs. `accounts.get` returns 200; its integer balance equals the opening balance, not the fixture completed-transaction total.
- Status: pending. No bulk import has occurred. The original customer was reconciled and was not recreated.

- Q024 answered: [2026/10/17 18:55] America/New_York — user approves following actual Nessie behavior. Preserve opening balances, import transactions independently, do not update existing remote balances, and document the difference from offline computed balances. The live probe passed with eight confirmed entities after this change; no entity was recreated.

## D012 — Live implementation verification

- Recorded: [2026/10/17 18:57] America/New_York.
- Live import: 124 confirmed entities (10 customers, 18 accounts, 48 deposits, 48 withdrawals). Original pending customer reconciled without recreation. Completed rerun made 142 GETs and zero POSTs.
- Six live query types returned HTTP 200 through the Admin API and committed history. Restarted app read identical saved content. Saved comparison made no upstream request and reported unchanged data.
- Safety review: independent reviewer found marker-collision and incomplete probe-preflight issues; regressions failed before fixes and passed afterward. Same reviewer verified both fixes before live continuation.
- Delivery remains a PR, with no deployment or release tag. Complete verification and review receipts: [Verification](Verification.md).
