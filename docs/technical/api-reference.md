# API Reference

Complete REST API documentation for the lit-critic Platform API surface.

**Base URL:** `http://localhost:8000/api` (default)

---

## Overview

The lit-critic API surface exposes `/api/*` endpoints consumed by the VS Code extension for workflow operations.

### Architectural Boundary

- `/api/*` endpoints are the **Platform-facing** surface for clients.
- Platform orchestrates workflow/persistence and delegates stateless reasoning to Core (`/v1/*` contract endpoints).
- Clients should not call Core directly in normal operation.

### Authentication

Currently, the API key is passed in request bodies (not in headers). This is suitable for local-only deployment.

For remote deployments, use a trusted gateway and transport security; see:

- `docs/technical/security-remote-core.md`
- `docs/technical/reliability-policy.md`

### Content Type

All requests and responses use `application/json` unless otherwise specified.

---

## Endpoints

### Repository

#### `GET /api/repo-preflight`

Return preflight validation status for the configured lit-critic repository path.
Called by clients on startup to determine whether the installation path is valid before
attempting operations that require the Core.

**Request:** None

**Response:**
```json
{
  "ok": true,
  "reason_code": null,
  "path": "/path/to/lit-critic",
  "marker": ".lit-critic",
  "configured_path": "/path/to/lit-critic"
}
```

When the path is invalid:
```json
{
  "ok": false,
  "reason_code": "marker_not_found",
  "path": null,
  "marker": ".lit-critic",
  "configured_path": "/wrong/path"
}
```

**Fields:**
- `ok` (boolean) — Whether the configured path passes validation
- `reason_code` (string | null) — Why validation failed, or `null` if OK
- `path` (string | null) — Resolved absolute path, or `null` if invalid
- `marker` (string) — Marker filename the validator looks for
- `configured_path` (string | null) — Raw path currently persisted in user config

**Status Codes:**
- `200 OK` Always returns 200; check `ok` field for validity

---

#### `POST /api/repo-path`

Validate and persist a new lit-critic repository path.

**Request Body:**
```json
{
  "repo_path": "/path/to/lit-critic"
}
```

**Fields:**
- `repo_path` (string, required) — Path to validate and persist

**Response:** Same shape as `GET /api/repo-preflight`.

**Status Codes:**
- `200 OK` Path is valid and has been saved
- `400 Bad Request` Path failed validation; response body has same shape as preflight but with `"code": "repo_path_invalid"`

---

### Configuration

#### `GET /api/config`

Get available models and configuration.

**Request:** None

**Response:**
```json
{
  "api_key_configured": true,
  "api_keys_configured": {
    "anthropic": true,
    "openai": false
  },
  "available_models": {
    "opus": {
      "label": "Opus 4.6 (deepest analysis)",
      "provider": "anthropic",
      "id": "claude-opus-4-6",
      "max_tokens": 8192
    },
    "sonnet": {
      "label": "Sonnet 4.5 (default)",
      "provider": "anthropic",
      "id": "claude-sonnet-4-5-20250929",
      "max_tokens": 4096
    },
    "gpt-4o": {
      "label": "GPT-4o (default)",
      "provider": "openai",
      "id": "gpt-4o",
      "max_tokens": 4096
    }
  },
  "default_model": "sonnet",
  "analysis_modes": ["quick", "deep"],
  "default_analysis_mode": "deep",
  "mode_cost_hints": {
    "quick": "Quick mode prioritizes lower-cost checker-tier analysis.",
    "deep": "Deep mode runs checker + frontier discussion for highest coverage and highest expected cost."
  },
  "model_slots": {
    "frontier": "sonnet",
    "deep": "sonnet",
    "quick": "haiku"
  },
  "default_model_slots": {
    "frontier": "sonnet",
    "deep": "sonnet",
    "quick": "haiku"
  },
  "model_registry": {
    "auto_discovery_enabled": true,
    "cache_path": "C:/Users/alexi/.lit-critic-models-cache.json",
    "ttl_seconds": 86400,
    "last_refresh_attempt_at": 1772198720.42,
    "last_refresh_success_at": 1772198720.42
  }
}
```

Notes:
- `available_models` is dynamic (curated baseline + optional provider auto-discovery).
- `model_registry` exposes diagnostics only (no secrets/keys).
- `mode_cost_hints` is a UI-safe estimate string map keyed by analysis mode.

**Status Codes:**
- `200 OK` Success

#### `GET /api/config/models`

Get model-slot configuration and available models for mode-driven analysis.

**Request:** None

**Response:**
```json
{
  "model_slots": {
    "frontier": "sonnet",
    "deep": "sonnet",
    "quick": "haiku"
  },
  "default_model_slots": {
    "frontier": "sonnet",
    "deep": "sonnet",
    "quick": "haiku"
  },
  "available_models": {
    "sonnet": {
      "label": "Sonnet 4.5 (default)",
      "provider": "anthropic",
      "id": "claude-sonnet-4-5-20250929",
      "max_tokens": 4096
    }
  },
  "analysis_modes": ["quick", "deep"],
  "default_analysis_mode": "deep"
}
```

**Status Codes:**
- `200 OK` Success

#### `POST /api/config`

Update scene discovery configuration (scene folder and file extensions).

**Request Body:**
```json
{
  "scene_folder": "text",
  "scene_extensions": [".txt", ".md"]
}
```

**Fields:**
- `scene_folder` (string, required) — Subdirectory within the project to scan for scene files
- `scene_extensions` (string[], required) — File extensions to treat as scene files

**Response:**
```json
{
  "scene_folder": "text",
  "scene_extensions": [".txt", ".md"],
  "default_scene_folder": "text",
  "default_scene_extensions": [".txt"]
}
```

**Status Codes:**
- `200 OK` Configuration updated

---

#### `POST /api/config/models`

Validate and persist model-slot configuration.

**Request Body:**
```json
{
  "frontier": "gpt-4o",
  "deep": "sonnet",
  "quick": "haiku"
}
```

**Response:**
```json
{
  "model_slots": {
    "frontier": "gpt-4o",
    "deep": "sonnet",
    "quick": "haiku"
  },
  "default_model_slots": {
    "frontier": "sonnet",
    "deep": "sonnet",
    "quick": "haiku"
  }
}
```

**Status Codes:**
- `200 OK` Success
- `400 Bad Request` Invalid/unknown model in one or more slots

---

### Index Audit

#### `POST /api/audit`

Run index consistency audit for a project.

This endpoint always runs deterministic checks and can optionally run deep
semantic contradiction checks.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "deep": false,
  "api_key": "sk-ant-...",
  "model": "sonnet"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `deep` (boolean, optional, default `false`) — Include semantic contradiction checks
- `api_key` (string, optional) — Required only for deep mode when no provider key is available in environment
- `model` (string, optional) — Deep-mode model short name (defaults to configured default model)

**Response:**
```json
{
  "deterministic": [
    {
      "check_id": "orphan_first_seen",
      "severity": "warning",
      "file": "CAST.md",
      "location": "### Amelia Ashvale → First seen: 01.05.02",
      "message": "Scene 01.05.02 does not exist in TIMELINE.md",
      "related_file": "TIMELINE.md"
    }
  ],
  "semantic": [],
  "placeholder_census": {
    "CAST.md": 2
  },
  "formatted_report": "...",
  "deep": false,
  "model": null,
  "deep_error": null
}
```

Deep-mode failure policy:
- deterministic findings are still returned
- `deep_error` is populated with the semantic failure message
- endpoint does not fail unless deterministic path fails

**Status Codes:**
- `200 OK` Audit completed
- `404 Not Found` Project directory not found
- `400 Bad Request` Invalid request (e.g., missing deep-mode credentials when required)

---

### Project Knowledge Projection

These endpoints expose DB-backed projection state for scenes and indexes,
including explicit refresh and staleness status operations.

#### `GET /api/scenes`

List projected scenes for a project.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Response:**
```json
{
  "scenes": [
    {
      "scene_path": "text/chapter-01.txt",
      "scene_id": "01.01.01",
      "file_hash": "abc123...",
      "meta_json": {
        "POV": "Mara"
      },
      "last_refreshed_at": "2026-03-10T09:41:22Z"
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

#### `POST /api/scenes/refresh`

Refresh scene projections for all discovered scene files.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Response:**
```json
{
  "scenes": [
    {
      "scene_path": "text/chapter-01.txt",
      "updated": true
    }
  ],
  "total": 1,
  "updated": 1
}
```

**Status Codes:**
- `200 OK` Refresh completed
- `404 Not Found` Project directory not found

#### `GET /api/scenes/{scene_path}/status`

Return stale/fresh status for one scene projection.

**Path Parameters:**
- `scene_path` (string, required) — Project-relative scene path

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Response:**
```json
{
  "scene_path": "text/chapter-01.txt",
  "stale": false,
  "projected": true,
  "file_hash": "abc123...",
  "stored_hash": "abc123..."
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory or scene file not found

#### `GET /api/indexes`

List projected index files for a project.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Response:**
```json
{
  "indexes": [
    {
      "index_name": "CAST.md",
      "file_hash": "def456...",
      "entries_json": [
        {"name": "Mara", "type": "character"}
      ],
      "last_refreshed_at": "2026-03-10T09:41:22Z"
    },
    {
      "index_name": "STYLE.md",
      "file_hash": "fff000...",
      "entries_json": null,
      "last_refreshed_at": "2026-03-10T09:41:22Z"
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

#### `POST /api/indexes/refresh`

Refresh index projections for canonical index files.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Response:**
```json
{
  "indexes": [
    {
      "index_name": "CAST.md",
      "updated": true
    }
  ],
  "total": 1,
  "updated": 1
}
```

**Status Codes:**
- `200 OK` Refresh completed
- `404 Not Found` Project directory not found

#### `GET /api/indexes/status`

Return stale index projections for a project.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Response:**
```json
{
  "stale_indexes": ["CAST.md"],
  "stale_count": 1,
  "projected_count": 6
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

#### `POST /api/project/refresh`

Refresh both scene and index projections for a project.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Response:**
```json
{
  "scenes": [
    {"scene_path": "text/chapter-01.txt", "updated": true}
  ],
  "indexes": [
    {"index_name": "CAST.md", "updated": true}
  ]
}
```

**Status Codes:**
- `200 OK` Refresh completed
- `404 Not Found` Project directory not found

#### `GET /api/project/status`

Return project-knowledge freshness summary for scene and index projections.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Response:**
```json
{
  "scenes": {
    "total": 2,
    "stale": 1,
    "fresh": 1,
    "last_refreshed_at": null
  },
  "indexes": {
    "total": 6,
    "stale": 0,
    "fresh": 6,
    "last_refreshed_at": "2026-03-10T09:41:22Z"
  }
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

#### `POST /api/scenes/lock`

Lock a scene file to skip extraction when you run Refresh Knowledge.
Locked scenes are included in analysis but their content is not re-extracted.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "scene_filename": "text/chapter-01.txt"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `scene_filename` (string, required) — Project-relative scene filename to lock

**Response:**
```json
{
  "locked": true,
  "scene_filename": "text/chapter-01.txt"
}
```

**Status Codes:**
- `200 OK` Scene locked
- `404 Not Found` Project directory not found

---

#### `POST /api/scenes/unlock`

Unlock a scene file so extraction runs again when you run Refresh Knowledge.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "scene_filename": "text/chapter-01.txt"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `scene_filename` (string, required) — Project-relative scene filename to unlock

**Response:**
```json
{
  "unlocked": true,
  "scene_filename": "text/chapter-01.txt"
}
```

**Status Codes:**
- `200 OK` Scene unlocked
- `404 Not Found` Project directory not found

---

#### `POST /api/scenes/rename`

Rename a scene file and propagate all references: updates `Prev`/`Next`
metadata fields in adjacent scenes and updates DB projection entries.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "old_filename": "text/chapter-01.txt",
  "new_filename": "text/chapter-01-revised.txt"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `old_filename` (string, required) — Current project-relative filename
- `new_filename` (string, required) — New project-relative filename

**Response:**
```json
{
  "renamed": true,
  "old_filename": "text/chapter-01.txt",
  "new_filename": "text/chapter-01-revised.txt",
  "prev_updated": true,
  "next_updated": false
}
```

**Status Codes:**
- `200 OK` Rename completed
- `404 Not Found` Project directory or scene not found
- `400 Bad Request` New filename already exists or invalid path

---

### Knowledge Management

These endpoints manage extracted knowledge: refreshing it from scene content,
reviewing and overriding it, and exporting it as markdown.

Valid `category` values: `characters`, `terms`, `threads`, `timeline`.

#### `POST /api/knowledge/refresh`

Refresh scene projections, index projections, and extracted knowledge for a
project. This is the canonical replacement for the legacy `/api/scenes/refresh`
and `/api/indexes/refresh` endpoints.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory

**Response:**
```json
{
  "refreshed": true,
  "stale_scenes": ["text/chapter-01.txt"],
  "scenes": [
    {"scene_path": "text/chapter-01.txt", "updated": true}
  ],
  "indexes": [
    {"index_name": "CANON.md", "updated": false},
    {"index_name": "STYLE.md", "updated": false}
  ],
  "scene_total": 1,
  "chain_warnings": [],
  "extraction": {
    "scenes_scanned": 1,
    "extracted": ["characters", "terms"],
    "skipped_locked": []
  }
}
```

When nothing is stale:
```json
{
  "refreshed": false,
  "stale_scenes": [],
  "scenes": [],
  "indexes": [],
  "scene_total": 0,
  "chain_warnings": [],
  "extraction": {
    "scenes_scanned": 0,
    "extracted": [],
    "skipped_locked": []
  }
}
```

**Status Codes:**
- `200 OK` Refresh completed
- `404 Not Found` Project directory not found

---

#### `GET /api/knowledge/review`

Return extracted entities and author overrides for one knowledge category.

**Query Parameters:**
- `category` (string, required) — One of: `characters`, `terms`, `threads`, `timeline`
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "category": "characters",
  "entity_key_field": "name",
  "entities": [
    {
      "name": "Mara",
      "first_seen": "text/chapter-01.txt",
      "description": "Protagonist",
      "locked": false
    }
  ],
  "raw_entities": [
    {
      "name": "Mara",
      "first_seen": "text/chapter-01.txt",
      "description": "Protagonist"
    }
  ],
  "overrides": [
    {
      "entity_key": "Mara",
      "field_name": "description",
      "value": "Protagonist — revised by author"
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `400 Bad Request` Invalid category
- `404 Not Found` Project directory not found

---

#### `POST /api/knowledge/override`

Save an author override for one extracted knowledge field.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "category": "characters",
  "entity_key": "Mara",
  "field_name": "description",
  "value": "Protagonist — revised by author"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `category` (string, required) — Knowledge category
- `entity_key` (string, required) — Entity key (e.g., character name)
- `field_name` (string, required) — Field to override
- `value` (string, required) — Override value

**Response:**
```json
{
  "updated": true,
  "category": "characters",
  "entity_key": "Mara",
  "field_name": "description"
}
```

**Status Codes:**
- `200 OK` Override saved
- `404 Not Found` Project directory not found

---

#### `DELETE /api/knowledge/override`

Delete one previously saved knowledge override field value.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "category": "characters",
  "entity_key": "Mara",
  "field_name": "description"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `category` (string, required) — Knowledge category
- `entity_key` (string, required) — Entity key
- `field_name` (string, required) — Field whose override should be removed

**Response:**
```json
{
  "deleted": true,
  "category": "characters",
  "entity_key": "Mara",
  "field_name": "description"
}
```

**Status Codes:**
- `200 OK` Override deleted
- `404 Not Found` Project directory or override not found

---

#### `DELETE /api/knowledge/entity`

Delete an extracted knowledge entity and all its overrides.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "category": "characters",
  "entity_key": "Mara"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `category` (string, required) — Knowledge category
- `entity_key` (string, required) — Entity key to delete

**Response:**
```json
{
  "deleted": true,
  "entity_key": "Mara",
  "category": "characters"
}
```

**Status Codes:**
- `200 OK` Entity deleted
- `404 Not Found` Project directory or entity not found

---

#### `POST /api/knowledge/export`

Export extracted knowledge (with applied overrides) as a markdown string.
Does not write to disk — returns the markdown text for client-side use or download.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory

**Response:**
```json
{
  "markdown": "# Characters\n\n## Mara\n..."
}
```

**Status Codes:**
- `200 OK` Export generated
- `404 Not Found` Project directory not found

---

#### `POST /api/knowledge/review-pass`

Set the knowledge reconciliation review-pass trigger setting. This controls
when the LLM reconciliation pass runs after an extraction.

**Request Body:**
```json
{
  "value": "always"
}
```

**Fields:**
- `value` (string, required) — One of: `"always"`, `"on_stale"`, `"never"`

**Response:**
```json
{
  "knowledge_review_pass": "always"
}
```

**Status Codes:**
- `200 OK` Setting updated
- `400 Bad Request` Invalid value

---

#### `POST /api/knowledge/lock`

Lock a knowledge entity to prevent LLM updates and deletion during future
extraction passes.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "category": "characters",
  "entity_key": "Mara"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `category` (string, required) — Knowledge category
- `entity_key` (string, required) — Entity key to lock

**Response:**
```json
{
  "category": "characters",
  "entity_key": "Mara",
  "locked": true
}
```

**Status Codes:**
- `200 OK` Entity locked
- `404 Not Found` Project directory or entity not found

---

#### `POST /api/knowledge/unlock`

Unlock a knowledge entity so it can be updated or deleted by future extraction
passes.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "category": "characters",
  "entity_key": "Mara"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `category` (string, required) — Knowledge category
- `entity_key` (string, required) — Entity key to unlock

**Response:**
```json
{
  "category": "characters",
  "entity_key": "Mara",
  "locked": false
}
```

**Status Codes:**
- `200 OK` Entity unlocked
- `404 Not Found` Project directory or entity not found

---

### Analytics

Cross-session analytics endpoints for tracking patterns in author behaviour,
acceptance trends, scene finding history, and knowledge coverage gaps.

All analytics endpoints require `project_path` as a query parameter.

#### `GET /api/analytics/rejection-patterns`

Return aggregated rejection-pattern analytics for a project — which lens/severity
combinations the author most commonly rejects across sessions.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory
- `limit` (integer, optional, default `50`, range `1–500`) — Maximum number of aggregated rows
- `start_date` (string, optional) — ISO 8601 lower bound for session creation timestamp

**Request:** None

**Response:**
```json
{
  "analytics_version": "v1",
  "filters": {
    "limit": 50
  },
  "rows": [
    {
      "lens": "prose",
      "severity": "minor",
      "rejection_count": 14,
      "total_count": 20,
      "rejection_rate": 0.70
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

---

#### `GET /api/analytics/acceptance-rate-trend`

Return acceptance-rate trend across sessions for a project, bucketed by day or week.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory
- `bucket` (string, optional, default `"daily"`) — Aggregation bucket; one of `"daily"` or `"weekly"`
- `window` (integer, optional, default `30`, range `1–366`) — Maximum number of trend points to return

**Request:** None

**Response:**
```json
{
  "analytics_version": "v1",
  "filters": {
    "bucket": "daily",
    "sample_size": 87,
    "points": 14
  },
  "rows": [
    {
      "bucket": "2026-03-10",
      "accepted": 5,
      "total": 8,
      "acceptance_rate": 0.625
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

---

#### `GET /api/analytics/scene-finding-history`

Return per-scene finding history across all sessions for a specific scene.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory
- `scene_id` (string, required) — Scene path/identifier to filter findings by
- `limit` (integer, optional, default `50`, range `1–500`) — Maximum number of findings to return
- `offset` (integer, optional, default `0`) — Zero-based offset for pagination

**Request:** None

**Response:**
```json
{
  "analytics_version": "v1",
  "filters": {
    "scene_id": "text/chapter-01.txt"
  },
  "rows": [
    {
      "session_id": 3,
      "session_created_at": "2026-03-10T09:30:00",
      "lens": "prose",
      "severity": "major",
      "status": "accepted",
      "location": "L042-L045",
      "evidence": "..."
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

---

#### `GET /api/analytics/index-coverage-gaps`

Return a report of knowledge coverage gaps — scenes that have findings with
no matching entry in extracted knowledge (characters, terms, threads).

**Query Parameters:**
- `project_path` (string, required) — Path to project directory
- `session_start_id` (integer, optional) — Lower bound for session ID range
- `session_end_id` (integer, optional) — Upper bound for session ID range
- `scopes` (string[], optional) — Repeated scope filters; e.g., `scopes=cast&scopes=glossary`

**Request:** None

**Response:**
```json
{
  "analytics_version": "v1",
  "filters": {
    "session_start_id": null,
    "session_end_id": null,
    "scopes": null
  },
  "summary": {
    "total_gaps": 3,
    "scenes_with_gaps": 2
  },
  "missing_scene_paths": ["text/chapter-03.txt"],
  "rows": [
    {
      "scene_path": "text/chapter-01.txt",
      "scope": "cast",
      "entity": "Amelia",
      "context": "Amelia appears in scene but has no knowledge entry"
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `400 Bad Request` `session_start_id` > `session_end_id`
- `404 Not Found` Project directory not found

---

### Analysis

#### `POST /api/analyze`

Start a new analysis session.

**Request Body:**
```json
{
  "scene_path": "/path/to/scene.txt",
  "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
  "mode": "deep",
  "project_path": "/path/to/project/",
  "api_key": "sk-ant-...",
  "discussion_api_key": "sk-openai-..."
}
```

**Fields:**
- `scene_path` (string, optional) — Backward-compatible single-scene input
- `scene_paths` (string[], optional) — Multi-scene input (ordered scene set). If provided, this is used.
- At least one of `scene_path` or `scene_paths` must be present.
- `project_path` (string, required) — Absolute path to project directory
- `mode` (string, optional, default `deep`) — One of `quick`, `deep`; `quick` runs the full lens pipeline with the quick checker model slot; `deep` runs the full pipeline with the deep checker + frontier tiers
- `api_key` (string, optional) — API key for the resolved analysis model provider. If omitted, resolved from environment
- `discussion_api_key` (string, optional) — API key for the resolved discussion model provider when different from analysis provider
- Deprecated request fields `model` and `discussion_model` are rejected with `400 Bad Request`

**Response:**
```json
{
  "status": "success",
  "total_findings": 12,
  "scene_path": "/path/to/scene-01.txt",
  "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
  "mode_cost_hint": "Deep mode runs checker + frontier discussion for highest coverage and highest expected cost.",
  "tier_cost_summary": {
    "mode": "deep",
    "actuals_available": false,
    "checker": {
      "name": "sonnet",
      "label": "Sonnet 4.5 (default)",
      "provider": "anthropic",
      "input_tokens": null,
      "output_tokens": null,
      "cost_usd": null
    },
    "frontier": {
      "name": "gpt-4o",
      "label": "GPT-4o (default)",
      "provider": "openai",
      "input_tokens": null,
      "output_tokens": null,
      "cost_usd": null
    },
    "total_cost_usd": null
  },
  "summary": {
    "prose": {"critical": 1, "major": 2, "minor": 3},
    "structure": {"critical": 0, "major": 1, "minor": 1},
    "coherence": {"critical": 0, "major": 2, "minor": 2}
  },
  "current_finding": {
    "number": 1,
    "severity": "critical",
    "lens": "prose",
    "location": "L042-L045",
    "line_start": 42,
    "line_end": 45,
    "scene_path": "/path/to/scene-02.txt",
    "evidence": "The sentence spans 47 words...",
    "impact": "Readers may lose track...",
    "options": ["Break into two sentences", "..."],
    "flagged_by": ["prose"],
    "status": "pending"
  }
}
```

**Status Codes:**
- `200 OK` Analysis started successfully
- `400 Bad Request` Invalid request (missing fields, invalid mode/paths, deprecated model override fields)
- `500 Internal Server Error` Analysis failed

---

#### `GET /api/analyze/progress`

Stream analysis progress via Server-Sent Events (SSE).

**Request:** None (use after starting analysis)

**Response:** SSE stream

**Event Types:**

**1. Lens Progress**
```
event: lens_complete
data: {"lens": "prose", "message": "✓ prose lens complete"}
```

**2. Coordinator Progress**
```
event: coordinator
data: {"message": "Coordinating prose findings..."}
```

**3. Status Updates**
```
event: status
data: {"message": "Running 6 lenses in parallel..."}
```

**4. Warnings**
```
event: warning
data: {"message": "Coordinator chunk 'structure' failed: ..."}
```

**5. Completion**
```
event: complete
data: {"total_findings": 12}
```

**Status Codes:**
- `200 OK` Streaming started
- `404 Not Found` No active analysis

---

#### `POST /api/analyze/rerun`

Re-run analysis for the active session's scene set with the current model
settings. Used after making edits to a scene to get a fresh set of findings
without starting a new session from scratch.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "api_key": "sk-ant-...",
  "discussion_api_key": "sk-openai-..."
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `api_key` (string, optional) — API key for the analysis model provider
- `discussion_api_key` (string, optional) — API key for the discussion model provider when different from analysis provider

**Response:** Same shape as `POST /api/analyze`.

**Status Codes:**
- `200 OK` Re-analysis started successfully
- `404 Not Found` No active session
- `500 Internal Server Error` Analysis failed

---

### Session Management

#### `POST /api/resume`

Resume a previously saved session.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "api_key": "sk-ant-...",
  "scene_path_override": "/path/to/moved/scene.txt"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `api_key` (string, optional) — API key for the analysis model provider. If omitted, resolved from environment
- `discussion_api_key` (string, optional) — API key for the discussion model provider when it differs from analysis provider
- `scene_path_override` (string, optional) — Correct scene path to use when the saved path no longer exists (e.g., project moved to another machine)

**Response:**
```json
{
  "status": "success",
  "message": "Session resumed",
  "total_findings": 12,
  "current_index": 5,
  "current_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Session resumed
- `404 Not Found` No session file found
- `400 Bad Request` Session validation failed (scene modified)
- `409 Conflict` Saved scene path not found; response includes structured detail for recovery UIs

**409 Error Example:**
```json
{
  "detail": {
    "code": "scene_path_not_found",
    "message": "Saved scene file was not found. Provide scene_path_override to relink this session.",
    "saved_scene_path": "D:/old-machine/project/ch01.md",
    "attempted_scene_path": "D:/old-machine/project/ch01.md",
    "project_path": "D:/new-machine/project",
    "override_provided": false
  }
}
```

---

#### `POST /api/check-session`

Check if a saved session exists without loading it.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Response:**
```json
{
  "exists": true,
  "scene_path": "/path/to/scene.txt",
  "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
  "current_finding": 5,
  "total_findings": 12
}
```

**Status Codes:**
- `200 OK` Check complete

---

#### `POST /api/view-session`

Load a specific session (active, completed, or abandoned) into the runtime for viewing and navigation.

This endpoint is used by clients to inspect historical sessions while still using standard finding endpoints
(`GET /api/finding`, `POST /api/finding/goto`, `POST /api/finding/accept`, etc.).

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "session_id": 42,
  "api_key": "sk-ant-...",
  "scene_path_override": "/path/to/moved/scene.txt"
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `session_id` (integer, required) — Session to load
- `api_key` (string, optional) — API key for the analysis model provider. If omitted, resolved from environment
- `discussion_api_key` (string, optional) — API key for the discussion model provider when it differs from analysis provider
- `scene_path_override` (string, optional) — Correct scene path to use when the saved path no longer exists

**Response:**
```json
{
  "status": "success",
  "message": "Session loaded for viewing",
  "total_findings": 12,
  "current_index": 5,
  "current_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Session loaded
- `404 Not Found` Project directory or session not found
- `409 Conflict` Saved scene path not found; response includes structured detail for recovery UIs

**409 Error Example:**
```json
{
  "detail": {
    "code": "scene_path_not_found",
    "message": "Saved scene file was not found. Provide scene_path_override to relink this session.",
    "saved_scene_path": "D:/old-machine/project/ch01.md",
    "attempted_scene_path": "D:/old-machine/project/ch01.md",
    "project_path": "D:/new-machine/project",
    "override_provided": false
  }
}
```

---

#### `POST /api/resume-session`

Resume a specific active session by ID. Similar to `POST /api/resume` but
targets a session by its database ID rather than the project's most-recent
active session.

**Request Body:**
```json
{
  "project_path": "/path/to/project/",
  "session_id": 3,
  "api_key": "sk-ant-...",
  "discussion_api_key": "sk-openai-...",
  "scene_path_override": "/path/to/moved/scene.txt",
  "scene_path_overrides": {"old/path.txt": "new/path.txt"},
  "reopen": false
}
```

**Fields:**
- `project_path` (string, required) — Absolute path to project directory
- `session_id` (integer, required) — ID of the session to resume
- `api_key` (string, optional) — API key for the analysis model provider
- `discussion_api_key` (string, optional) — API key for the discussion model provider
- `scene_path_override` (string, optional) — Single-scene path remap for moved files
- `scene_path_overrides` (object, optional) — Multi-scene path remap `{oldPath: newPath}`
- `reopen` (boolean, optional, default `false`) — Force-reopen a completed or abandoned session

**Response:** Same shape as `POST /api/resume`.

**Status Codes:**
- `200 OK` Session resumed
- `404 Not Found` Session not found
- `409 Conflict` Scene path not found

---

#### `POST /api/session/summary`

Generate and return the session-end disconfirming meta-observation. Produces
an LLM summary of the overall session findings to help the author understand
recurring patterns before they close the session.

**Request:** None

**Response:**
```json
{
  "summary": "Across 12 findings, a pattern emerges: the author consistently..."
}
```

**Status Codes:**
- `200 OK` Summary generated
- `404 Not Found` No active session
- `500 Internal Server Error` Provider/Core processing error

---

#### `GET /api/session`

Get current session information.

**Request:** None

**Response:**
```json
{
  "total_findings": 12,
  "current_index": 5,
  "skip_minor": false,
  "model": "sonnet",
  "scene_path": "/path/to/scene.txt",
  "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
  "project_path": "/path/to/project/"
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` No active session

---

### Session History and Management

#### `GET /api/sessions`

List all sessions for a project (active, completed, abandoned).

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "sessions": [
    {
      "id": 3,
      "scene_path": "/path/to/scene.txt",
      "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
      "model": "sonnet",
      "status": "completed",
      "created_at": "2026-02-09T10:30:00",
      "completed_at": "2026-02-09T10:45:00",
      "total_findings": 12,
      "accepted_count": 5,
      "rejected_count": 3,
      "withdrawn_count": 1
    },
    {
      "id": 2,
      "scene_path": "/path/to/scene2.txt",
      "model": "opus",
      "status": "active",
      "created_at": "2026-02-09T09:00:00",
      "total_findings": 0
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

---

#### `GET /api/sessions/{session_id}`

Get detailed information about a specific session, including all findings.

This endpoint returns the persisted per-finding discussion thread so clients
can hydrate both active and historical views with full discussion context.

**Path Parameters:**
- `session_id` (int, required) — Session ID

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "session": {
    "id": 3,
    "scene_path": "/path/to/scene.txt",
    "scene_paths": ["/path/to/scene-01.txt", "/path/to/scene-02.txt"],
    "scene_hash": "abc123...",
    "model": "sonnet",
    "status": "completed",
    "created_at": "2026-02-09T10:30:00",
    "completed_at": "2026-02-09T10:45:00",
    "total_findings": 12,
    "accepted_count": 5,
    "rejected_count": 3,
    "withdrawn_count": 1
  },
  "findings": [
    {
      "number": 1,
      "severity": "major",
      "lens": "prose",
      "location": "L042-L045",
      "scene_path": "/path/to/scene-02.txt",
      "evidence": "...",
      "status": "accepted",
      "discussion_turns": [
        {"role": "user", "content": "I intended this ambiguity."},
        {"role": "assistant", "content": "Understood; revising severity."}
      ],
      "revision_history": [],
      "author_response": "",
      "outcome_reason": ""
    }
  ]
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found
- `404 Not Found` Session not found

---

#### `DELETE /api/sessions/{session_id}`

Delete a session and all its findings.

**Path Parameters:**
- `session_id` (int, required) — Session ID

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "deleted": true,
  "session_id": 3
}
```

**Status Codes:**
- `200 OK` Session deleted
- `404 Not Found` Session not found

---

### Learning Data Management

#### `GET /api/learning`

Get all learning data for a project.

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "id": 1,
  "project_name": "My Novel",
  "review_count": 12,
  "preferences": [
    {"id": 1, "description": "Author uses sentence fragments for pacing", "created_at": "2026-02-09T10:00:00"}
  ],
  "blind_spots": [
    {"id": 2, "description": "Author misses filter words", "created_at": "2026-02-09T10:05:00"}
  ],
  "resolutions": [],
  "ambiguity_intentional": [],
  "ambiguity_accidental": []
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` Project directory not found

---

#### `POST /api/learning/export`

Export learning data to LEARNING.md file.

**Request Body:**
```json
{
  "project_path": "/path/to/project/"
}
```

**Response:**
```json
{
  "exported": true,
  "path": "/path/to/project/LEARNING.md"
}
```

**Status Codes:**
- `200 OK` Exported successfully

---

#### `DELETE /api/learning`

Reset all learning data for a project (deletes all entries).

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "reset": true
}
```

**Status Codes:**
- `200 OK` Learning data reset

---

#### `DELETE /api/learning/entries/{entry_id}`

Delete a single learning entry.

**Path Parameters:**
- `entry_id` (int, required) — Entry ID

**Query Parameters:**
- `project_path` (string, required) — Path to project directory

**Request:** None

**Response:**
```json
{
  "deleted": true,
  "entry_id": 5
}
```

**Status Codes:**
- `200 OK` Entry deleted
- `404 Not Found` Entry not found

---

### Scene Content

#### `GET /api/scene`

Get the current scene content.

**Request:** None

**Response:**
```json
{
  "content": "@@META\nPrev: 01.02.05_scene.txt\nNext: 01.03.02_scene.txt\n@@END\n..."
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` No active session

---

### Finding Navigation

#### `GET /api/finding`

Get the current finding.

**Request:** None

**Response:**
```json
{
  "number": 5,
  "severity": "major",
  "lens": "structure",
  "location": "L042-L045",
  "line_start": 42,
  "line_end": 45,
  "scene_path": "/path/to/scene-02.txt",
  "evidence": "...",
  "impact": "...",
  "options": ["...", "..."],
  "flagged_by": ["structure"],
  "status": "pending",
  "stale": false,
  "discussion_turns": [],
  "revision_history": []
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` No current finding (review complete or no session)

---

#### `POST /api/finding/continue`

Advance to the next finding.

**Request:** None

**Response:**
```json
{
  "status": "advanced",
  "scene_changed": false,
  "current_finding": { /* Finding object */ }
}
```

**If review is complete:**
```json
{
  "status": "complete",
  "message": "All findings reviewed"
}
```

**If scene changed:**
```json
{
  "status": "advanced",
  "scene_changed": true,
  "adjusted": 8,
  "stale": 2,
  "re_evaluated": [
    {"finding_number": 5, "status": "updated"},
    {"finding_number": 7, "status": "withdrawn", "reason": "..."}
  ],
  "current_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` No active session

---

#### `POST /api/finding/goto`

Jump to a specific finding by index.

Behavior notes:
- In-range findings are always navigable, including terminal statuses such as
  `withdrawn`, `accepted`, and `rejected`.
- Response includes full persisted finding state (`discussion_turns`,
  `revision_history`, `author_response`, etc.) so clients can rehydrate
  historical discussion threads when revisiting completed findings.
- `complete: true` indicates an invalid/out-of-range index.

**Request Body:**
```json
{
  "index": 5
}
```

**Response:**
```json
{
  "complete": false,
  "scene_change": null,
  "finding": { /* Finding object with full state */ },
  "index": 5,
  "current": 6,
  "total": 12,
  "is_ambiguity": false
}
```

**Status Codes:**
- `200 OK` Success
- `404 Not Found` No active session

---

### Finding Actions

#### `POST /api/finding/accept`

Accept the current finding.

**Request:** None

**Response:**
```json
{
  "status": "accepted",
  "next_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Accepted
- `404 Not Found` No current finding

---

#### `POST /api/finding/reject`

Reject the current finding with optional reason.

**Request Body:**
```json
{
  "reason": "Intentional repetition for emphasis"
}
```

**Fields:**
- `reason` (string, optional) — Why you rejected it

**Response:**
```json
{
  "status": "rejected",
  "next_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Rejected
- `404 Not Found` No current finding

---

#### `POST /api/finding/ambiguity`

Mark ambiguity finding as intentional or accidental.

**Request Body:**
```json
{
  "intentional": true
}
```

**Response:**
```json
{
  "status": "marked",
  "next_finding": { /* Finding object */ }
}
```

**Status Codes:**
- `200 OK` Marked
- `400 Bad Request` Not an ambiguity finding
- `404 Not Found` No current finding

---

#### `POST /api/finding/review`

Re-check the current finding against scene edits. Compares the finding's
evidence against the current scene content to determine whether the finding
is still valid after the author has edited the scene.

**Request:** None

**Response:** The updated Finding object, with `stale` set to `false` if the
finding is still valid, or updated `status` if the finding was invalidated by
the edits.

```json
{
  "number": 5,
  "severity": "major",
  "lens": "prose",
  "status": "pending",
  "stale": false,
  "evidence": "..."
}
```

**Status Codes:**
- `200 OK` Review complete
- `404 Not Found` No current finding

---

### Discussion

#### `POST /api/finding/discuss`

Discuss the current finding (non-streaming).

**Request Body:**
```json
{
  "message": "This repetition is intentional for emphasis"
}
```

**Response:**
```json
{
  "response": "I understand your intent, but three occurrences...",
  "finding_updated": true,
  "changes": {
    "severity": "minor",
    "status": "revised"
  }
}
```

**Status Codes:**
- `200 OK` Discussion completed
- `404 Not Found` No current finding
- `500 Internal Server Error` Provider/Core processing error

---

#### `POST /api/finding/discuss/stream`

Discuss the current finding (streaming via SSE).

**Request Body:**
```json
{
  "message": "Why is this a problem?"
}
```

**Response:** SSE stream

**Event Types:**

**1. Token Stream**
```
event: token
data: {"token": "The "}
```

**2. Complete**
```
event: complete
data: {
  "full_response": "The sentence is 47 words...",
  "finding_updated": true,
  "changes": {"severity": "minor", "status": "revised"},
  "finding": {
    "number": 5,
    "status": "revised",
    "discussion_turns": [
      {"role": "user", "content": "Why is this a problem?"},
      {"role": "assistant", "content": "Because it interrupts pacing..."}
    ]
  }
}
```

`discussion_turns` is canonical Platform state: clients should re-render from
this array after a discussion completes so active and historical views stay in sync.

**3. Error**
```
event: error
data: {"error": "Provider API error: ..."}
```

**Status Codes:**
- `200 OK` Streaming started
- `404 Not Found` No current finding

---

### Bulk Actions

#### `POST /api/skip/minor`

Skip all remaining minor-severity findings.

**Request:** None

**Response:**
```json
{
  "status": "skipped",
  "skipped_count": 5,
  "current_finding": { /* Next non-minor finding */ }
}
```

**Status Codes:**
- `200 OK` Skipped
- `404 Not Found` No active session

---

#### `POST /api/skip/{lens}`

Skip to the next finding from a specific lens.

**Path Parameters:**
- `lens` (string) — One of: `prose`, `structure`, `logic`, `clarity`, `continuity`, `dialogue`, `horizon`
  - Group-level skip aliases are also supported by the web route layer (`structure`, `coherence`),
    where `coherence` covers `logic`, `clarity`, `continuity`, and `dialogue`.

**Request:** None

**Response:**
```json
{
  "status": "skipped",
  "current_finding": { /* First finding from target lens */ }
}
```

**Status Codes:**
- `200 OK` Skipped
- `404 Not Found` No findings from target lens
- `400 Bad Request` Invalid lens name

---

### Learning

#### `POST /api/learning/save`

Save LEARNING.md to project directory.

**Request:** None

**Response:**
```json
{
  "status": "success",
  "path": "/path/to/project/LEARNING.md",
  "preferences_count": 12
}
```

**Status Codes:**
- `200 OK` Saved
- `404 Not Found` No active session

---

## Data Models

### Finding Object

```typescript
interface Finding {
  number: number;
  severity: "critical" | "major" | "minor";
  lens: "prose" | "structure" | "logic" | "clarity" | "continuity" | "dialogue" | "horizon";
  location: string;                    // e.g., "L042-L045"
  line_start: number | null;           // 1-based line number
  line_end: number | null;
  scene_path: string | null;           // Owning scene file (multi-scene sessions)
  evidence: string;
  impact: string;
  options: string[];                   // Suggestions for fixing
  flagged_by: string[];                // List of lenses that flagged this
  ambiguity_type: string | null;       // For clarity findings
  stale: boolean;                      // True if scene was edited
  
  // Discussion state
  status: "pending" | "accepted" | "rejected" | "revised" | "withdrawn" | "escalated" | "discussed";
  author_response: string;
  discussion_turns: {role: string, content: string}[];
  revision_history: RevisionRecord[];
  outcome_reason: string;
}
```

### Revision Record

```typescript
interface RevisionRecord {
  timestamp: string;
  reason: string;
  old_severity: string;
  new_severity: string;
  old_evidence: string;
  new_evidence: string;
}
```

### Summary Object

```typescript
interface Summary {
  prose: {critical: number, major: number, minor: number};
  structure: {critical: number, major: number, minor: number};
  coherence: {critical: number, major: number, minor: number};
}
```

---

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message here"
}
```

### Common HTTP Status Codes

- `200 OK` Request succeeded
- `400 Bad Request` Invalid request (missing fields, invalid values)
- `404 Not Found` Resource not found (no session, no finding, etc.)
- `500 Internal Server Error` Platform/Core/provider failure

---

## Server-Sent Events (SSE)

Two endpoints use SSE for streaming:

1. `/api/analyze/progress` Analysis progress
2. `/api/finding/discuss/stream` Discussion responses

### SSE Format

```
event: <event_type>
data: <json_payload>

```

### Client Example (JavaScript)

```javascript
const eventSource = new EventSource('/api/analyze/progress');

eventSource.addEventListener('lens_complete', (event) => {
  const data = JSON.parse(event.data);
  console.log(`Lens ${data.lens} complete`);
});

eventSource.addEventListener('complete', (event) => {
  const data = JSON.parse(event.data);
  console.log(`Analysis complete: ${data.total_findings} findings`);
  eventSource.close();
});
```

---

## Rate Limiting

No rate limiting is currently implemented. The API is designed for local use only.

---

## CORS

CORS is enabled for all origins in development. For production deployment, configure `allow_origins` in `api/app.py`.

---

## Deployment Notes

### Local Development

```bash
python lit-critic-server.py --reload
```

### Production

Not recommended for public deployment without:
- API key security (move to headers/environment)
- Authentication/authorization
- Rate limiting
- HTTPS/TLS

For remote Core topologies, enforce gateway-based auth + TLS and keep Core non-publicly reachable.

---

## See Also

- **[Architecture Guide](architecture.md)** System design and data flow
- **[Testing Guide](testing.md)** API testing
- **[Installation Guide](installation.md)** Setup for development
- **[Remote Core Security](security-remote-core.md)** Auth/TLS guidance for remote Core deployments
- **[Reliability Policy](reliability-policy.md)** Retry/backoff/idempotency policy
