# F7 internal explanation boundary and proposed Gemini integration

Status: **internal mock implemented; Gemini/HTTP/frontend integration is PROPOSED ONLY**.
This is a team-owned internal interface, not a claim about Gemini's API or JSON format.
No Gemini SDK, credentials, model, URL, request mapping, or transport is implemented.
No public endpoint or Analysis/OpenAPI field has been added.

## Implemented internal interface

`ExplanationProvider.explain(ExplanationRequest) -> ExplanationResult`

Inject a provider with `ExplanationService(provider)`. Call
`service.explain(existing_analysis, safe_features)` after F5 analysis, using the existing
privacy serializer's snapshot. It returns an `ExplanationOutcome` containing a validated
result and an optional safe failure category. It neither invokes analysis again nor
returns a modified assessment. No provider is enabled by environment variables.
The mock is `MockExplanationProvider(scenario="valid")`; deterministic failure scenarios
are `timeout`, `unavailable`, and `invalid`.

### Request schema (all fields required)

| Field | Internal validation |
| --- | --- |
| `features` | Existing eight-field `FraudFeatures` object, with strict scalar types and controlled merchant categories |
| `alert_type` | `duplicate`, `amount_anomaly`, `subscription_change`, or `none` from authoritative Analysis |
| `severity` | Existing `low`, `medium`, or `high`; never recalculated |
| `needs_human` | Strict boolean from authoritative Analysis |

The eight approved feature fields are `merchant_category`, `amount_bucket`, `currency`,
`local_day_part`, `same_category_same_amount_24h_count`, `is_subscription`,
`subscription_delta_bucket`, and `prior_user_confirmation`. Their constraints reuse F4:
controlled categories; documented amount/day-part/delta/confirmation enums; USD;
integer count 0–20; strict subscription boolean. Prior confirmation remains `unknown`
under F6's unresolved matching policy.

The request is frozen and rejects unknown fields. Nested models are rebuilt and
revalidated before provider invocation. There is no user prompt, transaction/account/
customer identifier, merchant description, precise amount/date, request ID, confidence,
raw evidence text, memory content, model version, or secret. F4 `FraudAssessment` numeric
scores and provider prose/metadata are intentionally not forwarded: their mapping and
precedence are unapproved. The service uses the authoritative F5 `Analysis` projection.

### Result schema (all fields required)

| Field | Internal validation |
| --- | --- |
| `summary` | Plain text, 1–400 characters, currently restricted to reviewed mock/fallback templates |
| `reason_labels` | Immutable collection of at most one existing alert-type label; successful output must match the request |
| `recommended_actions` | Immutable collection of 1–3 reviewed verification actions |
| `source` | `mock` or `fallback`; never presented as a Gemini decision |

Actions are limited to checking receipts/activity, contacting the bank through its
official app or the number on the card when unrecognized, and protecting passwords/
verification codes. They do not execute anything. No money transfer, account blocking,
confirmed-fraud verdict, or risk-score override is possible through this model.

Python collections are tuples; JSON serialization uses arrays. A future adapter must
validate decoded results and preserve these semantics. Unknown output fields, arbitrary
prose, HTML/Markdown, sensitive strings, unapproved actions, and text that explains a
different alert are rejected rather than rendered or heuristically redacted. This is
not a general-purpose generated-prose sanitizer. Allowing genuine generated Gemini
prose requires an approved replacement output policy and tests before changing this gate.

## Failure and timeout expectations

Current code catches timeout, unavailable, invalid-input, invalid-output, and unexpected
provider failures, returning a reviewed plain-text fallback with verification actions.
It does not expose exception text or log prompts/responses. Fallback says the additional
explanation is unavailable; it does not label the transaction safe or erase the analysis.
No retries, sleeps, network calls, storage, or memory writes occur in this implementation.

**Proposal for a future REST adapter:** use a bounded transport timeout within the
remaining frontend 8-second budget; an initial explanation budget of at most 1.5 seconds
with no inline retries is proposed for owner review, not configured here. Skip explanation
when the remaining request budget is insufficient. The current synchronous protocol does
not cancel an arbitrary blocking injected provider; the future transport must enforce
its deadline. Preserve the valid analysis regardless of explanation success.

## Proposed frontend integration appendix — not implemented

Prefer displaying authoritative analysis immediately and treating explanation as an
optional, separately labelled supplement. A possible future UI view model would contain
an unchanged `Analysis` alongside an optional explanation with summary, reason labels,
verification actions, and source/fallback label. No endpoint path, transport mechanism,
new response field, or rollout behavior is approved by this proposal.

Questions requiring agreement:

1. Does the frontend want optional explanation alongside analysis or on explicit user request?
   How should loading, fallback, and mock/generated labels appear without delaying review?
2. Which fields and display shape may be added to the shared contract, if any? Who owns
   plain-text rendering, accessibility, and localization of reviewed actions?
3. Which Gemini model and verified request/response mappings may be used? Is the proposed
   field allowlist approved for that vendor, and what are its retention/training policies?
4. What output validation, privacy controls, and wording review are required before accepting
   generated prose rather than the current closed templates?
5. What transport deadline, total request budget, cost limit, and retry policy are approved?

Until these are answered, existing eight endpoints, Analysis schemas, risk semantics,
SQLite/Backboard behavior, and frontend remain unchanged.
