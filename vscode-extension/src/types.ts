/**
 * TypeScript interfaces mirroring the Python backend models.
 */

/** A single editorial finding from the analysis. */
export interface Finding {
    number: number;
    severity: 'critical' | 'major' | 'minor';
    lens: string;
    location: string;
    line_start: number | null;
    line_end: number | null;
    scene_path?: string | null;
    evidence: string;
    impact: string;
    options: string[];
    flagged_by: string[];
    ambiguity_type: string | null;
    stale: boolean;

    /**
     * New model states: active | silenced | resolved
     * Legacy interactive states (old sessions): pending | accepted | rejected | withdrawn | escalated | discussed | revised | conceded
     */
    status?: string;

    // Legacy interactive fields (present in old sessions only)
    author_response?: string;
    discussion_turns?: Array<{ role: string; content: string }>;
    revision_history?: Array<Record<string, unknown>>;
    outcome_reason?: string;
}

/** Analysis snapshot — the lightweight replacement for the interactive session model. */
export interface AnalysisSnapshot {
    id: number;
    scene_paths: string[];
    depth_mode: 'quick' | 'deep';
    models_used: { frontier?: string; checker?: string; quick?: string };
    created_at: string;
    scene_hashes: Record<string, string>;
    index_context_hash?: string | null;
    findings: Finding[];
    finding_count: number;
    active_count: number;
    silenced_count: number;
}

/** Silence rule from the backend. */
export interface SilenceRule {
    id: number;
    rule_type: 'instance' | 'pattern' | 'category';
    scope: 'scene' | 'project';
    scene_path: string;
    finding_id: number | null;
    lens: string;
    severity: string;
    text_pattern: string;
    note: string;
    suspended: boolean;
    created_at: string;
    suspended_at: string;
}

/** Response from POST /api/findings/{id}/explain. */
export interface ExplainResponse {
    finding_id: number;
    depth: string;
    explanation: string;
    model_used: string;
}

/** Request body for POST /api/silence-rules. */
export interface SilenceRuleCreateRequest {
    rule_type: 'instance' | 'pattern' | 'category';
    scope?: 'scene' | 'project';
    scene_path?: string;
    finding_id?: number;
    lens?: string;
    severity?: string;
    text_pattern?: string;
    note?: string;
}

/** UI-only transition payload used when review re-evaluates a finding context (legacy). */
export interface DiscussionContextTransition {
    previousFinding: Finding;
    previousTurns: Array<{ role: string; content: string }>;
    note?: string;
}

export interface IndexChangeReport {
    changed: boolean;
    stale: boolean;
    changed_files: string[];
    prompt: boolean;
}

export interface IndexAuditFinding {
    check_id: string;
    severity: 'error' | 'warning' | 'info';
    file: string;
    location: string;
    message: string;
    related_file?: string | null;
}

export interface IndexAuditResponse {
    deterministic: IndexAuditFinding[];
    semantic: IndexAuditFinding[];
    placeholder_census: Record<string, number>;
    formatted_report: string;
    deep: boolean;
    model: string;
    deep_error?: string | null;
}

export interface SceneAuditFinding {
    check_id: string;
    severity: 'error' | 'warning' | 'info';
    file: string;
    location: string;
    message: string;
    related_file?: string | null;
}

export interface SceneAuditResponse {
    deterministic: SceneAuditFinding[];
    semantic: SceneAuditFinding[];
    deep: boolean;
    model: string;
    deep_error?: string | null;
}

/** Response from GET /api/finding */
export interface FindingResponse {
    complete: boolean;
    message?: string;
    review?: SceneChangeReport;
    finding?: Finding;
    index?: number;
    current?: number;
    total?: number;
    is_ambiguity?: boolean;
    index_change?: IndexChangeReport | null;
}

/** Response from POST /api/analyze */
export interface AnalysisSummary {
    scene_path: string;
    scene_paths?: string[];
    scene_name: string;
    project_path: string;
    session_id?: number;
    total_findings: number;
    current_index: number;
    glossary_issues: string[];
    counts: { critical: number; major: number; minor: number };
    lens_counts: Record<string, { critical: number; major: number; minor: number }>;
    model: { name: string; id: string; label: string };
    discussion_model?: { name: string; id: string; label: string } | null;
    learning: { review_count: number; preferences: number; blind_spots: number };
    error?: string;
    findings_status?: Array<{
        number: number;
        severity: string;
        lens: string;
        status: string;
        location: string;
        evidence: string;
        line_start: number | null;
        line_end: number | null;
        scene_path?: string | null;
    }>;
    index_context_stale?: boolean;
    index_changed_files?: string[];
    rerun_recommended?: boolean;
    index_change?: IndexChangeReport;
    read_only?: boolean;
    session_status?: string;
}

export interface ResumeErrorDetail {
    code?: string;
    message?: string;
    saved_scene_path?: string;
    attempted_scene_path?: string;
    saved_scene_paths?: string[];
    missing_scene_paths?: string[];
    project_path?: string;
    override_provided?: boolean;
}

export interface ScenePathRecoverySelection {
    scenePathOverride?: string;
    scenePathOverrides?: Record<string, string>;
}

export interface RepoPreflightStatus {
    ok: boolean;
    reason_code?: string | null;
    message: string;
    path?: string | null;
    marker?: string;
    configured_path?: string | null;
}

export interface RepoPathInvalidDetail extends RepoPreflightStatus {
    code?: string;
    next_action?: string;
}

/** Response from GET /api/session */
export interface SessionInfo {
    active: boolean;
    scene_path?: string;
    scene_paths?: string[];
    scene_name?: string;
    project_path?: string;
    total_findings?: number;
    current_index?: number;
    findings_status?: Array<{
        number: number;
        severity: string;
        lens: string;
        status: string;
        location: string;
        evidence: string;
        line_start: number | null;
        line_end: number | null;
    }>;
    index_context_stale?: boolean;
    index_changed_files?: string[];
    rerun_recommended?: boolean;
    index_change?: IndexChangeReport;
}

/** Response from POST /api/finding/continue (and accept/reject) */
export interface AdvanceResponse {
    complete: boolean;
    message?: string;
    scene_change?: SceneChangeReport | null;
    finding?: Finding;
    index?: number;
    current?: number;
    total?: number;
    is_ambiguity?: boolean;
    // For accept/reject wrappers
    action?: Record<string, unknown>;
    next?: AdvanceResponse;
    index_change?: IndexChangeReport | null;
}

/** Scene change detection report */
export interface SceneChangeReport {
    changed: boolean;
    adjusted: number;
    stale: number;
    no_lines: number;
    re_evaluated: Array<{
        finding_number: number;
        status: string;
        reason?: string;
    }>;
}

/** Response from POST /api/finding/discuss */
export interface DiscussResponse {
    response: string;
    status: string;
    finding_status: string;
    finding?: Finding;
    revision_history?: Array<Record<string, unknown>>;
    error?: string;
    index_change?: IndexChangeReport | null;
}

/** SSE event from /api/analyze/progress */
export interface AnalysisProgressEvent {
    type: 'status' | 'code_checks_complete' | 'lens_complete' | 'lens_error' | 'warning' | 'error' | 'complete' | 'done';
    message?: string;
    lens?: string;
    total_findings?: number;
}

/** SSE event from /api/finding/discuss/stream */
export interface DiscussStreamEvent {
    type: 'token' | 'done';
    text?: string;
    response?: string;
    status?: string;
    finding_status?: string;
    finding?: Finding;
}

/** Response from GET /api/config */
export interface ServerConfig {
    api_key_configured: boolean;
    available_models: Record<string, {
        label: string;
        provider?: string;
        id?: string;
        max_tokens?: number;
    }>;
    default_model: string;
    analysis_modes?: string[];
    default_analysis_mode?: string;
    model_slots?: {
        frontier: string;
        deep: string;
        quick: string;
    };
    default_model_slots?: {
        frontier: string;
        deep: string;
        quick: string;
    };
    scene_folder?: string;
    scene_extensions?: string[];
    default_scene_folder?: string;
    default_scene_extensions?: string[];
    model_registry?: {
        auto_discovery_enabled: boolean;
        cache_path: string;
        ttl_seconds: number;
        last_refresh_attempt_at: number | null;
        last_refresh_success_at: number | null;
    };
}

/** Response from POST /api/check-session */
export interface CheckSessionResponse {
    exists: boolean;
    session_id?: number;
    scene_path?: string;
    saved_at?: string;
    current_index?: number;
    total_findings?: number;
}


/** Scene projection row from GET /api/scenes */
export interface SceneProjection {
    id?: number;
    scene_path: string;
    scene_id?: string | null;
    file_hash?: string | null;
    meta_json?: Record<string, unknown> | null;
    last_refreshed_at?: string | null;
    stale?: boolean;
    projected?: boolean;
}

/** Response from GET /api/scenes */
export interface SceneProjectionResponse {
    scenes: SceneProjection[];
}

/** Index projection row from GET /api/indexes */
export interface IndexProjection {
    id?: number;
    index_name: string;
    file_hash?: string | null;
    entries_json?: Array<Record<string, unknown>> | null;
    raw_content_hash?: string | null;
    last_refreshed_at?: string | null;
    stale?: boolean;
}

/** Response from GET /api/indexes */
export interface IndexProjectionResponse {
    indexes: IndexProjection[];
}

/** Response from GET /api/project/status */
export interface ProjectKnowledgeStatus {
    scenes: {
        total: number;
        stale: number;
        fresh: number;
        last_refreshed_at: string | null;
    };
    indexes: {
        total: number;
        stale: number;
        fresh: number;
        last_refreshed_at: string | null;
    };
    stale_total: number;
    fresh_total: number;
}

/** A single entity flagged for human review by the reconciliation pass. */
export interface KnowledgeReviewFlag {
    category: string;
    entity_key: string;
    reason: string;
}

/** Response from POST /api/project/refresh */
export interface ProjectKnowledgeRefreshResponse {
    scenes: Array<Record<string, unknown>>;
    indexes: Array<Record<string, unknown>>;
    scene_total: number;
    scene_updated: number;
    index_total: number;
    index_updated: number;
    extraction?: {
        attempted: boolean;
        extracted?: Array<unknown>;
        model_name?: string;
        reason?: string;
        /** Entities flagged for review by the reconciliation pass. */
        flagged_for_review?: KnowledgeReviewFlag[];
    };
    /** Top-level shortcut: populated when extraction includes reconciliation results. */
    flagged_for_review?: KnowledgeReviewFlag[];
}

export type KnowledgeCategoryKey = 'characters' | 'terms' | 'threads' | 'timeline';

export interface KnowledgeOverrideRecord {
    category?: string;
    entity_key?: string;
    field_name?: string;
    value?: unknown;
    override_value?: unknown;
    [key: string]: unknown;
}

export interface KnowledgeEntityTreeItemPayload {
    category: KnowledgeCategoryKey;
    entityKey: string;
    label: string;
    entity: Record<string, unknown>;
    /** Raw extracted entity without overrides applied. Used by the review panel
     *  to show the true "Extracted" value alongside the "Effective" (overridden) value. */
    rawEntity?: Record<string, unknown>;
    overrideFields: string[];
    overrideCount: number;
    hasOverrides: boolean;
    /** Whether the entity is locked from LLM updates. */
    locked: boolean;
    /** Whether the entity is flagged for review by the reconciliation pass. */
    flagged?: boolean;
    /** Whether the entity's source input is stale (set by Check for Changes). */
    stale?: boolean;
    /** Whether the entity's source scene no longer exists on disk (orphaned). */
    orphaned?: boolean;
}

export type KnowledgeReviewPanelStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';

export interface KnowledgeReviewPanelFieldState {
    fieldName: string;
    fieldLabel: string;
    extractedValue: string;
    overrideValue: string | null;
    effectiveValue: string;
    draftValue: string;
    hasOverride: boolean;
    isDirty: boolean;
    /** Which state color (if any) should be applied to this field's label. */
    stateColor: 'stale' | 'flagged' | 'locked' | 'overridden' | null;
}

export interface KnowledgeReviewPanelState {
    category: KnowledgeCategoryKey;
    categoryLabel: string;
    entityKey: string;
    entityLabel: string;
    locked: boolean;
    stale: boolean;
    flagged: boolean;
    hasOverrides: boolean;
    fields: KnowledgeReviewPanelFieldState[];
    selectedFieldName?: string;
    dirty: boolean;
    status: KnowledgeReviewPanelStatus;
    statusMessage?: string;
    lastSavedAt?: string | null;
}

export type KnowledgeReviewPanelAction =
    | { type: 'change-field'; fieldName: string; value: string }
    | { type: 'select-field'; fieldName: string }
    | { type: 'save-field'; fieldName: string; value: string }
    | { type: 'reset-field'; fieldName: string }
    | { type: 'next-entity' }
    | { type: 'previous-entity' }
    | { type: 'close' }
    | { type: 'delete-entity' };

/** Response from GET /api/knowledge/review */
export interface KnowledgeReviewResponse {
    category: string;
    entities?: Array<Record<string, unknown>>;
    raw_entities?: Array<Record<string, unknown>>;
    overrides?: KnowledgeOverrideRecord[];
    [key: string]: unknown;
}

/** Response from POST /api/knowledge/override */
export interface KnowledgeOverrideResponse {
    updated: boolean;
    category: string;
    entity_key: string;
    field_name: string;
}

/** Response from DELETE /api/knowledge/override */
export interface KnowledgeOverrideDeleteResponse {
    deleted: boolean;
    category: string;
    entity_key: string;
    field_name: string;
}

/** Response from DELETE /api/knowledge/entity */
export interface KnowledgeEntityDeleteResponse {
    deleted: boolean;
    entity_key: string;
    category: string;
}

/** Response from POST /api/knowledge/export */
export interface KnowledgeExportResponse {
    markdown: string;
}

/** Response from POST /api/knowledge/lock and /api/knowledge/unlock */
export interface KnowledgeLockResponse {
    category: string;
    entity_key: string;
    locked: boolean;
}

/** Response from POST /api/scenes/lock and /api/scenes/unlock */
export interface SceneLockResponse {
    scene_filename: string;
    locked?: boolean;
    unlocked?: boolean;
}

/** Response from POST /api/scenes/rename */
export interface SceneRenameResponse {
    renamed: boolean;
    old_filename?: string;
    new_filename?: string;
    [key: string]: unknown;
}

/** Response from POST /api/scenes/refresh */
export interface SceneRefreshResponse {
    scene_total: number;
    scene_updated: number;
    deprecated?: boolean;
    replacement?: string;
}

/** Response from POST /api/scenes/purge-orphans */
export interface SceneOrphanPurgeResponse {
    scene_projection: number;
    extracted_scene_metadata: number;
    extracted_character_sources: number;
    extracted_term_sources: number;
    extracted_thread_events: number;
    extracted_timeline: number;
}

/** Learning data from GET /api/learning */
export interface LearningData {
    project_name: string;
    review_count: number;
    preferences: Array<{ id?: number; description: string; created_at?: string }>;
    blind_spots: Array<{ id?: number; description: string; created_at?: string }>;
    resolutions: Array<{ id?: number; description: string; created_at?: string }>;
    ambiguity_intentional: Array<{ id?: number; description: string; created_at?: string }>;
    ambiguity_accidental: Array<{ id?: number; description: string; created_at?: string }>;
}

/** One stale input file entry from GET /api/inputs/staleness */
export interface InputStalenessEntry {
    path: string;
    type: 'scene' | 'reference';
    affected_knowledge: Array<{ category: string; entity_key: string }> | 'all';
    affected_sessions: number[];
}

/** One orphaned scene entry from GET /api/inputs/staleness */
export interface OrphanedSceneEntry {
    scene_key: string;
    affected_sessions: number[];
    affected_silence_rules: number[];
}

/** Response from GET /api/inputs/staleness */
export interface InputStalenessResponse {
    stale_inputs: InputStalenessEntry[];
    orphaned_scenes?: OrphanedSceneEntry[];
}

/** One scene entry from GET /api/scenes/analyzable */
export interface AnalyzableScene {
    scene_key: string;
    path: string;
    status: 'extraction_due' | 'extracted';
}

/** Response from GET /api/scenes/analyzable */
export interface AnalyzableScenesResponse {
    analyzable_scenes: AnalyzableScene[];
}
