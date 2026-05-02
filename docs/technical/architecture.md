# Architecture Guide

This document describes the **current canonical architecture** of lit-critic.

lit-critic is organized as three explicit layers:

1. **Core (`core/`)** — stateless reasoning engine
2. **Platform (`orchestrator/`)** — workflow + persistence owner
3. **API server (`api/`)** and **VS Code extension (`vscode-extension/`)** — thin client layers

---

## 1) Responsibility Boundaries

| Layer | Owns | Must Not Own |
|---|---|---|
| Core | Analyze/discuss/re-evaluate reasoning over versioned contract payloads | Filesystem paths, session lifecycle, SQLite orchestration |
| Platform | Scene/index loading, session state machine, persistence, retry/backoff, Core transport | Client-specific presentation/UI concerns |
| Clients | Interaction, navigation, rendering, command surfaces | Workflow orchestration or direct Core coupling |

---

## 2) Runtime Topology

```text
VS Code Extension
        |
        |  /api/*
        v
REST API Surface (api/routes.py)
        |
        |  Platform services + facade
        v
Orchestrator (orchestrator/*)
     /      |       \
    /       |        \
   v        v         v
Project files   SQLite (.lit-critic.db)   Core (core/api.py)
(scenes/indexes)  (native + derived data)      ^
       |                  ^                     |
       |  parse/hash      |  store/query        | /v1/* contracts
       +------------------>+---------------------+
            projection services
        |
        +-- session/discussion services consume authored + projected data
```

### Deployment modes

- **Default:** all components local (localhost)
- **Remote Core:** Platform stays close to project data; Core can be remote behind TLS + auth gateway

---

## 3) Core (`core/`)

Core is stateless and contract-first.

### Public endpoints

- `GET /health`
- `POST /v1/analyze`
- `POST /v1/discuss`
- `POST /v1/re-evaluate-finding`

### Core characteristics

- Accepts text + structured payloads only
- No direct file or database access
- Returns deterministic, validated contract responses

---

## 4) Platform (`orchestrator/`)

Platform is the workflow boundary and source of orchestration truth.

### Key modules

- `facade.py` — scene/index loading and contract request assembly
- `core_client.py` — transport, timeout, retry/backoff, error mapping
- `context.py` — condensed discussion context generation
- `session_state_machine.py` — state transitions and review behavior helpers
- `persistence/*` — SQLite lifecycle and data access
- `services/*` — session/discussion/learning orchestration services
- `services/scene_projection_service.py` + `services/index_projection_service.py` — build DB projections from authored files
- `services/scene_status_service.py` + `services/index_status_service.py` — single source of truth for scene and index staleness (computed on every call, not persisted; see `specs/loop-redesign-architecture.md` §3)
- `services/project_knowledge_service.py` — orchestrates knowledge refresh workflows; delegates staleness queries to the status services above

### Platform guarantees

- Session lifecycle consistency across all clients
- Immediate persistence of user actions
- Moved-scene recovery and scene-change re-evaluation
- Uniform error handling and retry policy

---

## 5) Client Layers

All clients are presentation and interaction layers over Platform behavior.

### REST API Server (`api/`)

- FastAPI HTTP endpoints consumed by the VS Code extension
- Streaming progress + discussion

### VS Code Extension (`vscode-extension/`)

- Diagnostics, findings tree, discussion panel
- Local API process management for developer workflow

#### Internal module structure

The extension is decomposed into focused modules to keep `extension.ts` as a thin composition root:

| Module | Responsibility |
|---|---|
| `extension.ts` | Activation wiring only — instantiates services, registers commands, delegates startup |
| `bootstrap/startupService.ts` | Repo-root discovery, repo-path recovery, server startup with busy UI, auto-load sidebars, activity-view reveal |
| `commands/registerCommands.ts` | Centralised command-ID → handler mapping; keeps command palette surface enumerable and testable |
| `workflows/sessionWorkflowController.ts` | All session/finding command handlers (analyze, resume, accept, reject, review, rerun, etc.) |
| `workflows/stateStore.ts` | Mutable runtime session state (findings cache, current index, totals, notices) — injected as a unit to enable deterministic tests |
| `ui/workbenchPresenter.ts` | Status bar transitions, findings/sessions tree reveal, discussion panel coordination, diagnostics updates |
| `domain/findingLogic.ts` | Pure finding-navigation helpers (fallback resolution, index clamping, context-change detection) |
| `domain/sessionDecisionLogic.ts` | Pure session-entry decision helpers (repo-path error parsing, session label formatting) |
| `domain/modelSelectionLogic.ts` | Pure model/preset selection helpers (configured model resolution, status message building) |

All VS Code surface interactions are injected through narrow port interfaces (`StartupPorts`, `WorkflowUiPort`, `WorkflowDeps`) so that unit tests can use simple fakes without loading the VS Code runtime.

#### Test organization

| Test file | What it tests |
|---|---|
| `test_startupService.ts` | Startup service branches: repo discovery, recovery loop, progress UI, activity reveal |
| `test_sessionWorkflowController.ts` | Workflow command handlers with fake ports — no VS Code or server required |
| `test_registerCommands.ts` | Command-ID coverage and handler-wiring correctness |
| `test_domain_*.ts` | Pure helper logic — zero mocking |
| `test_extension_real.ts` | Integration-style: activation wiring, command registration, auto-start behavior |

---

## 6) Data Ownership and Persistence

lit-critic uses a three-part ownership model so each layer has clear responsibility:

- **Authored data** (human-edited): scene files + index files in the project filesystem
- **Derived data** (machine-built, reproducible): scene/index projections in SQLite
- **Native runtime data** (workflow state): sessions/findings/learning in SQLite

### Filesystem (source of truth)

- Scene text files
- Author-authored knowledge files (`CANON.md`, `STYLE.md`)

> `CAST.md`, `GLOSSARY.md`, `THREADS.md`, and `TIMELINE.md` are no longer maintained as files. Their content is extracted automatically from prose and stored in the project database.

### SQLite (`.lit-critic.db`)

Owned by Platform for:

- native workflow state:
  - sessions
  - findings
  - learning
- derived project-knowledge projection state:
  - `scene_projection` (scene metadata + file hash + refresh timestamp)
  - `index_projection` (index hash + parsed entries blob when applicable — CANON.md and STYLE.md)
- extracted knowledge state:
  - `extracted_scene_metadata` (per-scene LLM-extracted metadata)
  - `extracted_characters`, `extracted_terms`, `extracted_threads`, `extracted_thread_events`, `extracted_timeline` (auto-extracted knowledge from prose)
  - `knowledge_overrides` (author corrections applied on top of extracted values; survive re-extraction)

### DB projection layer (derived cache)

The projection layer is a deterministic cache derived from authored project files.

- Refresh can be explicit (`scenes refresh`, `indexes refresh`, `/api/project/refresh`) or lazy (`ensure_project_knowledge_fresh`)
- Staleness is computed on demand by `scene_status_service` and `index_status_service` using file-content hashes; unchanged files are skipped
- `STYLE.md` is tracked hash-only (no structured entries)
- If projection rows are missing or stale, they are rebuildable from filesystem sources

### Autonomous loop (`core/loop.py`)

The loop is a single-pass state machine that reads computed scene and index statuses and advances work through a five-status lifecycle: `extraction_due` → `extracted` → `analysis_due` → `analyzed`, with a `failed` status for backoff. Each cycle calls `decide()` (a pure function mapping statuses + cool-down gates to actions) then executes the chosen action. All decisions are logged at INFO level for observability. See `specs/loop-redesign-architecture.md` for full design detail.

Key persisted multi-scene fields include:

- session scene set (`scene_paths`)
- per-finding source scene (`finding.scene_path`)

Persistence is auto-applied on each mutation (accept/reject/discuss/navigate).

---

## 7) Core Flows

### Analysis

1. Client starts analysis via `/api/analyze`
2. Platform loads one or more consecutive scenes + indexes
3. Platform concatenates selected scenes and tracks line/source mapping
4. Platform calls Core `/v1/analyze`
5. Results are mapped back to scene-local lines with per-finding `scene_path`
6. Results are persisted and returned to client

### Discussion

1. Client posts message via `/api/finding/discuss` (or streaming variant)
2. Platform builds condensed context + current finding state
3. In multi-scene sessions, discussion scope is constrained to the finding's source scene
4. Platform calls Core `/v1/discuss`
5. Outcome (revised/withdrawn/etc.) is persisted and broadcast to client

### Resume

1. Client requests `/api/resume`
2. Platform restores active session from SQLite
3. Scene hash/path validation runs (with recovery when needed)
4. Review continues from persisted index

---

## 8) Reliability and Security

- Transport retries/backoff are applied by Platform (`core_client.py`)
- Persistence lock contention is handled with bounded retries
- Remote Core deployments require gateway-authenticated TLS
- Clients should reconcile state before replaying mutating actions

See:

- [Reliability Policy](reliability-policy.md)
- [Remote Core Security](security-remote-core.md)

---

## 9) Design Principles

1. **Stateless Core boundary**
2. **Single orchestration owner (Platform)**
3. **Client interoperability through shared persisted state**
4. **Contract-first compatibility**
5. **Local-first data ownership**

---

## 10) See Also

- [API Reference](api-reference.md)
- [Installation Guide](installation.md)
- [Testing Guide](testing.md)
- [Versioning & Compatibility](versioning.md)
- [Reliability Policy](reliability-policy.md)
- [Remote Core Security](security-remote-core.md)
