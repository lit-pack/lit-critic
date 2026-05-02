# Versioning & Compatibility Policy

This document defines how **Semantic Versioning (SemVer)** is applied across the compartmentalized architecture:

- **Core** (`core/`)
- **Platform** (`orchestrator/`)
- **Clients** (`api/`, `vscode-extension/`)
- **Contracts** (`contracts/v1/`)

---

## 1) Why SemVer Here

After the refactor, component boundaries are explicit and independently evolvable. SemVer gives each boundary a predictable compatibility contract:

- **MAJOR** = backward-incompatible changes
- **MINOR** = backward-compatible feature additions
- **PATCH** = backward-compatible fixes

This reduces accidental breakage between Platform/Core and across client surfaces.

---

## 2) Source of Truth

Canonical component versions live in:

- `versioning/compatibility.json` → `components`
- Optional push/release declaration metadata lives in:
  - `versioning/compatibility.json` → `release_intent`

The local validator (`versioning/validate_semver.py`) enforces parity between this file and version declarations in code/manifests.

---

## 3) Current Compatibility Matrix

Compatibility is currently enforced at **major-version** granularity.

| Consumer | Compatible with |
|---|---|
| Platform | Core major `2`, Contracts v1 major `1` |
| API (REST API) | Platform major `2` |
| VS Code Extension | API major `2` |

Matrix source:

- `versioning/compatibility.json` → `compatibility`

---

## 4) Component Version Rules

### Contracts (`contracts/v1`)

- `contracts/v1/__init__.py` defines `__version__`
- Any breaking schema/adapter change requires **MAJOR** bump

### Core (`core`)

- `core/__init__.py` defines `__version__`
- `core/api.py` FastAPI app `version` must match Core version

### Platform (`orchestrator`)

- `orchestrator/__init__.py` defines `__version__`
- `pyproject.toml` `[project].version` is aligned to Platform package version

### API (`api`)

- `api/__init__.py` defines `__version__`
- `api/app.py` FastAPI app `version` must match API version

### VS Code Extension

- `vscode-extension/package.json` `version`

---

## 5) No-CI Enforcement Model (Local)

Until CI is introduced, SemVer is enforced through local automation:

1. **Release-intent guard**
   - `python versioning/check_release_intent.py`
   - Detects changed component areas in outgoing commits and fails if
     `versioning/compatibility.json` was not updated.
   - In pre-push hooks, `.githooks/pre-push` runs `python versioning/check_release_intent.py --pre-push`
     so outgoing commit detection uses Git's pre-push ref payload (`<local_sha>..<remote_sha>` logic)
     instead of relying only on branch-tracking heuristics.

2. **Validator script**
   - `python versioning/validate_semver.py`
   - Checks SemVer format, cross-file parity, and compatibility matrix majors.

3. **NPM shortcuts**
   - `npm run check:release-intent`
   - `npm run validate:semver`
   - `npm run release:check` (runs both checks)

4. **Git hook (pre-push)**
   - Hook file: `.githooks/pre-push`
   - Install once per clone: `npm run hooks:install`

5. **Release checklist**
   - See: `docs/technical/release-checklist.md`

---

## 5.5) Work-in-Progress Push Declaration (Non-Release)

When pushing partial work (for example, an incomplete multi-step spec implementation),
declare intent in `versioning/compatibility.json` under `release_intent`.

Recommended shape:

```json
"release_intent": {
  "status": "wip",
  "summary": "Short explanation of what is incomplete.",
  "spec": "path/to/spec.md",
  "implemented": ["completed parts"],
  "pending": ["remaining parts"]
}
```

Guidelines:

- Use `status: "wip"` for non-release pushes.
- Keep `implemented` and `pending` aligned with the source spec checklist.
- Do **not** bump component versions while `status` is `wip`.
- Before a real release, either remove the WIP declaration or update it to a
  release-ready state with fully completed scope.

---

## 6) Future CI Integration

When CI is added, reuse the exact local validator command:

```bash
npm run release:check
```

No policy rewrite is required; CI becomes an execution environment for the same checks.
