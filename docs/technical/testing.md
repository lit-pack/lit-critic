# Testing Guide

This document describes how to run and write tests for lit-critic under the current architecture:

- Core (`core/`)
- Platform (`orchestrator/`)
- Contracts (`contracts/`)
- Client layers (`api/`, `vscode-extension/`)

---

## 1) Test Suite Overview

### Python (pytest)

- `tests/core/`
- `tests/platform/`
- `tests/contracts/`
- `tests/api/`

### TypeScript (mocha)

- `tests/vscode-extension/`

---

## 2) Quick Start

### Run all tests

```bash
npm test
```

### Python only

```bash
pytest
# or
npm run test:python
```

### TypeScript only

```bash
npm run test:ts
# or
cd vscode-extension && npm test
```

---

## 3) Python Test Commands

### By package

```bash
pytest tests/core/
pytest tests/platform/
pytest tests/contracts/
pytest tests/api/
```

### By file / test

```bash
pytest tests/platform/test_core_client.py
pytest tests/contracts/test_v1_contracts.py::test_analyze_contract_schema
```

### Verbose

```bash
pytest -v
```

---

## 4) Coverage

Run architecture-aligned coverage:

```bash
pytest --cov=core --cov=orchestrator --cov=contracts --cov=api
```

HTML report:

```bash
pytest --cov=core --cov=orchestrator --cov=contracts --cov=api --cov-report=html
```

Open `htmlcov/index.html`.

---

## 5) Recommended Coverage Targets

- Core: >80%
- Platform: >80%
- Contracts: >90%
- API: >70%
- VS Code Extension: >60%

---

## 6) What to Test by Layer

### Core

- Contract request/response validation
- Analyze/discuss/re-evaluate behavior
- Error mapping for malformed provider output

### Platform

- Core client retry/backoff behavior
- Session state transitions
- Persistence interactions (session/finding/learning)
- Scene-change handling and re-evaluation triggers

### Contracts

- Schema compatibility and strict validation
- Adapter/wrapper parity
- Golden fixture comparisons

### Clients

- API integration behavior
- Presentation mapping (diagnostics/tree/panel)
- Session resume and recovery UX paths

---

## 7) TypeScript Tests (VS Code Extension)

```bash
cd vscode-extension
npm test
```

Focus areas:

- `apiClient.ts` request/response handling
- diagnostics mapping
- discussion panel state updates
- command wiring and session tree behavior

---

## 8) Failure-Mode Matrix (Minimum)

Ensure coverage for:

1. Platform->Core timeout and retry exhaustion
2. HTTP 5xx retry behavior
3. HTTP 4xx no-retry behavior
4. invalid Core payload handling
5. SQLite lock/contention retry behavior
6. moved scene path recovery on resume
7. stale finding re-evaluation after scene edits

---

## 9) CI Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install Python deps
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio

      - name: Run Python tests
        run: pytest --cov=core --cov=orchestrator --cov=contracts --cov=api

      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '16'

      - name: Run TS tests
        run: |
          cd vscode-extension
          npm install
          npm test
```

---

## 10) Best Practices

- Prefer behavior-level tests over implementation coupling
- Keep contract tests deterministic and fixture-backed
- Mock provider/network boundaries, not internal dataclasses where possible
- Use focused fixtures for project files and SQLite paths
- Validate both happy path and failure path for mutating actions

---

## See Also

- [Architecture Guide](architecture.md)
- [API Reference](api-reference.md)
- [Installation Guide](installation.md)
- [Reliability Policy](reliability-policy.md)
