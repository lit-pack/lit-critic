## Reliability Policy (Retry, Backoff, Idempotency)

This document defines the operational policy for retries and failure handling in the stateless Core + Platform architecture.

---

## Scope

- **In scope:** Platform->Core HTTP transport behavior (`orchestrator/core_client.py`) and Platform persistence contention handling in SQLite-backed session/finding/learning flows.
- **Out of scope:** provider-side LLM determinism guarantees.

---

## Transport Retry Policy (Platform -> Core)

`CoreClient` applies bounded retry with linear backoff:

- `retry_attempts` (default: `2`, minimum: `1`)
- `retry_backoff_seconds` (default: `0.25`, minimum: `0.0`)
- retry delay = `retry_backoff_seconds * attempt`

### Retried Conditions

- HTTP `5xx` responses
- network/transport exceptions (`URLError`, `TimeoutError`, `socket.timeout`)

### Non-Retried Conditions

- HTTP `4xx` responses (immediately mapped to `CoreClientHTTPError`)
- invalid JSON payloads (mapped to `CoreClientError`)

### Error Surface

- `CoreClientHTTPError(status_code, detail)` for HTTP failures
- `CoreClientError` for transport/decode failures after retry exhaustion

---

## Persistence Contention Policy (SQLite)

Finding persistence applies bounded retries for transient SQLite lock failures:

- attempts: `3`
- base backoff: `0.02` seconds
- delay = `0.02 * attempt`

Only `sqlite3.OperationalError` containing `locked` is retried; other DB errors fail fast.

---

## Idempotency Policy

### Core Contract Calls

Core is stateless at API boundary. Platform transport retries may replay a request when failures occur before a successful response is observed.

Operationally this is treated as **at-least-once transport semantics**.

### Workflow Actions

Session actions (accept/reject/advance/discuss) mutate workflow state and are **not universally idempotent** at UX level.

Therefore:

1. Automatic retries are limited to transport/persistence layers where bounded and explicit.
2. Clients should avoid blind re-submission of user actions after unknown completion unless they first reconcile session state.
3. API consumers should prefer reading current session/finding state before replaying a mutating action.

---

## Operational Recommendations

- Keep retry bounds low to avoid duplicate work amplification.
- Log retry exhaustion and lock-contention events with request/session context.
- Alert on elevated retry-exhaustion rates (often indicates upstream outage or DB pressure).
