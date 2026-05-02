# Installation Guide

This guide covers local setup for developing and running lit-critic.

## Prerequisites

- Python **3.10+**
- Node.js + npm (for TypeScript/VS Code extension workflows)
- At least one model provider API key:
  - `ANTHROPIC_API_KEY`
  - and/or `OPENAI_API_KEY`

## Clone the repository

```bash
git clone https://github.com/lit-pack/lit-critic.git
cd lit-critic
```

## Install dependencies

### Recommended (full workspace)

```bash
npm run install
```

This installs Python and TypeScript dependencies used across the repository.

### Python-only install (alternative)

```bash
pip install -r requirements.txt
```

## Configure API keys

### macOS / Linux

```bash
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"
```

### Windows (PowerShell)

```powershell
setx ANTHROPIC_API_KEY "your-key-here"
setx OPENAI_API_KEY "your-key-here"
```

> Configure the key(s) that match the providers/models you plan to use.

## Optional: model auto-discovery controls

lit-critic can auto-discover newly available provider models and merge them into
the runtime model registry (with cache + TTL fallback).

Optional environment variables:

- `LIT_CRITIC_MODEL_DISCOVERY_ENABLED` (`1`/`0`) — enable/disable auto-discovery
- `LIT_CRITIC_MODEL_DISCOVERY_TTL_SECONDS` — refresh interval between discovery attempts
- `LIT_CRITIC_MODEL_DISCOVERY_TIMEOUT_SECONDS` — timeout for provider model-list calls
- `LIT_CRITIC_MODEL_CACHE_PATH` — cache file path override for discovered models

If omitted, sensible defaults are used.

## Run lit-critic

### API server

```bash
python lit-critic-server.py
```

Optional flags:

```bash
python lit-critic-server.py --port 3000
python lit-critic-server.py --reload
```

## Run tests

### Full test suite

```bash
npm test
```

### Python tests only

```bash
pytest --cov=core --cov=orchestrator --cov=web --cov=contracts
```

### TypeScript tests only

```bash
npm run test:ts
```

## VS Code extension development

```bash
cd vscode-extension
npm install
npm run compile
```

Then open `vscode-extension/` in VS Code and press **F5**.

## Troubleshooting

- **No model access / auth errors**
  - Verify environment variables are set in the same shell/session launching lit-critic.
- **Newly released model not showing yet**
  - Confirm `LIT_CRITIC_MODEL_DISCOVERY_ENABLED=1`.
  - Ensure the relevant provider key is configured (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`).
  - Lower `LIT_CRITIC_MODEL_DISCOVERY_TTL_SECONDS` for faster refresh during testing.
- **Port already in use**
  - Start web with a custom port, e.g. `--port 3000`.
- **Extension cannot find lit-critic repo**
  - Set `litCritic.repoPath` in VS Code settings to the folder containing `lit-critic-server.py`.

## See Also

- [Architecture Guide](architecture.md)
- [API Reference](api-reference.md)
- [Testing Guide](testing.md)
- [Versioning & Compatibility](versioning.md)
- [Release Checklist](release-checklist.md)