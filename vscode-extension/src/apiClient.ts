/**
 * API Client — typed HTTP wrapper for all lit-critic REST endpoints.
 *
 * Uses Node's built-in http module (no external dependencies).
 * All methods return typed responses matching the Python backend.
 */

import * as http from 'http';
import {
    AnalysisSummary,
    AnalysisProgressEvent,
    ExplainResponse,
    Finding,
    ServerConfig,
    LearningData,
    RepoPreflightStatus,
    IndexAuditResponse,
    SceneAuditResponse,
    SceneProjectionResponse,
    IndexProjectionResponse,
    ProjectKnowledgeRefreshResponse,
    ProjectKnowledgeStatus,
    KnowledgeReviewResponse,
    KnowledgeOverrideResponse,
    KnowledgeOverrideDeleteResponse,
    KnowledgeEntityDeleteResponse,
    KnowledgeExportResponse,
    KnowledgeLockResponse,
    SceneLockResponse,
    SceneRenameResponse,
    SceneRefreshResponse,
    SceneOrphanPurgeResponse,
    InputStalenessResponse,
    AnalyzableScenesResponse,
} from './types';

/** Response shape for GET /api/findings/current. */
export type CurrentFindingsResponse = {
    scenes: Record<string, {
        snapshot_id: number;
        depth_mode: string;
        model: string;
        created_at: string;
        findings: Finding[];
    }>;
};

type LegacyIndexInsertBucket = {
    added?: unknown[];
};

type LegacyThreadIndexBucket = LegacyIndexInsertBucket & {
    advanced?: unknown[];
    closed?: unknown[];
};

type LegacyIndexSceneReport = {
    cast?: LegacyIndexInsertBucket;
    glossary?: LegacyIndexInsertBucket;
    threads?: LegacyThreadIndexBucket;
    timeline?: LegacyIndexInsertBucket;
    error?: string;
    [key: string]: unknown;
};

type LegacyIndexSceneResponse = {
    report: LegacyIndexSceneReport;
    summary: string;
};

export class ApiClient {
    private baseUrl: string;

    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }

    // ------------------------------------------------------------------
    // Generic HTTP helpers
    // ------------------------------------------------------------------

    private request<T>(method: string, path: string, body?: unknown, timeoutMs: number = 300_000): Promise<T> {
        return new Promise((resolve, reject) => {
            const url = new URL(path, this.baseUrl);
            const bodyStr = body !== undefined ? JSON.stringify(body) : undefined;

            const options: http.RequestOptions = {
                method,
                hostname: url.hostname,
                port: url.port,
                path: url.pathname + url.search,
                headers: {
                    'Accept': 'application/json',
                    ...(bodyStr ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
                },
                timeout: timeoutMs,
            };

            const req = http.request(options, (res) => {
                let data = '';
                res.on('data', (chunk: Buffer) => { data += chunk.toString(); });
                res.on('end', () => {
                    if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
                        try {
                            resolve(JSON.parse(data) as T);
                        } catch {
                            reject(new Error(`Invalid JSON response: ${data.slice(0, 200)}`));
                        }
                    } else {
                        let detail = data;
                        try {
                            const parsed = JSON.parse(data);
                            // Handle FastAPI validation errors (422)
                            if (res.statusCode === 422 && parsed.detail && Array.isArray(parsed.detail)) {
                                // Format validation errors nicely
                                const errors = parsed.detail.map((err: any) => 
                                    `${err.loc?.join('.') || 'unknown'}: ${err.msg}`
                                ).join(', ');
                                detail = `Validation error: ${errors}`;
                            } else if (typeof parsed.detail === 'string') {
                                detail = parsed.detail;
                            } else if (typeof parsed.detail === 'object') {
                                detail = JSON.stringify(parsed.detail);
                            } else {
                                detail = data;
                            }
                        } catch {
                            // keep raw data
                        }
                        reject(new Error(`HTTP ${res.statusCode}: ${detail}`));
                    }
                });
            });

            req.on('error', reject);
            req.on('timeout', () => {
                req.destroy();
                reject(new Error('Request timed out'));
            });

            if (bodyStr) {
                req.write(bodyStr);
            }
            req.end();
        });
    }

    /**
     * Open an SSE stream. Returns a function to abort the connection.
     * Calls `onEvent` for each parsed SSE event.
     */
    private streamSSE<T>(
        method: string,
        path: string,
        onEvent: (event: T) => void,
        onDone: () => void,
        onError: (err: Error) => void,
        body?: unknown,
    ): () => void {
        const url = new URL(path, this.baseUrl);
        const bodyStr = body !== undefined ? JSON.stringify(body) : undefined;

        const options: http.RequestOptions = {
            method,
            hostname: url.hostname,
            port: url.port,
            path: url.pathname + url.search,
            headers: {
                'Accept': 'text/event-stream',
                ...(bodyStr ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
            },
        };

        const req = http.request(options, (res) => {
            // Check for HTTP errors before attempting SSE parsing
            if (res.statusCode && (res.statusCode < 200 || res.statusCode >= 300)) {
                let errorBody = '';
                res.on('data', (chunk: Buffer) => { errorBody += chunk.toString(); });
                res.on('end', () => {
                    let detail = errorBody;
                    try {
                        const parsed = JSON.parse(errorBody);
                        detail = parsed.detail || errorBody;
                    } catch {
                        // keep raw body
                    }
                    onError(new Error(`HTTP ${res.statusCode}: ${detail}`));
                });
                return;
            }

            let buffer = '';

            res.on('data', (chunk: Buffer) => {
                buffer += chunk.toString();
                // Parse SSE lines
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // keep incomplete line in buffer

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith('data: ')) {
                        const jsonStr = trimmed.slice(6);
                        try {
                            const event = JSON.parse(jsonStr) as T;
                            onEvent(event);
                        } catch {
                            // skip malformed events
                        }
                    }
                    // Ignore comments (: keepalive) and empty lines
                }
            });

            res.on('end', onDone);
            res.on('error', onError);
        });

        req.on('error', onError);

        if (bodyStr) {
            req.write(bodyStr);
        }
        req.end();

        return () => req.destroy();
    }

    // ------------------------------------------------------------------
    // API endpoints
    // ------------------------------------------------------------------

    /** GET /api/config — health check and config info. */
    async getConfig(): Promise<ServerConfig> {
        return this.request<ServerConfig>('GET', '/api/config');
    }

    /** GET /api/repo-preflight — get backend repo-path preflight status. */
    async getRepoPreflight(): Promise<RepoPreflightStatus> {
        return this.request<RepoPreflightStatus>('GET', '/api/repo-preflight');
    }

    /** POST /api/repo-path — validate and persist backend repo path. */
    async updateRepoPath(repoPath: string): Promise<RepoPreflightStatus> {
        return this.request<RepoPreflightStatus>('POST', '/api/repo-path', {
            repo_path: repoPath,
        });
    }

    /** POST /api/analyze — start a new analysis (single or multi-scene). */
    async analyze(
        scenePath: string,
        projectPath: string,
        apiKey?: string,
        scenePaths?: string[],
        mode?: string,
    ): Promise<AnalysisSummary> {
        const effectivePaths = scenePaths && scenePaths.length > 0 ? scenePaths : [scenePath];
        // Deep analysis can take 20-30 minutes — use a 45-minute timeout.
        return this.request<AnalysisSummary>('POST', '/api/analyze', {
            scene_path: effectivePaths[0],
            scene_paths: effectivePaths,
            project_path: projectPath,
            ...(apiKey ? { api_key: apiKey } : {}),
            ...(mode ? { mode } : {}),
        }, 2_700_000);
    }

    /** POST /api/config/models — persist model-slot configuration. */
    async updateConfigModels(modelSlots: { frontier: string; deep: string; quick: string }): Promise<{ model_slots: { frontier: string; deep: string; quick: string } }> {
        return this.request<{ model_slots: { frontier: string; deep: string; quick: string } }>('POST', '/api/config/models', modelSlots);
    }

    /** POST /api/config — persist scene discovery configuration. */
    async updateConfig(sceneConfig: { scene_folder: string; scene_extensions: string[] }): Promise<{
        scene_folder: string;
        scene_extensions: string[];
        default_scene_folder: string;
        default_scene_extensions: string[];
    }> {
        return this.request<{
            scene_folder: string;
            scene_extensions: string[];
            default_scene_folder: string;
            default_scene_extensions: string[];
        }>('POST', '/api/config', sceneConfig);
    }

    /** POST /api/analyze/rerun — re-run analysis for current active session context. */
    async rerunAnalysis(projectPath: string, apiKey?: string): Promise<AnalysisSummary> {
        // Rerun can also be slow for large scenes — use the same 45-minute timeout.
        return this.request<AnalysisSummary>('POST', '/api/analyze/rerun', {
            project_path: projectPath,
            ...(apiKey ? { api_key: apiKey } : {}),
        }, 2_700_000);
    }

    /** GET /api/analyze/progress — SSE stream for analysis progress. */
    streamAnalysisProgress(
        onEvent: (event: AnalysisProgressEvent) => void,
        onDone: () => void,
        onError: (err: Error) => void,
    ): () => void {
        return this.streamSSE<AnalysisProgressEvent>(
            'GET', '/api/analyze/progress', onEvent, onDone, onError
        );
    }

    // ------------------------------------------------------------------
    // Management API endpoints
    // ------------------------------------------------------------------

    /** GET /api/findings/current — latest findings per scene in a single call. */
    async getCurrentFindings(projectPath: string): Promise<CurrentFindingsResponse> {
        return this.request<CurrentFindingsResponse>('GET', `/api/findings/current?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** DELETE /api/knowledge — delete ALL extracted knowledge, overrides and review flags. */
    async resetAllKnowledge(projectPath: string): Promise<{ reset: boolean }> {
        return this.request<{ reset: boolean }>('DELETE', `/api/knowledge?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** DELETE /api/analysis/snapshots — purge all analysis_snapshot rows, resetting scene status to not_analyzed. */
    async deleteAllAnalysisSnapshots(projectPath: string): Promise<{ deleted: boolean }> {
        return this.request<{ deleted: boolean }>('DELETE', `/api/analysis/snapshots?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** DELETE /api/analysis/snapshots/by-scene — delete the analysis snapshot and findings for a specific scene. */
    async deleteAnalysisForScene(projectPath: string, scenePath: string): Promise<{ deleted: boolean; count: number }> {
        return this.request<{ deleted: boolean; count: number }>(
            'DELETE',
            `/api/analysis/snapshots/by-scene?project_path=${encodeURIComponent(projectPath)}&scene_path=${encodeURIComponent(scenePath)}`,
        );
    }

    /** GET /api/learning — get learning data for a project. */
    async getLearning(projectPath: string): Promise<LearningData> {
        return this.request<LearningData>('GET', `/api/learning?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** POST /api/learning/export — export LEARNING.md. */
    async exportLearning(projectPath: string): Promise<{ exported: boolean; path: string }> {
        return this.request<{ exported: boolean; path: string }>('POST', '/api/learning/export', {
            project_path: projectPath,
        });
    }

    /** DELETE /api/learning — reset all learning data. */
    async resetLearning(projectPath: string): Promise<{ reset: boolean }> {
        return this.request<{ reset: boolean }>('DELETE', `/api/learning?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** DELETE /api/learning/entries/{id} — delete a learning entry. */
    async deleteLearningEntry(entryId: number, projectPath: string): Promise<{ deleted: boolean; entry_id: number }> {
        return this.request<{ deleted: boolean; entry_id: number }>('DELETE', `/api/learning/entries/${entryId}?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** GET /api/scenes — list projected scenes for a project. */
    async getScenes(projectPath: string): Promise<SceneProjectionResponse> {
        return this.request<SceneProjectionResponse>('GET', `/api/scenes?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** GET /api/indexes — list projected indexes for a project. */
    async getIndexes(projectPath: string): Promise<IndexProjectionResponse> {
        return this.request<IndexProjectionResponse>('GET', `/api/indexes?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** POST /api/knowledge/refresh — refresh scene + index projections and extracted knowledge. */
    async refreshKnowledge(projectPath: string): Promise<ProjectKnowledgeRefreshResponse> {
        return this.request<ProjectKnowledgeRefreshResponse>('POST', '/api/knowledge/refresh', {
            project_path: projectPath,
        });
    }

    /** Backward-compatible alias for older callers. */
    async refreshProjectKnowledge(projectPath: string): Promise<ProjectKnowledgeRefreshResponse> {
        return this.refreshKnowledge(projectPath);
    }

    /** GET /api/knowledge/review — load extracted entities + overrides for one category. */
    async getKnowledgeReview(category: string, projectPath: string): Promise<KnowledgeReviewResponse> {
        return this.request<KnowledgeReviewResponse>(
            'GET',
            `/api/knowledge/review?category=${encodeURIComponent(category)}&project_path=${encodeURIComponent(projectPath)}`,
        );
    }

    /** POST /api/knowledge/override — save one override field value. */
    async submitOverride(
        category: string,
        entityKey: string,
        fieldName: string,
        value: string,
        projectPath: string,
    ): Promise<KnowledgeOverrideResponse> {
        return this.request<KnowledgeOverrideResponse>('POST', '/api/knowledge/override', {
            category,
            entity_key: entityKey,
            field_name: fieldName,
            value,
            project_path: projectPath,
        });
    }

    /** DELETE /api/knowledge/override — delete one override field value. */
    async deleteOverride(
        category: string,
        entityKey: string,
        fieldName: string,
        projectPath: string,
    ): Promise<KnowledgeOverrideDeleteResponse> {
        return this.request<KnowledgeOverrideDeleteResponse>('DELETE', '/api/knowledge/override', {
            category,
            entity_key: entityKey,
            field_name: fieldName,
            project_path: projectPath,
        });
    }

    /** DELETE /api/knowledge/entity — delete an extracted entity and all its overrides. */
    async deleteKnowledgeEntity(
        category: string,
        entityKey: string,
        projectPath: string,
    ): Promise<KnowledgeEntityDeleteResponse> {
        return this.request<KnowledgeEntityDeleteResponse>('DELETE', '/api/knowledge/entity', {
            category,
            entity_key: entityKey,
            project_path: projectPath,
        });
    }

    /** POST /api/knowledge/export — export extracted knowledge markdown. */
    async exportKnowledge(projectPath: string): Promise<KnowledgeExportResponse> {
        return this.request<KnowledgeExportResponse>('POST', '/api/knowledge/export', {
            project_path: projectPath,
        });
    }

    /** POST /api/scenes/lock — lock one scene from automatic extraction. */
    async lockScene(sceneFilename: string, projectPath: string): Promise<SceneLockResponse> {
        return this.request<SceneLockResponse>('POST', '/api/scenes/lock', {
            scene_filename: sceneFilename,
            project_path: projectPath,
        });
    }

    /** POST /api/scenes/unlock — unlock one scene for automatic extraction. */
    async unlockScene(sceneFilename: string, projectPath: string): Promise<SceneLockResponse> {
        return this.request<SceneLockResponse>('POST', '/api/scenes/unlock', {
            scene_filename: sceneFilename,
            project_path: projectPath,
        });
    }

    /** POST /api/knowledge/lock — lock a knowledge entity from LLM updates. */
    async lockEntity(category: string, entityKey: string, projectPath: string): Promise<KnowledgeLockResponse> {
        return this.request<KnowledgeLockResponse>('POST', '/api/knowledge/lock', {
            category,
            entity_key: entityKey,
            project_path: projectPath,
        });
    }

    /** POST /api/knowledge/unlock — unlock a knowledge entity for LLM updates. */
    async unlockEntity(category: string, entityKey: string, projectPath: string): Promise<KnowledgeLockResponse> {
        return this.request<KnowledgeLockResponse>('POST', '/api/knowledge/unlock', {
            category,
            entity_key: entityKey,
            project_path: projectPath,
        });
    }

    /** POST /api/knowledge/dismiss-flag — dismiss a review flag for one entity. */
    async dismissReviewFlag(category: string, entityKey: string, projectPath: string): Promise<{ dismissed: boolean }> {
        return this.request<{ dismissed: boolean }>('POST', '/api/knowledge/dismiss-flag', {
            category,
            entity_key: entityKey,
            project_path: projectPath,
        });
    }

    /** POST /api/scenes/rename — rename one scene and propagate references. */
    async renameScene(oldName: string, newName: string, projectPath: string): Promise<SceneRenameResponse> {
        return this.request<SceneRenameResponse>('POST', '/api/scenes/rename', {
            old_filename: oldName,
            new_filename: newName,
            project_path: projectPath,
        });
    }

    /** POST /api/scenes/refresh — write discoverable scene files into scene_projection DB. */
    async refreshScenes(projectPath: string): Promise<SceneRefreshResponse> {
        return this.request<SceneRefreshResponse>('POST', '/api/scenes/refresh', {
            project_path: projectPath,
        });
    }

    /** POST /api/scenes/purge-orphans — delete DB rows for scenes no longer on disk. */
    async purgeOrphanedSceneRefs(projectPath: string): Promise<SceneOrphanPurgeResponse> {
        return this.request<SceneOrphanPurgeResponse>('POST', '/api/scenes/purge-orphans', {
            project_path: projectPath,
        });
    }

    /** GET /api/project/status — projection freshness summary. */
    async getProjectStatus(projectPath: string): Promise<ProjectKnowledgeStatus> {
        return this.request<ProjectKnowledgeStatus>('GET', `/api/project/status?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** GET /api/inputs/staleness — return stale inputs and their dependent knowledge/sessions. */
    async getInputStaleness(projectPath: string): Promise<InputStalenessResponse> {
        return this.request<InputStalenessResponse>('GET', `/api/inputs/staleness?project_path=${encodeURIComponent(projectPath)}`);
    }

    /** GET /api/scenes/analyzable — return scenes ready for analysis (extraction_due or extracted). */
    async getAnalyzableScenes(projectPath: string): Promise<AnalyzableScenesResponse> {
        return this.request<AnalyzableScenesResponse>('GET', `/api/scenes/analyzable?project_path=${encodeURIComponent(projectPath)}`);
    }

    /**
     * Backward-compat shim for legacy command paths; slated for removal once callers are migrated.
     */
    async indexScene(
        scenePath: string,
        projectPath: string,
        model?: string,
        apiKey?: string,
    ): Promise<LegacyIndexSceneResponse> {
        return this.request<LegacyIndexSceneResponse>('POST', '/api/index', {
            scene_path: scenePath,
            project_path: projectPath,
            ...(model ? { model } : {}),
            ...(apiKey ? { api_key: apiKey } : {}),
        });
    }

    /**
     * Backward-compat shim for legacy command paths; slated for removal once callers are migrated.
     */
    async auditIndexes(
        projectPath: string,
        deep: boolean = false,
        model?: string,
        apiKey?: string,
    ): Promise<IndexAuditResponse> {
        return this.request<IndexAuditResponse>('POST', '/api/audit', {
            project_path: projectPath,
            deep,
            ...(model ? { model } : {}),
            ...(apiKey ? { api_key: apiKey } : {}),
        });
    }

    /**
     * Backward-compat shim for legacy command paths; slated for removal once callers are migrated.
     */
    async auditScene(
        scenePath: string,
        projectPath: string,
        deep: boolean = false,
        model?: string,
        apiKey?: string,
    ): Promise<SceneAuditResponse> {
        return this.request<SceneAuditResponse>('POST', '/api/scenes/audit', {
            scene_path: scenePath,
            project_path: projectPath,
            deep,
            ...(model ? { model } : {}),
            ...(apiKey ? { api_key: apiKey } : {}),
        });
    }

    /**
     * POST /api/findings/{findingId}/explain — one-shot LLM explanation for a finding.
     *
     * The client passes the full finding object and the relevant scene text.
     * The server performs a single LLM query and returns an explanation.
     * No state is modified; no learning signal is generated.
     */
    async explainFinding(
        findingId: number,
        finding: Finding,
        sceneText: string,
        depth: 'quick' | 'deep',
        projectPath: string,
    ): Promise<ExplainResponse> {
        // Deep explanations use the frontier model — allow up to 5 minutes.
        const timeoutMs = depth === 'deep' ? 300_000 : 60_000;
        return this.request<ExplainResponse>(
            'POST',
            `/api/findings/${findingId}/explain?project_path=${encodeURIComponent(projectPath)}`,
            { depth, finding, scene_text: sceneText },
            timeoutMs,
        );
    }

}
