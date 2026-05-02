/**
 * WorkflowController — command handlers for analysis, model, server,
 * learning, and knowledge management.
 *
 * All VS Code interactions are injected through WorkflowUiPort.
 * All collaborator services are injected through WorkflowDeps.
 */

import { ApiClient } from '../apiClient';
import { AnalysisTreeProvider } from '../analysisTreeProvider';
import { DiagnosticsProvider } from '../diagnosticsProvider';
import { FindingsTreeProvider } from '../findingsTreeProvider';
import { LearningTreeProvider } from '../learningTreeProvider';
import { IDiscussionView } from '../ui/workbenchPresenter';
import {
    buildAnalysisStartStatusMessage,
    getConfiguredAnalysisModel,
} from '../domain/modelSelectionLogic';
import {
    Finding,
    KnowledgeEntityTreeItemPayload,
} from '../types';
import { RuntimeStateStore } from './stateStore';
import {
    cmdRefreshLearning,
    cmdExportLearning,
    cmdResetLearning,
    cmdDeleteLearningEntry as cmdDeleteLearningEntryHandler,
} from './learningWorkflowHandlers';
import {
    cmdEditKnowledgeEntry as cmdEditKnowledgeEntryHandler,
    cmdResetKnowledgeOverride as cmdResetKnowledgeOverrideHandler,
    cmdResetAllKnowledge as cmdResetAllKnowledgeHandler,
} from './knowledgeWorkflowHandlers';
import {
    cmdSelectModel as cmdSelectModelHandler,
} from './modelSelectionWorkflow';
import {
    formatTierCostSummary,
    WorkbenchPresenter,
} from '../ui/workbenchPresenter';

// ---------------------------------------------------------------------------
// Helpers (moved from sessionDecisionLogic.ts)
// ---------------------------------------------------------------------------

function tryParseRepoPathInvalidDetail(message: string): { code?: string; message?: string } | null {
    const match = message.match(/^HTTP\s+\d+:\s+(\{.*\})$/);
    if (!match) {
        return null;
    }

    try {
        const detail = JSON.parse(match[1]) as { code?: string; message?: string };
        if (detail && detail.code === 'repo_path_invalid') {
            return detail;
        }
    } catch {
        // ignore parse failures
    }

    return null;
}

// ---------------------------------------------------------------------------
// Port interface — VS Code surface injected by extension.ts
// ---------------------------------------------------------------------------

export interface WorkflowUiPort {
    // Messages
    showInformationMessage(message: string, ...items: string[]): Promise<string | undefined>;
    showErrorMessage(message: string, ...items: string[]): Promise<string | undefined>;
    showWarningMessage(message: string, modal: boolean, ...items: string[]): Promise<string | undefined>;

    // User inputs
    showInputBox(options: {
        prompt?: string;
        placeHolder?: string;
        value?: string;
        ignoreFocusOut?: boolean;
        validateInput?: (value: string) => string | null;
    }): Promise<string | undefined>;
    showQuickPick(items: any[], options?: { placeHolder?: string; activeItemLabel?: string }): Promise<any>;

    // File operations
    showOpenDialog(options: {
        canSelectFiles: boolean;
        canSelectFolders: boolean;
        canSelectMany: boolean;
        openLabel?: string;
        title?: string;
    }): Promise<Array<{ fsPath: string }> | undefined>;
    showTextDocument(fsPath: string, options?: {
        viewColumn?: number;
        preview?: boolean;
        preserveFocus?: boolean;
    }): Promise<any>;

    // Progress / status
    withProgress(title: string, task: (progress: { report(v: { message?: string }): void }) => Promise<void>): Promise<void>;
    // Navigation
    navigateToFindingLine(finding: Finding): Promise<void>;

    // Filesystem check
    pathExists(p: string): boolean;
    getOpenTextDocumentPaths(): string[];

    // Extension configuration
    getExtensionConfig(): {
        get<T>(key: string, defaultValue: T): T;
        inspect<T>(key: string): { globalValue?: T; workspaceValue?: T; workspaceFolderValue?: T } | undefined;
    };
}

// ---------------------------------------------------------------------------
// Deps interface — all collaborators injected by extension.ts
// ---------------------------------------------------------------------------

export interface WorkflowDeps {
    getApiClient(): ApiClient;
    ensureServer(): Promise<void>;
    getServerManager(): { stop(): void; isRunning: boolean; repoRoot?: string } | undefined;
    state: RuntimeStateStore;
    presenter: WorkbenchPresenter;
    findingsTreeProvider: FindingsTreeProvider;
    learningTreeProvider: LearningTreeProvider;
    knowledgeTreeProvider: {
        setApiClient(client: ApiClient): void;
        setProjectPath(projectPath: string): void;
        refresh(): Promise<void>;
        setFlaggedEntities(flags: Array<{ category: string; entity_key: string; reason: string }>): void;
        clearFlaggedEntities(): void;
    };
    knowledgeTreeView?: { reveal(item: any, options?: { select?: boolean; focus?: boolean }): Thenable<void> };
    diagnosticsProvider: DiagnosticsProvider;
    analysisTreeProvider?: AnalysisTreeProvider;
    ensureDiscussionPanel(): IDiscussionView;
    getDiscussionPanel(): IDiscussionView | undefined;
    runTrackedOperation<T>(
        profile: { id: string; title: string; statusMessage?: string },
        operation: () => Promise<T>,
    ): Promise<T>;
    detectProjectPath(): string | undefined;
    ui: WorkflowUiPort;
    /** Optional logger — writes timestamped lines to the lit-critic output channel. */
    log?(message: string): void;
}

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

export class WorkflowController {
    constructor(private readonly deps: WorkflowDeps) {}

    // -----------------------------------------------------------------------
    // Public command handlers
    // -----------------------------------------------------------------------

    cmdAnalyze = async (): Promise<void> => { await this._cmdAnalyze(); };
    cmdSelectModel = async (): Promise<void> => { await this._cmdSelectModel(); };
    cmdStopServer = (): void => { this._cmdStopServer(); };
    cmdRefreshLearning = async (): Promise<void> => { await this._cmdRefreshLearning(); };
    cmdExportLearning = async (): Promise<void> => { await this._cmdExportLearning(); };
    cmdResetLearning = async (): Promise<void> => { await this._cmdResetLearning(); };
    cmdDeleteLearningEntry = async (item: any): Promise<void> => { await this._cmdDeleteLearningEntry(item); };
    cmdRefreshKnowledge = async (): Promise<void> => { await this._cmdRefreshKnowledge(); };
    cmdEditKnowledgeEntry = async (item: any): Promise<void> => { await this._cmdEditKnowledgeEntry(item); };
    cmdResetKnowledgeOverride = async (item?: any): Promise<void> => { await this._cmdResetKnowledgeOverride(item); };
    editKnowledgeEntry = async (item: any): Promise<boolean> => this._cmdEditKnowledgeEntry(item);
    resetKnowledgeOverride = async (item?: any): Promise<boolean> => this._cmdResetKnowledgeOverride(item);
    cmdResetAllKnowledge = async (): Promise<void> => { await this._cmdResetAllKnowledge(); };
    cmdResetAllAnalysis = async (): Promise<void> => { await this._cmdResetAllAnalysis(); };
    cmdDeleteSceneAnalysis = async (item: any): Promise<void> => { await this._cmdDeleteSceneAnalysis(item); };

    // -----------------------------------------------------------------------
    // Private — analyze (produces snapshot)
    // -----------------------------------------------------------------------

    private async _cmdAnalyze(): Promise<void> {
        try {
            await this.deps.ensureServer();
            const client = this.deps.getApiClient();

            const projectPath = this.deps.detectProjectPath();
            if (!projectPath) {
                void this.deps.ui.showErrorMessage(
                    'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
                );
                return;
            }

            // Check which scenes are ready for analysis.
            const analyzableResult = await client.getAnalyzableScenes(projectPath).catch(() => undefined);
            const scenePaths_list = analyzableResult
                ? analyzableResult.analyzable_scenes.map((s) => s.path)
                : [];

            if (scenePaths_list.length === 0) {
                void this.deps.ui.showInformationMessage(
                    'lit-critic: All scenes are up to date — nothing to analyze.',
                );
                return;
            }

            const scenePath = scenePaths_list[0];
            const scenePaths = scenePaths_list.length > 1 ? scenePaths_list : undefined;

            const config = this.deps.ui.getExtensionConfig();
            const model = getConfiguredAnalysisModel(config);

            this.deps.presenter.setAnalyzing(buildAnalysisStartStatusMessage(model));
            void this.deps.ui.showInformationMessage('lit-critic: Starting analysis...');
            this.deps.log?.(`ANALYSIS starting — model: ${model}, scenes: ${scenePaths_list.length}, timeout: 2700s`);

            let firstProgressEventSeen = false;
            let resolveFirstProgressEvent: (() => void) | undefined;
            const firstProgressEventPromise = new Promise<void>((resolve) => {
                resolveFirstProgressEvent = resolve;
            });
            const markFirstProgressEvent = (): void => {
                if (firstProgressEventSeen) { return; }
                firstProgressEventSeen = true;
                resolveFirstProgressEvent?.();
                resolveFirstProgressEvent = undefined;
            };

            const analysisPromise = (async () => {
                try {
                    const result = await client.analyze(
                        scenePath, projectPath,
                        undefined, scenePaths, model,
                    );
                    this.deps.log?.(`ANALYSIS response received — ${result.total_findings} findings, session_id: ${result.session_id ?? 'none'}`);
                    return result;
                } catch (err) {
                    const message = err instanceof Error ? err.message : String(err);
                    this.deps.log?.(`ANALYSIS request error — ${message}`);
                    const detail = tryParseRepoPathInvalidDetail(message);
                    if (!detail) { throw err; }
                    const sm = this.deps.getServerManager();
                    const repoRoot = sm?.repoRoot;
                    if (!repoRoot) { throw err; }
                    this.deps.log?.('ANALYSIS retrying after repo path update...');
                    await client.updateRepoPath(repoRoot);
                    const result = await client.analyze(
                        scenePath, projectPath,
                        undefined, scenePaths, model,
                    );
                    this.deps.log?.(`ANALYSIS response received (retry) — ${result.total_findings} findings, session_id: ${result.session_id ?? 'none'}`);
                    return result;
                }
            })();

            await new Promise((r) => setTimeout(r, 250));

            const progressPromise = new Promise<void>((resolve) => {
                client.streamAnalysisProgress(
                    (event) => {
                        markFirstProgressEvent();
                        switch (event.type) {
                            case 'status':
                                this.deps.log?.(`SSE status: ${event.message}`);
                                this.deps.presenter.setAnalyzing(event.message);
                                break;
                            case 'code_checks_complete':
                                this.deps.log?.(`SSE code_checks_complete: ${event.message}`);
                                this.deps.presenter.setAnalyzing(`✓ Code checks: ${event.message ?? 'complete'}`);
                                break;
                            case 'lens_complete':
                                this.deps.log?.(`SSE lens_complete: ${event.lens}`);
                                this.deps.presenter.setAnalyzing(`✓ ${event.lens} complete`);
                                break;
                            case 'lens_error':
                                this.deps.log?.(`SSE lens_error: ${event.lens} — ${event.message}`);
                                void this.deps.ui.showErrorMessage(`lit-critic: ${event.lens} lens failed: ${event.message}`);
                                break;
                            case 'complete':
                                this.deps.log?.('SSE complete: analysis finished on server');
                                this.deps.presenter.setAnalyzing('Analysis complete!');
                                break;
                            case 'done':
                                this.deps.log?.('SSE done: stream closed by server');
                                markFirstProgressEvent();
                                resolve();
                                break;
                            default:
                                this.deps.log?.(`SSE ${(event as any).type}: (unhandled event)`);
                                break;
                        }
                    },
                    () => { markFirstProgressEvent(); this.deps.log?.('SSE stream ended (transport closed)'); resolve(); },
                    (err) => { markFirstProgressEvent(); this.deps.log?.(`SSE stream error: ${err.message}`); resolve(); },
                );
            });

            await this.deps.ui.withProgress(
                'lit-critic: Starting analysis',
                async (progress) => {
                    progress.report({ message: 'Sending analysis request...' });
                    await Promise.race([
                        firstProgressEventPromise,
                        analysisPromise.then(() => undefined),
                    ]);
                },
            );

            const summary = await analysisPromise;
            await progressPromise;

            if (summary.error) {
                this.deps.presenter.setError(summary.error);
                void this.deps.ui.showErrorMessage(`lit-critic: Analysis failed — ${summary.error}`);
                return;
            }

            let modelInfo = `Model: ${summary.model.label}`;
            if (summary.discussion_model) {
                modelInfo += ` · Discussion: ${summary.discussion_model.label}`;
            }

            void this.deps.ui.showInformationMessage(
                `lit-critic: Found ${summary.total_findings} findings ` +
                `(${summary.counts.critical} critical, ${summary.counts.major} major, ${summary.counts.minor} minor) · ${modelInfo}`
            );

            const tierCostSummary = formatTierCostSummary((summary as any)?.tier_cost_summary);
            if (tierCostSummary) {
                void this.deps.ui.showInformationMessage(`lit-critic: ${tierCostSummary}`);
            }

            // Populate findings tree from snapshot findings
            if (summary.findings_status) {
                const findings: Finding[] = summary.findings_status.map((f) => ({
                    number: f.number,
                    severity: f.severity as 'critical' | 'major' | 'minor',
                    lens: f.lens,
                    location: f.location,
                    line_start: f.line_start ?? null,
                    line_end: f.line_end ?? null,
                    scene_path: (f as any).scene_path ?? null,
                    evidence: f.evidence ?? '',
                    impact: '',
                    options: [],
                    flagged_by: [],
                    ambiguity_type: null,
                    stale: false,
                    status: f.status,
                }));
                this.deps.state.allFindings = findings;
                this.deps.state.totalFindings = findings.length;
                this.deps.findingsTreeProvider.setFindings(findings, summary.scene_path, 0);
                this.deps.diagnosticsProvider.setScenePath(summary.scene_path, summary.scene_paths);
                this.deps.diagnosticsProvider.updateFromFindings(findings);

                // Feed findings into the Analysis tree grouped by scene so
                // manual analysis results appear immediately (not only via
                // loop SSE events).
                if (this.deps.analysisTreeProvider) {
                    // Clear old entries first — path keys may differ between
                    // hydration (startup) and analysis response, causing
                    // duplicate scene rows if we don't wipe before re-populating.
                    this.deps.analysisTreeProvider.clear();
                    const findingsByScene = new Map<string, Finding[]>();
                    for (const f of findings) {
                        const key = f.scene_path ?? summary.scene_path ?? 'unknown';
                        const arr = findingsByScene.get(key);
                        if (arr) { arr.push(f); } else { findingsByScene.set(key, [f]); }
                    }
                    for (const [sp, sceneFindings] of findingsByScene) {
                        this.deps.analysisTreeProvider.setFindings(sp, sceneFindings);
                    }
                }
            }

            this._refreshManagementViews();
            this.deps.presenter.setReady();

        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            this.deps.log?.(`ANALYSIS failed — ${msg}`);
            this.deps.presenter.setError(msg);
            void this.deps.ui.showErrorMessage(`lit-critic: ${msg}`);
        }
    }

    // -----------------------------------------------------------------------
    // Private — model / server
    // -----------------------------------------------------------------------

    private async _cmdSelectModel(): Promise<void> {
        await cmdSelectModelHandler(this.deps);
    }

    private _cmdStopServer(): void {
        const sm = this.deps.getServerManager();
        if (sm) {
            sm.stop();
            this.deps.presenter.setReady();
            void this.deps.ui.showInformationMessage('lit-critic: Server stopped.');
        } else {
            void this.deps.ui.showInformationMessage('lit-critic: No server is running.');
        }
    }

    // -----------------------------------------------------------------------
    // Private — learning
    // -----------------------------------------------------------------------

    private async _cmdRefreshLearning(): Promise<void> {
        await cmdRefreshLearning(this.deps);
    }

    private async _cmdExportLearning(): Promise<void> {
        await cmdExportLearning(this.deps);
    }

    private async _cmdResetLearning(): Promise<void> {
        await cmdResetLearning(this.deps);
    }

    private async _cmdDeleteLearningEntry(item: any): Promise<void> {
        await cmdDeleteLearningEntryHandler(item, this.deps);
    }

    // -----------------------------------------------------------------------
    // Private — knowledge
    // -----------------------------------------------------------------------

    private async _cmdRefreshKnowledge(): Promise<void> {
        this.deps.presenter.setAnalyzing('Refreshing knowledge...');
        try {
            await this.deps.runTrackedOperation(
                { id: 'refresh-knowledge', title: 'Refreshing knowledge', statusMessage: 'Refreshing knowledge...' },
                async () => {
                    await this.deps.ensureServer();
                    const projectPath = this.deps.detectProjectPath();
                    if (!projectPath) {
                        void this.deps.ui.showErrorMessage(
                            'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
                        );
                        return;
                    }

                    const result = await this.deps.getApiClient().refreshKnowledge(projectPath);
                    const refreshResult = result as any;
                    const extraction = refreshResult?.extraction as Record<string, unknown> | undefined;
                    const extractionReason = typeof extraction?.reason === 'string' ? extraction.reason : undefined;
                    const extractionError = typeof extraction?.error === 'string' ? extraction.error : undefined;
                    const extractionFailed = Array.isArray(extraction?.failed) ? (extraction.failed as any[]).length : 0;
                    const extractionExtracted = Array.isArray(extraction?.extracted) ? (extraction.extracted as any[]).length : 0;
                    const firstFailedScene = Array.isArray(extraction?.failed) && (extraction.failed as any[]).length > 0
                        ? (extraction.failed as any[])[0]
                        : undefined;
                    const firstFailedError = typeof firstFailedScene?.error === 'string' ? firstFailedScene.error : undefined;

                    const hasExtractionIssue = extractionReason === 'extraction_unavailable' || extractionFailed > 0;
                    if (hasExtractionIssue) {
                        let warningMessage: string;
                        if (extractionReason === 'partial_failure' && extractionFailed > 0) {
                            const sceneDetail = firstFailedError ? ` — ${firstFailedError}` : '';
                            warningMessage = `lit-critic: Knowledge refreshed — ${extractionExtracted} scene(s) extracted, but ${extractionFailed} failed${sceneDetail}. Refresh again to retry.`;
                        } else {
                            const reasonLabel = extractionReason ?? 'unknown';
                            const detail = extractionError ? ` — ${extractionError}` : '';
                            warningMessage = `lit-critic: Knowledge refresh completed, but extraction failed (${reasonLabel})${detail}. Categories may remain empty.`;
                        }
                        void this.deps.ui.showWarningMessage(warningMessage, false);
                    } else if (extractionReason === 'no_stale_scenes') {
                        void this.deps.ui.showInformationMessage(
                            'lit-critic: Knowledge refreshed. No stale scenes — extraction skipped.',
                        );
                    } else {
                        void this.deps.ui.showInformationMessage(
                            `lit-critic: Knowledge refreshed — ${extractionExtracted} scene(s) extracted.`,
                        );
                    }

                    // Auto-populate the knowledge tree view after server-side refresh
                    const client = this.deps.getApiClient();
                    this.deps.knowledgeTreeProvider.setApiClient(client);
                    this.deps.knowledgeTreeProvider.setProjectPath(projectPath);
                    await this.deps.knowledgeTreeProvider.refresh();

                    // Propagate flagged entities from reconciliation pass
                    const flaggedItems: Array<{ category: string; entity_key: string; reason: string }> =
                        Array.isArray((extraction as any)?.flagged_for_review)
                            ? ((extraction as any).flagged_for_review as Array<{ category: string; entity_key: string; reason: string }>)
                            : [];
                    if (flaggedItems.length > 0) {
                        this.deps.knowledgeTreeProvider.setFlaggedEntities(flaggedItems);
                        void this.deps.ui.showInformationMessage(
                            `lit-critic: ${flaggedItems.length} knowledge item(s) flagged for review by reconciliation pass.`,
                        );
                    } else {
                        this.deps.knowledgeTreeProvider.clearFlaggedEntities();
                    }
                },
            );
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            this.deps.presenter.setError(msg);
            void this.deps.ui.showErrorMessage(`lit-critic: ${msg}`);
            return;
        }
        this.deps.presenter.setReady();
    }

    private async _cmdEditKnowledgeEntry(item: any): Promise<boolean> {
        return cmdEditKnowledgeEntryHandler(item, this.deps);
    }

    private async _cmdResetKnowledgeOverride(item?: any): Promise<boolean> {
        return cmdResetKnowledgeOverrideHandler(item, this.deps);
    }

    private async _cmdResetAllKnowledge(): Promise<void> {
        await cmdResetAllKnowledgeHandler(this.deps);
    }

    private async _cmdResetAllAnalysis(): Promise<void> {
        const projectPath = this.deps.detectProjectPath();
        if (!projectPath) {
            void this.deps.ui.showErrorMessage(
                'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
            );
            return;
        }

        const answer = await this.deps.ui.showWarningMessage(
            'Reset all analysis? This will delete all analysis snapshots and clear current findings. Learning from past analysis has already been committed. This cannot be undone.',
            true,
            'Reset',
        );
        if (answer !== 'Reset') {
            return;
        }

        const apiClient = this.deps.getApiClient();
        if (apiClient) {
            await apiClient.deleteAllAnalysisSnapshots(projectPath);
        }

        this.deps.analysisTreeProvider?.clear();
        this.deps.findingsTreeProvider.clear();
        this.deps.diagnosticsProvider.clear();
        void this.deps.ui.showInformationMessage('All analysis has been reset.');
    }

    private async _cmdDeleteSceneAnalysis(item: any): Promise<void> {
        const scenePath: string | undefined = item?.scenePath;
        if (!scenePath) {
            void this.deps.ui.showErrorMessage('lit-critic: Could not determine scene path.');
            return;
        }

        const projectPath = this.deps.detectProjectPath();
        if (!projectPath) {
            void this.deps.ui.showErrorMessage(
                'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
            );
            return;
        }

        try {
            await this.deps.getApiClient().deleteAnalysisForScene(projectPath, scenePath);
            this.deps.analysisTreeProvider?.setFindings(scenePath, []);
            this.deps.findingsTreeProvider.clear();
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            void this.deps.ui.showErrorMessage(`lit-critic: ${msg}`);
        }
    }

    // -----------------------------------------------------------------------
    // Private — helpers
    // -----------------------------------------------------------------------

    private _refreshManagementViews(): void {
        const projectPath = this.deps.detectProjectPath();
        const apiClient = this.deps.getApiClient();
        if (!projectPath || !apiClient) {
            return;
        }

        this.deps.learningTreeProvider.setApiClient(apiClient);
        this.deps.learningTreeProvider.setProjectPath(projectPath);
        this.deps.learningTreeProvider.refresh().catch(() => {});

        this.deps.knowledgeTreeProvider.setApiClient(apiClient);
        this.deps.knowledgeTreeProvider.setProjectPath(projectPath);
        this.deps.knowledgeTreeProvider.refresh().catch(() => {});
    }

}
