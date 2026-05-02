/**
 * lit-critic — VS Code Extension entry point.
 *
 * Orchestrates all components:
 *   - ServerManager: spawns/stops the FastAPI backend
 *   - ApiClient: typed HTTP wrapper for the REST API
 *   - DiagnosticsProvider: maps findings to squiggly underlines
 *   - FindingsTreeProvider: sidebar tree view of all findings
 *   - DiscussionPanel: webview for interactive discussion
 *   - StatusBar: quick status overview
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

import { ServerManager } from './serverManager';
import { ApiClient } from './apiClient';
import { DiagnosticsProvider } from './diagnosticsProvider';
import { FindingsDecorationProvider, FindingsTreeProvider } from './findingsTreeProvider';
import { AnalysisTreeProvider } from './analysisTreeProvider';
import { ScenesTreeProvider, SceneTreeItem } from './scenesTreeProvider';
import { KnowledgeTreeProvider } from './knowledgeTreeProvider';
import { LearningTreeProvider } from './learningTreeProvider';
import { DiscussionViewProvider } from './discussionViewProvider';
import { KnowledgeReviewViewProvider } from './knowledgeReviewViewProvider';
import { StatusBar } from './statusBar';
import { OperationTracker } from './operationTracker';
import { REPO_MARKER, validateRepoPath } from './repoPreflight';
import {
    Finding,
    KnowledgeCategoryKey,
} from './types';
import {
    KnowledgeReviewHelperDeps,
    buildKnowledgeReviewPanelState,
    hydrateKnowledgeReviewPanel,
    navigateKnowledgeReviewPanel,
    loadKnowledgeEntityPayload,
    resolveKnowledgeEntityReviewTarget,
} from './ui/knowledgeReviewHelpers';
import { StalenessRegistry } from './workflows/stalenessRegistry';
import {
    StalenessServiceDeps,
    recheckStaleness,
} from './workflows/stalenessService';
import { ExplainCodeActionProvider } from './workflows/explainActionProvider';
import {
    debugScenesTrace,
    syncSceneDiscoverySettingsToServer,
    getSceneDiscoverySettingsFromConfig,
} from './bootstrap/sceneDiscoveryConfig';
import { createRuntimeStateStore } from './workflows/stateStore';
import { WorkbenchPresenter } from './ui/workbenchPresenter';
import { StartupService } from './bootstrap/startupService';
import { registerCommands } from './commands/registerCommands';
import {
    WorkflowController,
    WorkflowDeps,
    WorkflowUiPort,
} from './workflows/workflowController';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let serverManager: ServerManager | undefined;
let apiClient: ApiClient;
let diagnosticsProvider: DiagnosticsProvider;
let findingsTreeProvider: FindingsTreeProvider;
let scenesTreeProvider: ScenesTreeProvider;
let knowledgeTreeProvider: KnowledgeTreeProvider;
let findingsDecorationProvider: FindingsDecorationProvider;
let analysisTreeProvider: AnalysisTreeProvider;
let learningTreeProvider: LearningTreeProvider;
let scenesTreeView: vscode.TreeView<any> | undefined;
let knowledgeTreeView: vscode.TreeView<any> | undefined;
let findingsTreeView: vscode.TreeView<any> | undefined;
let sessionsTreeView: vscode.TreeView<any> | undefined;
let discussionPanel: DiscussionViewProvider;
let knowledgeReviewPanel: KnowledgeReviewViewProvider | undefined;
let statusBar: StatusBar;
let operationTracker: OperationTracker;
let presenter: WorkbenchPresenter;
let startupService: StartupService;
let stalenessRegistry: StalenessRegistry = new StalenessRegistry();
let controller: WorkflowController;
let extensionContext: vscode.ExtensionContext | undefined;
let sceneFileWatcherDisposables: vscode.Disposable[] = [];
// Single shared debounce timer for staleness re-checks. Both the save listener
// and the file-system watcher use this timer so that a save (which triggers
// both paths) results in exactly one API call.
let stalenessDebounceTimer: ReturnType<typeof setTimeout> | undefined;
// When true, the file system watcher skips refresh calls. Set during in-tool
// renames so the watcher doesn't duplicate the refresh the rename command
// already does explicitly.
let sceneWatcherSuppressed = false;


const state = createRuntimeStateStore();

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    extensionContext = context;

    // Always initialize UI components so the sidebar tree view is registered,
    // even when the lit-critic repo root is not found (e.g. user opened
    // a scene folder rather than the repo itself).
    statusBar = new StatusBar();
    operationTracker = new OperationTracker();
    diagnosticsProvider = new DiagnosticsProvider();
    findingsDecorationProvider = new FindingsDecorationProvider();
    findingsTreeProvider = new FindingsTreeProvider(findingsDecorationProvider);
    scenesTreeProvider = new ScenesTreeProvider();
    scenesTreeProvider.setLogger((msg) => operationTracker.log(msg));
    knowledgeTreeProvider = new KnowledgeTreeProvider();
    analysisTreeProvider = new AnalysisTreeProvider();
    learningTreeProvider = new LearningTreeProvider();

    // Register tree views — must always happen so VS Code can populate the sidebar
    findingsTreeView = vscode.window.createTreeView('litCritic.findings', {
        treeDataProvider: findingsTreeProvider,
        showCollapseAll: true,
    });

    scenesTreeView = vscode.window.createTreeView('litCritic.scenes', {
        treeDataProvider: scenesTreeProvider,
        showCollapseAll: true,
    });

    knowledgeTreeView = vscode.window.createTreeView('litCritic.indexes', {
        treeDataProvider: knowledgeTreeProvider,
        showCollapseAll: true,
    });

    sessionsTreeView = vscode.window.createTreeView('litCritic.sessions', {
        treeDataProvider: analysisTreeProvider,
        showCollapseAll: true,
    });

    // Create and register WebviewView providers for the Secondary Side Bar.
    // Registration must happen during activate() so VS Code calls resolveWebviewView()
    // when the sidebar is opened. The DiscussionViewProvider uses a lazy ApiClient
    // getter so it can be registered before the server is started.
    discussionPanel = new DiscussionViewProvider();
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'litCritic.discussionView',
            discussionPanel,
            { webviewOptions: { retainContextWhenHidden: true } },
        ),
    );

    knowledgeReviewPanel = new KnowledgeReviewViewProvider();
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'litCritic.knowledgeReviewView',
            knowledgeReviewPanel,
            { webviewOptions: { retainContextWhenHidden: true } },
        ),
    );

    presenter = new WorkbenchPresenter({
        statusBar,
        diagnosticsProvider,
        findingsTreeProvider,
        ensureDiscussionPanel,
        getDiscussionPanel: () => discussionPanel,
    });
    presenter.bindTreeViews(findingsTreeView, sessionsTreeView);

    // Initialize StartupService with concrete VS Code and filesystem ports.
    // Ports are created here (inside activate) so that test stubs injected via
    // proxyquire (e.g. vscode, fs) are captured correctly by the closures.
    startupService = new StartupService({
        getConfiguredRepoPath: () =>
            vscode.workspace.getConfiguration('litCritic').get<string>('repoPath', '').trim(),
        getAutoStartEnabled: () =>
            vscode.workspace.getConfiguration('litCritic').get<boolean>('autoStartServer', true),
        updateConfiguredRepoPath: (value) =>
            Promise.resolve(vscode.workspace.getConfiguration('litCritic').update(
                'repoPath', value, vscode.ConfigurationTarget.Global,
            )),
        pathExists: (p) => fs.existsSync(p),
        getWorkspaceFolders: () => {
            const folders = vscode.workspace.workspaceFolders;
            return folders
                ? (Array.from(folders) as Array<{ uri: { fsPath: string } }>)
                : undefined;
        },
        showErrorModal: (msg, ...buttons) =>
            vscode.window.showErrorMessage(msg, { modal: true }, ...(buttons as [string, ...string[]])) as Promise<string | undefined>,
        showFolderPicker: async () => {
            const picked = await vscode.window.showOpenDialog({
                canSelectFiles: false,
                canSelectFolders: true,
                canSelectMany: false,
                openLabel: 'Use this folder',
            });
            return picked?.[0]?.fsPath;
        },
        openSettings: (key) =>
            vscode.commands.executeCommand('workbench.action.openSettings', key) as Promise<void>,
        getConfiguredRepoPathAfterSettingsEdit: () =>
            vscode.workspace.getConfiguration('litCritic').get<string>('repoPath', '').trim(),
        withProgressNotification: (title, message, task) =>
            vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title, cancellable: false },
                async (progress) => { progress.report({ message }); await task(); },
            ) as Promise<void>,
        executeCommand: (cmd) =>
            vscode.commands.executeCommand(cmd) as Promise<void>,
    });

    const learningTreeView = vscode.window.createTreeView('litCritic.learning', {
        treeDataProvider: learningTreeProvider,
        showCollapseAll: true,
    });

    // Register all disposables
    const lockedEntityDecorationProvider: vscode.FileDecorationProvider = {
        provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
            if (uri.scheme === 'knowledge-flagged') {
                return { color: new vscode.ThemeColor('litCritic.flaggedForReviewForeground') };
            }
            if (uri.scheme === 'knowledge-overridden') {
                return { color: new vscode.ThemeColor('litCritic.overriddenForeground') };
            }
            if (uri.scheme === 'knowledge-locked') {
                return { color: new vscode.ThemeColor('litCritic.authorOverrideForeground') };
            }
            if (uri.scheme === 'source-stale') {
                return { color: new vscode.ThemeColor('litCritic.staleForeground') };
            }
            return undefined;
        },
    };

    context.subscriptions.push(
        statusBar,
        operationTracker,
        diagnosticsProvider,
        vscode.window.registerFileDecorationProvider(findingsDecorationProvider),
        vscode.window.registerFileDecorationProvider(lockedEntityDecorationProvider),
        findingsTreeView,
        scenesTreeView,
        knowledgeTreeView,
        sessionsTreeView,
        learningTreeView,
    );

    const findingsVisibilityDisposable = findingsTreeView.onDidChangeVisibility?.((event) => {
        if (event.visible) {
            presenter.revealCurrentFindingSelection();
        }
    });
    if (findingsVisibilityDisposable) {
        context.subscriptions.push(findingsVisibilityDisposable);
    }

    // Build WorkflowUiPort adapter — maps the controller's narrow interface to
    // real VS Code APIs. Created inside activate() so proxyquire stubs are
    // captured correctly by the closures.
    const uiPort: WorkflowUiPort = {
        showInformationMessage: (msg, ...items) =>
            vscode.window.showInformationMessage(msg, ...items) as Promise<string | undefined>,
        showErrorMessage: (msg, ...items) =>
            vscode.window.showErrorMessage(msg, ...items) as Promise<string | undefined>,
        showWarningMessage: (msg, modal, ...items) =>
            vscode.window.showWarningMessage(
                msg, { modal }, ...(items as [string, ...string[]])
            ) as Promise<string | undefined>,
        showInputBox: (opts) => vscode.window.showInputBox(opts) as Promise<string | undefined>,
        showQuickPick: async (items, opts) => {
            if (!opts?.activeItemLabel || typeof (vscode.window as any).createQuickPick !== 'function') {
                return vscode.window.showQuickPick(items, {
                    placeHolder: opts?.placeHolder,
                }) as Promise<any>;
            }

            const qp = (vscode.window as any).createQuickPick();
            qp.items = items as any[];
            qp.placeholder = opts.placeHolder;

            const activeItem = (items as any[]).find((item: any) => {
                const label = typeof item === 'string' ? item : item?.label;
                return label === opts.activeItemLabel;
            });
            if (activeItem) {
                qp.activeItems = [activeItem];
            }

            return await new Promise<any>((resolve) => {
                let settled = false;

                const acceptDisp = qp.onDidAccept(() => {
                    if (settled) {
                        return;
                    }
                    settled = true;
                    const selected = qp.selectedItems?.[0] ?? qp.activeItems?.[0];
                    acceptDisp.dispose();
                    hideDisp.dispose();
                    qp.dispose();
                    resolve(selected);
                });

                const hideDisp = qp.onDidHide(() => {
                    if (settled) {
                        return;
                    }
                    settled = true;
                    acceptDisp.dispose();
                    hideDisp.dispose();
                    qp.dispose();
                    resolve(undefined);
                });

                qp.show();
            });
        },
        showOpenDialog: (opts) =>
            vscode.window.showOpenDialog(opts) as unknown as Promise<Array<{ fsPath: string }> | undefined>,
        showTextDocument: (fsPath, opts) =>
            vscode.window.showTextDocument(vscode.Uri.file(fsPath), {
                viewColumn: opts?.viewColumn as vscode.ViewColumn | undefined,
                preview: opts?.preview,
                preserveFocus: opts?.preserveFocus,
            }) as Promise<any>,
        withProgress: (title, task) =>
            vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title, cancellable: false },
                async (progress) => { await task(progress); },
            ) as Promise<void>,
        navigateToFindingLine: (finding) => navigateToFindingLine(finding),
        pathExists: (p) => fs.existsSync(p),
        getOpenTextDocumentPaths: () => {
            const paths = new Set<string>();
            const tabGroups = (vscode.window as any).tabGroups?.all;

            if (Array.isArray(tabGroups)) {
                for (const group of tabGroups) {
                    const tabs = Array.isArray(group?.tabs) ? group.tabs : [];
                    for (const tab of tabs) {
                        const input: any = tab?.input;
                        const candidateUris: Array<any> = [
                            input?.uri,
                            input?.modified,
                            input?.modified?.uri,
                            input?.original,
                            input?.original?.uri,
                        ];

                        for (const uri of candidateUris) {
                            if (uri?.scheme === 'file' && typeof uri.fsPath === 'string' && uri.fsPath.length > 0) {
                                paths.add(uri.fsPath);
                            }
                        }
                    }
                }
            }

            // Fallback for test stubs / older hosts where tabGroups may be unavailable.
            if (paths.size === 0) {
                for (const editor of vscode.window.visibleTextEditors) {
                    const fsPath = editor?.document?.uri?.fsPath;
                    if (typeof fsPath === 'string' && fsPath.length > 0) {
                        paths.add(fsPath);
                    }
                }
            }

            return Array.from(paths);
        },
        getExtensionConfig: () =>
            vscode.workspace.getConfiguration('litCritic') as any,
    };

    // Build WorkflowDeps and instantiate the controller.
    const workflowDeps: WorkflowDeps = {
        getApiClient: () => ensureApiClient(),
        ensureServer: () => ensureServer(),
        getServerManager: () => serverManager,
        state,
        presenter,
        findingsTreeProvider,
        learningTreeProvider,
        knowledgeTreeProvider,
        knowledgeTreeView,
        diagnosticsProvider,
        analysisTreeProvider,
        ensureDiscussionPanel: () => ensureDiscussionPanel(),
        getDiscussionPanel: () => discussionPanel,
        runTrackedOperation: (profile, op) => runTrackedOperation(profile, op),
        detectProjectPath: () => detectProjectPath(),
        ui: uiPort,
        log: (msg) => operationTracker.log(msg),
    };
    controller = new WorkflowController(workflowDeps);

    // Wire knowledge review view callbacks now that controller is available
    knowledgeReviewPanel.onAction = async (action) => {
        const panel = knowledgeReviewPanel;
        if (!panel) {
            return;
        }

        const currentState = panel.getState();
        if (!currentState) {
            return;
        }

        const payload = knowledgeTreeProvider.getEntityPayload(currentState.category, currentState.entityKey)
            ?? await loadKnowledgeEntityPayload(currentState.category, currentState.entityKey, currentState.entityLabel, undefined, getKnowledgeHelperDeps());

        if (action.type === 'save-field') {
            if (!payload) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to save.');
                return;
            }
            const saved = await controller.editKnowledgeEntry({ ...payload, fieldName: action.fieldName, value: action.value });
            if (!saved) {
                void vscode.window.showErrorMessage(`lit-critic: Could not save ${action.fieldName} override.`);
                return;
            }
            await hydrateKnowledgeReviewPanel(currentState.category, currentState.entityKey, currentState.entityLabel, payload, {
                lastSavedAt: new Date().toISOString(),
            }, getKnowledgeHelperDeps());
            return;
        }

        if (action.type === 'reset-field') {
            if (!payload) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to reset.');
                return;
            }
            const reset = await controller.resetKnowledgeOverride({ ...payload, fieldName: action.fieldName });
            if (!reset) {
                void vscode.window.showErrorMessage(`lit-critic: Could not reset ${action.fieldName} override.`);
                return;
            }
            await hydrateKnowledgeReviewPanel(currentState.category, currentState.entityKey, currentState.entityLabel, payload, {
                lastSavedAt: new Date().toISOString(),
            }, getKnowledgeHelperDeps());
            return;
        }

        if (action.type === 'next-entity') {
            await vscode.commands.executeCommand('litCritic.nextKnowledgeEntity');
        }
        if (action.type === 'previous-entity') {
            await vscode.commands.executeCommand('litCritic.previousKnowledgeEntity');
        }

    };

    // Register all commands through the centralised registrar.
    // Must always happen so Command Palette entries are available.
    registerCommands(context.subscriptions, {
        cmdAnalyze: async () => {
            // D1: Stale inputs exist → auto-run knowledge update before analysis.
            // The author just wants feedback — the system does the right thing without prompting.
            if (stalenessRegistry.hasStaleInputs()) {
                await controller.cmdRefreshKnowledge();
            }
            await controller.cmdAnalyze();
            // Refresh scene projections so the inputs tree drops stale badges
            // for scenes that were just analysed.
            void scenesTreeProvider.refresh().catch(() => {});
            void recheckStaleness(getStalenessServiceDeps()).then((count) => updateKnowledgeStalenessMessage(count)).catch(() => {});
        },
        cmdSelectModel: controller.cmdSelectModel,
        cmdStopServer: controller.cmdStopServer,
        cmdShowLensFindings: (args: { scenePath: string; lens: string }) => {
            const sceneFindings = analysisTreeProvider.getFindingsForScene(args.scenePath);
            const filtered = sceneFindings.filter(
                (f) => f.lens.toLowerCase() === args.lens.toLowerCase(),
            );
            findingsTreeProvider.showLensFindings(filtered, args.scenePath, args.lens);
            // Auto-reveal the Findings tree view so the user sees the filtered results
            if (findingsTreeView) {
                void vscode.commands.executeCommand('litCritic.findings.focus');
            }
        },
        cmdShowSceneFindings: (args: { scenePath: string }) => {
            const sceneFindings = analysisTreeProvider.getFindingsForScene(args.scenePath);
            findingsTreeProvider.setFindings(sceneFindings, args.scenePath, 0);
            // Auto-reveal the Findings tree view so the user sees the results
            if (findingsTreeView) {
                void vscode.commands.executeCommand('litCritic.findings.focus');
            }
        },
        cmdResetAllKnowledge: controller.cmdResetAllKnowledge,
        cmdResetAllAnalysis: controller.cmdResetAllAnalysis,
        cmdDeleteSceneAnalysis: controller.cmdDeleteSceneAnalysis,
        cmdRefreshLearning: controller.cmdRefreshLearning,
        cmdExportLearning: controller.cmdExportLearning,
        cmdResetLearning: controller.cmdResetLearning,
        cmdDeleteLearningEntry: controller.cmdDeleteLearningEntry,
        cmdRefreshKnowledge: async () => {
            await controller.cmdRefreshKnowledge();
            void recheckStaleness(getStalenessServiceDeps()).then((count) => updateKnowledgeStalenessMessage(count)).catch(() => {});
        },
        cmdEditKnowledgeEntry: controller.cmdEditKnowledgeEntry,
        cmdResetKnowledgeOverride: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (target) {
                // Focus-first: make this entity current in the panel and tree before resetting
                if (target.payload) {
                    ensureKnowledgeReviewPanel().show(buildKnowledgeReviewPanelState(target.payload, {}));
                }
                await hydrateKnowledgeReviewPanel(target.category, target.entityKey, target.label, target.payload, undefined, getKnowledgeHelperDeps());
                const entityItem = knowledgeTreeProvider.getEntityItem(target.category, target.entityKey);
                if (entityItem) {
                    void knowledgeTreeView?.reveal(entityItem, { select: true, focus: false });
                }
            }
            await controller.cmdResetKnowledgeOverride(item);
        },
        cmdOpenKnowledgeReviewPanel: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (!target) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to review.');
                return;
            }

            if (target.payload) {
                ensureKnowledgeReviewPanel().show(buildKnowledgeReviewPanelState(target.payload, {}));
            }

            await hydrateKnowledgeReviewPanel(target.category, target.entityKey, target.label, target.payload, undefined, getKnowledgeHelperDeps());
        },
        cmdDeleteKnowledgeEntity: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (!target) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to delete.');
                return;
            }
            const { category, entityKey, label, payload } = target;

            // Focus-first: make this entity current in the panel and tree before confirming
            if (payload) {
                ensureKnowledgeReviewPanel().show(buildKnowledgeReviewPanelState(payload, {}));
            }
            await hydrateKnowledgeReviewPanel(category, entityKey, label, payload, undefined, getKnowledgeHelperDeps());
            const currentEntityItem = knowledgeTreeProvider.getEntityItem(category, entityKey);
            if (currentEntityItem) {
                void knowledgeTreeView?.reveal(currentEntityItem, { select: true, focus: false });
            }

            const confirmed = await vscode.window.showWarningMessage(
                `Delete entity '${entityKey}'? This cannot be undone. All overrides will also be removed.`,
                { modal: true },
                'Delete',
            );
            if (confirmed !== 'Delete') {
                return;
            }

            try {
                const projectPath = detectProjectPath();
                if (!projectPath) {
                    void vscode.window.showErrorMessage('lit-critic: Could not detect project directory.');
                    return;
                }
                await ensureServer();
                // Capture next entity before deletion (while the tree still contains the entity).
                // Use getAdjacentEntityPayload(next) for forward navigation; fall back to
                // getFirstEntityPayload() after refresh to wrap around to the start.
                const nextBeforeDeletion = knowledgeTreeProvider.getAdjacentEntityPayload(category, entityKey, 'next');
                await ensureApiClient().deleteKnowledgeEntity(category, entityKey, projectPath);
                await knowledgeTreeProvider.refresh();
                void vscode.window.showInformationMessage("Entity deleted. Run 'Refresh Knowledge' to allow the AI to re-extract it.");
                // Navigate to next, or wrap to first if we were at the last entry
                const nextPayload = nextBeforeDeletion ?? knowledgeTreeProvider.getFirstEntityPayload();
                if (nextPayload) {
                    await hydrateKnowledgeReviewPanel(nextPayload.category, nextPayload.entityKey, nextPayload.label, nextPayload, undefined, getKnowledgeHelperDeps());
                    const nextEntityItem = knowledgeTreeProvider.getEntityItem(nextPayload.category, nextPayload.entityKey);
                    if (nextEntityItem) {
                        void knowledgeTreeView?.reveal(nextEntityItem, { select: true, focus: false });
                    }
                } else {
                    ensureKnowledgeReviewPanel().close();
                }
            } catch (err) {
                const detail = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`lit-critic: Delete failed: ${detail}`);
            }
        },
        cmdNextKnowledgeEntity: async () => {
            await navigateKnowledgeReviewPanel('next', getKnowledgeHelperDeps());
        },
        cmdPreviousKnowledgeEntity: async () => {
            await navigateKnowledgeReviewPanel('previous', getKnowledgeHelperDeps());
        },
        cmdKeepFlaggedEntity: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (!target) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry.');
                return;
            }
            const { category, entityKey } = target;
            const projectPath = detectProjectPath();
            if (!projectPath) {
                void vscode.window.showErrorMessage('lit-critic: Could not detect project directory.');
                return;
            }
            try {
                await ensureServer();
                const choice = await vscode.window.showInformationMessage(
                    `Keep '${entityKey}' and dismiss the review flag?`,
                    'Keep & Lock',
                    'Keep Only',
                    'Cancel',
                );
                if (!choice || choice === 'Cancel') { return; }
                if (choice === 'Keep & Lock') {
                    await ensureApiClient().lockEntity(category, entityKey, projectPath);
                }
                await ensureApiClient().dismissReviewFlag(category, entityKey, projectPath);
                knowledgeTreeProvider.clearEntityFlag(category as KnowledgeCategoryKey, entityKey);
                await knowledgeTreeProvider.refresh();
                void vscode.window.showInformationMessage(
                    `lit-critic: '${entityKey}' kept${choice === 'Keep & Lock' ? ' and locked' : ''}.`,
                );
            } catch (err) {
                const detail = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`lit-critic: Keep failed: ${detail}`);
            }
        },
        cmdDeleteFlaggedEntity: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (!target) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to delete.');
                return;
            }
            const { category, entityKey } = target;
            const projectPath = detectProjectPath();
            if (!projectPath) {
                void vscode.window.showErrorMessage('lit-critic: Could not detect project directory.');
                return;
            }
            const confirmed = await vscode.window.showWarningMessage(
                `Delete entity '${entityKey}'? This cannot be undone. All overrides will also be removed.`,
                { modal: true },
                'Delete',
            );
            if (confirmed !== 'Delete') { return; }
            try {
                await ensureServer();
                await ensureApiClient().deleteKnowledgeEntity(category, entityKey, projectPath);
                knowledgeTreeProvider.clearEntityFlag(category as KnowledgeCategoryKey, entityKey);
                await knowledgeTreeProvider.refresh();
                void vscode.window.showInformationMessage(`lit-critic: '${entityKey}' deleted.`);
            } catch (err) {
                const detail = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`lit-critic: Delete failed: ${detail}`);
            }
        },
        cmdToggleEntityLock: async (item?: unknown) => {
            const target = resolveKnowledgeEntityReviewTarget(item, getKnowledgeHelperDeps());
            if (!target) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine knowledge entry to lock/unlock.');
                return;
            }
            const { category, entityKey, payload } = target;
            const isLocked = payload?.locked ?? false;
            const projectPath = detectProjectPath();
            if (!projectPath) {
                void vscode.window.showErrorMessage('lit-critic: Could not detect project directory.');
                return;
            }
            try {
                await ensureServer();
                if (isLocked) {
                    await ensureApiClient().unlockEntity(category, entityKey, projectPath);
                    void vscode.window.showInformationMessage(`lit-critic: '${entityKey}' unlocked.`);
                } else {
                    await ensureApiClient().lockEntity(category, entityKey, projectPath);
                    void vscode.window.showInformationMessage(`lit-critic: '${entityKey}' locked — the LLM will not update it.`);
                }
                await knowledgeTreeProvider.refresh();

                // Refresh the review panel if it is currently showing this entity
                const panelState = ensureKnowledgeReviewPanel().getState();
                if (panelState?.category === category && panelState?.entityKey === entityKey) {
                    await hydrateKnowledgeReviewPanel(category, entityKey, target.label, target.payload, undefined, getKnowledgeHelperDeps());
                }
            } catch (err) {
                const detail = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`lit-critic: Toggle lock failed: ${detail}`);
            }
        },
        // Explain actions — one-shot LLM explanation for a finding (no state change)
        cmdExplainFindingQuick: async (findingNumber: number) => {
            await runExplainFinding(findingNumber, 'quick');
        },
        cmdExplainFindingDeep: async (findingNumber: number) => {
            await runExplainFinding(findingNumber, 'deep');
        },
    });

    // Findings navigation — triggered by clicking a FindingTreeItem.
    // Also shows the finding in the Findings Review (Discussion) panel,
    // mirroring how knowledge items show in the Knowledge Review panel.
    context.subscriptions.push(
        vscode.commands.registerCommand('litCritic.navigateToFinding', (finding: Finding) => {
            navigateToFindingLine(finding);
            const allFindings = findingsTreeProvider.getAllFindings();
            const idx = allFindings.findIndex(f => f.number === finding.number);
            const current = idx >= 0 ? idx + 1 : 1;
            const total = allFindings.length;
            ensureDiscussionPanel().show(finding, current, total);
        }),
    );

    // Register the explain code action provider so "Explain (Quick/Deep)" appear
    // in the lightbulb menu when the cursor is on a lit-critic diagnostic squiggle.
    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            { scheme: 'file' },
            new ExplainCodeActionProvider(),
            { providedCodeActionKinds: ExplainCodeActionProvider.providedCodeActionKinds },
        ),
    );

    // Lazily created when the first explanation is requested; disposed with the extension.
    let explainOutputChannel: vscode.OutputChannel | undefined;

    /**
     * Shared handler for litCritic.explainFindingQuick and litCritic.explainFindingDeep.
     * Fetches a one-shot LLM explanation and displays it in the dedicated output channel.
     */
    async function runExplainFinding(findingNumber: number, depth: 'quick' | 'deep'): Promise<void> {
        const projectPath = detectProjectPath();
        if (!projectPath) {
            void vscode.window.showErrorMessage('lit-critic: Could not detect project directory.');
            return;
        }

        const finding = findingsTreeProvider.getFinding(findingNumber);
        if (!finding) {
            void vscode.window.showErrorMessage(
                `lit-critic: Finding #${findingNumber} not found in current snapshot. Run analysis first.`,
            );
            return;
        }

        // Lazily create the output channel so it only appears when first used.
        if (!explainOutputChannel) {
            explainOutputChannel = vscode.window.createOutputChannel('lit-critic: Explain');
            context.subscriptions.push(explainOutputChannel);
        }

        const depthLabel = depth === 'quick' ? 'Quick' : 'Deep';
        explainOutputChannel.appendLine(`\n${'='.repeat(60)}`);
        explainOutputChannel.appendLine(
            `Finding #${findingNumber} [Explain ${depthLabel}] — ${finding.lens} · ${finding.severity}`,
        );
        explainOutputChannel.appendLine(finding.evidence);
        explainOutputChannel.appendLine('─'.repeat(60));
        explainOutputChannel.appendLine('Requesting explanation…');
        // Reveal channel without stealing focus from the editor
        explainOutputChannel.show(true);

        try {
            await ensureServer();
            // Read the active document text for context; fall back to empty string if no editor open.
            const sceneText = vscode.window.activeTextEditor?.document.getText() ?? '';
            const result = await ensureApiClient().explainFinding(
                findingNumber, finding, sceneText, depth, projectPath,
            );
            explainOutputChannel.appendLine('');
            explainOutputChannel.appendLine(result.explanation);
            explainOutputChannel.appendLine('');
            explainOutputChannel.appendLine(`(Model: ${result.model_used})`);
        } catch (err) {
            const detail = err instanceof Error ? err.message : String(err);
            explainOutputChannel.appendLine(`\n⚠️ Explanation failed: ${detail}`);
            void vscode.window.showErrorMessage(`lit-critic: Explain failed: ${detail}`);
        }
    }

    context.subscriptions.push(
        vscode.commands.registerCommand('litCritic.refreshIndexes', async () => {
            await runTrackedOperation(
                {
                    id: 'refresh-indexes-tree',
                    title: 'Refreshing indexes',
                    statusMessage: 'Refreshing indexes...',
                },
                async () => {
                    const projectPath = detectProjectPath();
                    if (!projectPath) {
                        return;
                    }

                    await ensureServer();
                    const client = ensureApiClient();
                    const maybeRefreshIndexes = (client as ApiClient & {
                        refreshIndexes?: (projectPath: string) => Promise<unknown>;
                    }).refreshIndexes;
                    if (typeof maybeRefreshIndexes === 'function') {
                        await maybeRefreshIndexes.call(client, projectPath).catch(() => {});
                    }
                    knowledgeTreeProvider.setApiClient(client);
                    knowledgeTreeProvider.setProjectPath(projectPath);
                    await knowledgeTreeProvider.refresh();
                },
            );
        }),
        vscode.commands.registerCommand('litCritic.purgeOrphanedSceneRefs', async () => {
            const projectPath = detectProjectPath();
            if (!projectPath) {
                void vscode.window.showWarningMessage('No project detected. Open a lit-critic project first.');
                return;
            }
            const confirmed = await vscode.window.showWarningMessage(
                'Clean up stale scene references? This removes DB rows for scene files that no longer exist on disk.',
                { modal: true },
                'Clean Up',
            );
            if (confirmed !== 'Clean Up') { return; }
            try {
                await ensureServer();
                const client = ensureApiClient();
                const result = await client.purgeOrphanedSceneRefs(projectPath);
                const totalRemoved = Object.values(result).reduce((sum: number, n) => sum + (n as number), 0);
                await client.refreshScenes(projectPath).catch(() => {});
                scenesTreeProvider.setApiClient(client);
                scenesTreeProvider.setProjectPath(projectPath);
                await scenesTreeProvider.refresh().catch(() => {});
                knowledgeTreeProvider.setApiClient(client);
                knowledgeTreeProvider.setProjectPath(projectPath);
                await knowledgeTreeProvider.refresh().catch(() => {});
                void vscode.window.showInformationMessage(
                    totalRemoved === 0
                        ? 'lit-critic: No stale scene references found.'
                        : `lit-critic: Removed ${totalRemoved} stale scene reference${totalRemoved === 1 ? '' : 's'}.`,
                );
            } catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`lit-critic: Purge failed: ${msg}`);
            }
        }),
        vscode.commands.registerCommand('litCritic.renameScene', async (item?: unknown) => {
            const projectPath = detectProjectPath();
            if (!projectPath) {
                void vscode.window.showWarningMessage('No project detected. Open a lit-critic project first.');
                return;
            }
            const sceneItem = item instanceof SceneTreeItem ? item : undefined;
            if (!sceneItem) {
                void vscode.window.showErrorMessage('lit-critic: Could not determine scene to rename. Right-click a scene in the Inputs tree.');
                return;
            }
            const oldPath = sceneItem.scene.scene_path;
            const oldBasename = path.basename(oldPath);
            const oldDir = oldPath.includes('/') ? oldPath.substring(0, oldPath.lastIndexOf('/') + 1) : '';
            const newName = await vscode.window.showInputBox({
                title: 'Rename Scene',
                prompt: `New filename for "${oldBasename}"`,
                value: oldBasename,
                validateInput: (v) => (!v.trim() ? 'Filename cannot be empty.' : null),
            });
            if (!newName || !newName.trim()) {
                return;
            }
            const newPath = oldDir + newName.trim();
            // Suppress the file system watcher while the rename is in flight so
            // the disk-level delete+create events don't trigger a second refresh.
            sceneWatcherSuppressed = true;
            let renameError: string | undefined;
            try {
                await vscode.window.withProgress(
                    { location: vscode.ProgressLocation.Notification, title: 'lit-critic', cancellable: false },
                    async (progress) => {
                        progress.report({ message: `Renaming scene to "${newName.trim()}"…` });
                        await ensureServer();
                        const client = ensureApiClient();
                        await client.renameScene(oldPath, newPath, projectPath);
                        progress.report({ message: 'Updating scene list…' });
                        await client.refreshScenes(projectPath).catch(() => {});
                        scenesTreeProvider.setApiClient(client);
                        scenesTreeProvider.setProjectPath(projectPath);
                        await scenesTreeProvider.refresh();
                    },
                );
            } catch (err) {
                renameError = err instanceof Error ? err.message : String(err);
            } finally {
                sceneWatcherSuppressed = false;
            }
            if (renameError) {
                void vscode.window.showErrorMessage(`lit-critic: Rename failed: ${renameError}`);
            } else {
                void vscode.window.showInformationMessage(`lit-critic: Scene renamed to "${newName.trim()}".`);
            }


        }),
    );

    const config = vscode.workspace.getConfiguration('litCritic');
    const autoStartServer = config.get<boolean>('autoStartServer', true);

    // Apply workspace-scoped problem-decoration preferences (optional).
    await applyWorkspaceProblemDecorationPreferences();

    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((event) => {
            if (
                event.affectsConfiguration('litCritic.disableProblemDecorationColors')
                || event.affectsConfiguration('litCritic.disableProblemDecorationBadges')
            ) {
                void applyWorkspaceProblemDecorationPreferences();
            }

            if (event.affectsConfiguration('litCritic.knowledgeReviewPassTrigger')) {
                void (async () => {
                    try {
                        if (serverManager?.isRunning) {
                            const value = vscode.workspace.getConfiguration('litCritic')
                                .get<string>('knowledgeReviewPassTrigger', 'always');
                            await (ensureApiClient() as any).request('POST', '/api/knowledge/review-pass', { value }).catch(() => {});
                        }
                    } catch {
                        // Non-fatal
                    }
                })();
            }

            if (
                event.affectsConfiguration('litCritic.sceneFolder')
                || event.affectsConfiguration('litCritic.sceneExtensions')
            ) {
                void (async () => {
                    try {
                        if (serverManager?.isRunning) {
                            const client = ensureApiClient();
                            await syncSceneDiscoverySettingsToServer(client);
                            const projectPath = detectProjectPath();
                            if (projectPath) {
                                await client.refreshScenes(projectPath).catch(() => {});
                                scenesTreeProvider.setApiClient(client);
                                scenesTreeProvider.setProjectPath(projectPath);
                                await scenesTreeProvider.refresh().catch(() => {});
                            }
                            // Re-create file watchers with the new folder/extension config.
                            setupSceneFileWatcher();
                        }
                    } catch {
                        // Non-fatal: backend may be temporarily unavailable.
                    }
                })();
            }
        })
    );

    // Debounced save listener: re-check staleness 2s after a scene file is saved.
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument((document) => {
            const savedPath = document.uri.fsPath;
            const { sceneFolder, sceneExtensions } = getSceneDiscoverySettingsFromConfig();
            const projectPath = detectProjectPath();
            if (!projectPath) { return; }

            // Only react to files inside the scene folder with a matching extension.
            const normalizedSaved = savedPath.replace(/\\/g, '/');
            const normalizedProject = projectPath.replace(/\\/g, '/');
            const inSceneFolder = normalizedSaved.includes(`/${sceneFolder}/`)
                || normalizedSaved.startsWith(`${normalizedProject}/${sceneFolder}/`);
            const hasSceneExt = sceneExtensions.some((ext) => normalizedSaved.endsWith(`.${ext}`));
            if (!inSceneFolder || !hasSceneExt) { return; }

            // Client-side guard: if this file is already known-stale, a further edit
            // cannot change the stale count or the set of affected knowledge/sessions.
            // Skip the API call entirely to avoid redundant network traffic.
            if (stalenessRegistry.isInputStale(savedPath)) {
                operationTracker.log(`[Watcher] Document saved (already stale, skipping staleness recheck): ${savedPath}`);
                return;
            }

            operationTracker.log(`[Watcher] Document saved: ${savedPath}`);

            // Debounce: uses the shared stalenessDebounceTimer so that the fs watcher
            // firing on the same save event resets this timer rather than adding a
            // second call — resulting in exactly one API call per save/edit burst.
            if (stalenessDebounceTimer !== undefined) {
                clearTimeout(stalenessDebounceTimer);
            }
            stalenessDebounceTimer = setTimeout(() => {
                stalenessDebounceTimer = undefined;
                void recheckStaleness(getStalenessServiceDeps())
                    .then((count) => {
                        updateKnowledgeStalenessMessage(count);
                        // D2: autoUpdateOnSave='knowledge' — automatically run knowledge extraction
                        // when stale scenes are detected on save. 'full' (auto-analyze) is
                        // intentionally excluded from initial scope (see Design Decision D2).
                        if (count > 0) {
                            const autoUpdate = vscode.workspace.getConfiguration('litCritic')
                                .get<string>('autoUpdateOnSave', 'off');
                            if (autoUpdate === 'knowledge') {
                                void controller.cmdRefreshKnowledge();
                            }
                        }
                    })
                    .catch(() => {});
            }, 2000);
        }),
    );

    let repoRoot = findRepoRoot();

    // If findRepoRoot() succeeded, promote the resolved path to the Global (User)
    // scope so it persists regardless of which workspace is open on next startup.
    // This silently fixes the case where the user previously set repoPath at
    // Workspace scope (which doesn't follow them to other workspaces).
    if (repoRoot) {
        const _repoPathCfg = vscode.workspace.getConfiguration('litCritic');
        const _inspectFn = (_repoPathCfg as any).inspect;
        const currentGlobal: string | undefined = typeof _inspectFn === 'function'
            ? (_inspectFn.call(_repoPathCfg, 'repoPath') as any)?.globalValue?.trim()
            : undefined;
        if (!currentGlobal || currentGlobal !== repoRoot) {
            // Clear workspace-scoped override first so the global value won't be shadowed.
            await vscode.workspace.getConfiguration('litCritic')
                .update('repoPath', undefined, vscode.ConfigurationTarget.Workspace)
                .then(undefined, () => {});
            await vscode.workspace.getConfiguration('litCritic').update(
                'repoPath', repoRoot, vscode.ConfigurationTarget.Global,
            ).then(undefined, () => { /* non-fatal — best-effort promotion */ });
        }
    }

    if (!repoRoot && autoStartServer) {
        const configuredRepoPath = config.get<string>('repoPath', '').trim();
        const configuredValidation = validateRepoPath(configuredRepoPath || undefined);

        // Trigger recovery even when repoPath is completely empty (first launch on
        // a new PC), not only when it is set but invalid.
        if (!configuredValidation.ok) {
            try {
                repoRoot = await ensureRepoRootWithRecovery();
            } catch {
                repoRoot = undefined;
            }
        }
    }

    if (repoRoot) {
        serverManager = new ServerManager(repoRoot);
        apiClient = new ApiClient(serverManager.baseUrl);
        context.subscriptions.push(serverManager);

        if (autoStartServer) {
            try {
                // Use a single progress notification that spans the full startup
                // sequence — server launch + config sync + sidebar population —
                // so the notification is only dismissed when the extension is
                // truly ready for use.
                presenter.setAnalyzing('Starting server...');
                await vscode.window.withProgress(
                    {
                        location: vscode.ProgressLocation.Notification,
                        title: 'lit-critic',
                        cancellable: false,
                    },
                    async (progress) => {
                        const stageMessage: Record<'checking' | 'launching' | 'waiting' | 'ready', string> = {
                            checking: 'Checking for a running backend...',
                            launching: 'Launching backend process...',
                            waiting: 'Waiting for server readiness...',
                            ready: 'Server ready — loading project data...',
                        };

                        progress.report({ message: stageMessage.checking });
                        await serverManager!.start((stage) => {
                            progress.report({ message: stageMessage[stage] });
                        });

                        await ensureApiClient().updateRepoPath(repoRoot!).catch(() => {});
                        await syncSceneDiscoverySettingsToServer(ensureApiClient()).catch(() => {});

                        progress.report({ message: 'Loading project data...' });
                        await autoLoadSidebar();

                    },
                );

                // Re-check staleness to ensure initial UI correctly reflects DB state.
                await recheckStaleness(getStalenessServiceDeps())
                    .then((count) => updateKnowledgeStalenessMessage(count))
                    .catch(() => {});

                // Only mark ready and signal running AFTER all startup work is done.
                presenter.setReady();
                void vscode.commands.executeCommand('setContext', 'litCritic.serverRunning', true);

                await revealLitCriticActivityContainerIfProjectDetected(repoRoot);
                await tryMoveReviewContainerToSecondarySidebar(context);
            } catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                presenter.setError(msg);
            }
        }
    }
}

export function deactivate(): void {
    extensionContext = undefined;
    discussionPanel?.dispose();
    knowledgeReviewPanel?.dispose();
    serverManager?.stop();
}

async function applyWorkspaceProblemDecorationPreferences(): Promise<void> {
    const config = vscode.workspace.getConfiguration('litCritic');
    const disableColors = config.get<boolean>('disableProblemDecorationColors', false);
    const disableBadges = config.get<boolean>('disableProblemDecorationBadges', false);

    const workbenchConfig = vscode.workspace.getConfiguration('workbench');

    await workbenchConfig.update(
        'editor.decorations.colors',
        disableColors ? false : undefined,
        vscode.ConfigurationTarget.Workspace,
    );

    await workbenchConfig.update(
        'editor.decorations.badges',
        disableBadges ? false : undefined,
        vscode.ConfigurationTarget.Workspace,
    );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findRepoRoot(): string | undefined {
    const config = vscode.workspace.getConfiguration('litCritic');
    const configured = config.get<string>('repoPath', '').trim();
    if (configured) {
        const validation = validateRepoPath(configured);
        if (validation.ok) {
            return validation.path || configured;
        }
    }
    return findRepoRootFromWorkspace();
}

function findRepoRootFromWorkspace(): string | undefined {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        return undefined;
    }

    for (const folder of workspaceFolders) {
        let dir = folder.uri.fsPath;
        for (let i = 0; i < 5; i++) {
            const marker = path.join(dir, REPO_MARKER);
            try {
                if (fs.existsSync(marker)) {
                    return dir;
                }
            } catch {
                // ignore
            }
            const parent = path.dirname(dir);
            if (parent === dir) { break; }
            dir = parent;
        }
    }

    return undefined;
}

async function startServerWithBusyUi(repoRoot: string): Promise<void> {
    presenter.setAnalyzing('Starting server...');
    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: 'lit-critic: Starting server',
            cancellable: false,
        },
        async (progress) => {
            const stageMessage: Record<'checking' | 'launching' | 'waiting' | 'ready', string> = {
                checking: 'Checking for an existing backend instance...',
                launching: 'Launching lit-critic backend process...',
                waiting: 'Waiting for backend readiness check...',
                ready: 'Backend is ready.',
            };

            progress.report({ message: stageMessage.checking });
            await serverManager!.start((stage) => {
                progress.report({ message: stageMessage[stage] });
            });

            progress.report({ message: 'Finalizing extension startup...' });
            await ensureApiClient().updateRepoPath(repoRoot).catch(() => {
                // Non-fatal
            });
        },
    );

    presenter.setReady();
    // Signal to the secondary sidebar views that the server is running.
    void vscode.commands.executeCommand('setContext', 'litCritic.serverRunning', true);
}

async function ensureRepoRootWithRecovery(): Promise<string> {
    const config = vscode.workspace.getConfiguration('litCritic');
    const configured = config.get<string>('repoPath', '').trim();
    const configuredValidation = validateRepoPath(configured || undefined);
    if (configuredValidation.ok) {
        return configuredValidation.path || configured;
    }

    const workspaceRoot = findRepoRootFromWorkspace();
    if (workspaceRoot) {
        const workspaceValidation = validateRepoPath(workspaceRoot);
        if (workspaceValidation.ok) {
            return workspaceValidation.path || workspaceRoot;
        }
    }

    let currentMessage = configured
        ? configuredValidation.message
        : `Could not locate lit-critic installation (${REPO_MARKER}).`;

    while (true) {
        const action = await vscode.window.showErrorMessage(
            `lit-critic startup preflight failed. ${currentMessage}`,
            { modal: true },
            'Select Folder…',
            'Open Settings',
        );

        if (!action) {
            // User dismissed via X or Escape — cancel startup.
            throw new Error('Repository path setup cancelled.');
        }

    if (action === 'Open Settings') {
            await vscode.commands.executeCommand('workbench.action.openSettings', 'litCritic.repoPath');
            // openSettings() resolves immediately when the tab opens, not when the user saves.
            // Show a follow-up modal so the user can set the value and confirm before we read it back.
            // No "Cancel" button here — dismissing via X loops back to the main recovery dialog.
            const confirmed = await vscode.window.showInformationMessage(
                'Set `litCritic.repoPath` in User settings, then click "Check Again".',
                { modal: true },
                'Check Again',
            );
            if (!confirmed) {
                // User dismissed the follow-up — go back to the main recovery dialog.
                continue;
            }
            // Read globalValue specifically: .get() returns the merged (workspace-wins) value,
            // which would still be wrong if workspace scope has an old override.
            const inspected = vscode.workspace.getConfiguration('litCritic').inspect<string>('repoPath');
            const candidate = (inspected?.globalValue ?? '').trim();
            const validation = validateRepoPath(candidate || undefined);
            if (validation.ok) {
                const normalized = validation.path || candidate;
                // Clear workspace-scoped override so the global value is not shadowed on next startup.
                await vscode.workspace.getConfiguration('litCritic')
                    .update('repoPath', undefined, vscode.ConfigurationTarget.Workspace)
                    .then(undefined, () => {});
                await vscode.workspace.getConfiguration('litCritic').update(
                    'repoPath', normalized, vscode.ConfigurationTarget.Global,
                );
                return normalized;
            }
            currentMessage = validation.message || 'Path set in User settings is not valid.';
            continue;
        }

        const picked = await vscode.window.showOpenDialog({
            canSelectFiles: false,
            canSelectFolders: true,
            canSelectMany: false,
            openLabel: 'Use this folder',
        });
        if (!picked || picked.length === 0) {
            currentMessage = `No folder selected. Please choose a directory containing ${REPO_MARKER}.`;
            continue;
        }

        const selected = picked[0].fsPath;
        const validation = validateRepoPath(selected);
        if (!validation.ok) {
            currentMessage = validation.message;
            continue;
        }

        const normalized = validation.path || selected;
        // Clear workspace-scoped override so the global value is not shadowed on next startup.
        await vscode.workspace.getConfiguration('litCritic')
            .update('repoPath', undefined, vscode.ConfigurationTarget.Workspace)
            .then(undefined, () => {});
        await vscode.workspace.getConfiguration('litCritic').update(
            'repoPath',
            normalized,
            vscode.ConfigurationTarget.Global,
        );
        return normalized;
    }
}

function detectProjectPath(): string | undefined {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders) {
        for (const folder of workspaceFolders) {
            const canonPath = path.join(folder.uri.fsPath, 'CANON.md');
            if (fs.existsSync(canonPath)) {
                return folder.uri.fsPath;
            }
        }
    }

    // Fallback: older or custom projects may not use CANON.md but still have
    // a valid repo root configured/discovered by startup preflight.
    const repoRoot = serverManager?.repoRoot ?? findRepoRoot();
    if (repoRoot) {
        return repoRoot;
    }

    return undefined;
}

/**
 * Hydrate the Analysis tree on startup by fetching the latest session per scene
 * from the backend and mapping findings into the analysisTreeProvider.
 * Also seeds diagnostics from the hydrated findings.
 */
async function hydrateAnalysisTree(client: ApiClient, projectPath: string): Promise<void> {
    const response = await client.getCurrentFindings(projectPath);
    const sceneEntries = Object.entries(response.scenes);
    if (sceneEntries.length === 0) {
        return;
    }

    const allFindings: Finding[] = [];

    for (const [scenePath, sceneData] of sceneEntries) {
        if (!sceneData.findings || sceneData.findings.length === 0) { continue; }

        const sceneFindings: Finding[] = sceneData.findings.map((f) => ({
            number: f.number,
            severity: f.severity as 'critical' | 'major' | 'minor',
            lens: f.lens,
            location: f.location,
            line_start: f.line_start,
            line_end: f.line_end,
            scene_path: scenePath,
            evidence: f.evidence,
            impact: f.impact ?? '',
            options: f.options ?? [],
            flagged_by: f.flagged_by ?? [],
            ambiguity_type: null,
            stale: false,
            status: f.status || 'active',
        }));

        analysisTreeProvider.setFindings(scenePath, sceneFindings);
        allFindings.push(...sceneFindings);
    }

    // Seed diagnostics from all hydrated findings.
    if (allFindings.length > 0) {
        diagnosticsProvider.updateFromFindings(allFindings);
    }
}

async function autoLoadSidebar(): Promise<void> {
    await runTrackedOperation(
        {
            id: 'auto-load-sidebar',
            title: 'Loading sessions and learning data',
            statusMessage: 'Loading sessions and learning data...',
            progressLocation: vscode.ProgressLocation.Window,
        },
        async () => {
            const projectPath = detectProjectPath();
            debugScenesTrace('autoLoadSidebar.detectProjectPath', { projectPath });
            if (!projectPath) {
                return;
            }

            // Detect staleness passively — mark stale items in the sidebar trees so the
            // user can see what changed, then let them decide when to run Refresh Knowledge.
            // This mirrors the post-startup "Check for Changes" behavior: we never run an
            // automatic LLM extraction or DB write on startup without an explicit user action.
            const startupStaleCount = await recheckStaleness(getStalenessServiceDeps()).catch(() => 0);
            updateKnowledgeStalenessMessage(startupStaleCount);

            const client = ensureApiClient();
            scenesTreeProvider.setApiClient(client);
            scenesTreeProvider.setProjectPath(projectPath);
            await scenesTreeProvider.refresh().catch((error) => {
                debugScenesTrace('autoLoadSidebar.scenesTreeProvider.refresh error', {
                    projectPath,
                    error: error instanceof Error ? error.message : String(error),
                });
            });

            knowledgeTreeProvider.setApiClient(client);
            knowledgeTreeProvider.setProjectPath(projectPath);
            await knowledgeTreeProvider.refresh().catch(() => {});

            // Hydrate the Analysis tree: list sessions, pick latest per scene,
            // fetch detail for each, and feed findings to analysisTreeProvider.
            await hydrateAnalysisTree(client, projectPath).catch(() => {});

            learningTreeProvider.setApiClient(client);
            learningTreeProvider.setProjectPath(projectPath);
            await learningTreeProvider.refresh().catch(() => {});

            // Set up the file system watcher now that the server is ready and
            // the project path is known. The watcher auto-refreshes the Inputs
            // tree and re-checks staleness when scene files are created/deleted/changed.
            setupSceneFileWatcher();
        },
    );
}

/**
 * On first activation, attempt to move the `lit-critic-review` view container
 * to the Secondary Side Bar. Best-effort: if the command fails or is unavailable,
 * the container stays in the primary sidebar and the user can move it manually
 * via right-click → "Move to Secondary Side Bar".
 */
async function tryMoveReviewContainerToSecondarySidebar(context: vscode.ExtensionContext): Promise<void> {
    const flagKey = 'litCritic.reviewSidebarMoved';
    if (context.globalState.get<boolean>(flagKey)) {
        return; // Already attempted on a previous activation
    }

    try {
        // Open the review container so VS Code knows it exists
        await vscode.commands.executeCommand('workbench.view.extension.lit-critic-review');
        // Move the Discussion view to the Secondary Side Bar (aux bar)
        await vscode.commands.executeCommand('workbench.action.moveView', {
            viewId: 'litCritic.discussionView',
            destGroupOrContainerId: 'workbench.view.auxiliarybar',
        });
        await context.globalState.update(flagKey, true);
    } catch {
        // Non-fatal. User can right-click the container icon and choose
        // "Move to Secondary Side Bar" to place it manually.
    }
}

async function revealLitCriticActivityContainerIfProjectDetected(repoRootHint?: string): Promise<void> {
    const projectPath = detectProjectPath() || repoRootHint;
    if (!projectPath) {
        return;
    }

    try {
        await vscode.commands.executeCommand('workbench.view.extension.lit-critic');
    } catch {
        // Non-fatal
    }
}

async function ensureServer(): Promise<void> {

    try {
        // Fast path: server is already running — just sync repo path.
        if (serverManager?.isRunning) {
            const repoRoot = serverManager.repoRoot;
            if (repoRoot) {
                await ensureApiClient().updateRepoPath(repoRoot).catch(() => {});
            }
            return;
        }

        // Try quick, non-interactive repo-root discovery first.
        // Falls back to interactive recovery only when discovery fails.
        const repoRoot = findRepoRoot()
            ?? serverManager?.repoRoot
            ?? await ensureRepoRootWithRecovery();

        if (!serverManager) {
            serverManager = new ServerManager(repoRoot);
            apiClient = new ApiClient(serverManager.baseUrl);
        } else {
            const existingRoot = serverManager.repoRoot;
            if (existingRoot && existingRoot !== repoRoot) {
                serverManager.dispose();
                serverManager = new ServerManager(repoRoot);
                apiClient = new ApiClient(serverManager.baseUrl);
            }
        }

        await startServerWithBusyUi(repoRoot);
        await syncSceneDiscoverySettingsToServer(ensureApiClient()).catch(() => {});
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        presenter.setError(msg);
        throw new Error(`Could not start lit-critic server: ${msg}`);
    }
}

function ensureApiClient(): ApiClient {
    if (!apiClient) {
        if (!serverManager) {
            throw new Error('Server not initialized. Run "lit-critic: Analyze" first.');
        }
        apiClient = new ApiClient(serverManager.baseUrl);
    }
    return apiClient;
}

function ensureDiscussionPanel(): DiscussionViewProvider {
    return discussionPanel;
}

function ensureKnowledgeReviewPanel(): KnowledgeReviewViewProvider {
    // onAction is wired in activate() after controller is created.
    // If called before that (e.g. navigateKnowledgeReviewPanel), the panel
    // singleton is already created; onAction will be set shortly after.
    return knowledgeReviewPanel!;
}

// ---------------------------------------------------------------------------
// Staleness service deps factory
// ---------------------------------------------------------------------------

function getStalenessServiceDeps(): StalenessServiceDeps {
    return {
        detectProjectPath,
        getServerManager: () => serverManager,
        ensureApiClient,
        stalenessRegistry,
        scenesTreeProvider,
        knowledgeTreeProvider,
        log: (msg) => operationTracker?.log(msg),
    };
}

// ---------------------------------------------------------------------------
// Knowledge staleness message helper
// ---------------------------------------------------------------------------

function updateKnowledgeStalenessMessage(count: number): void {
    if (!knowledgeTreeView) { return; }
    knowledgeTreeView.badge = count > 0
        ? { value: count, tooltip: `${count} scene${count === 1 ? '' : 's'} changed — run "Update (AI)"` }
        : undefined;
}

// ---------------------------------------------------------------------------
// Scene file watcher — auto-refreshes Inputs tree and staleness on fs changes
// ---------------------------------------------------------------------------

function setupSceneFileWatcher(): vscode.Disposable[] {
    // Dispose any previously created watchers before creating new ones.
    for (const d of sceneFileWatcherDisposables) {
        d.dispose();
    }
    sceneFileWatcherDisposables = [];

    const projectPath = detectProjectPath();
    if (!projectPath) {
        return [];
    }

    const { sceneFolder, sceneExtensions } = getSceneDiscoverySettingsFromConfig();

    // Shared helper: debounce and schedule a staleness re-check.
    const scheduleStalenessCheck = () => {
        if (stalenessDebounceTimer !== undefined) {
            clearTimeout(stalenessDebounceTimer);
        }
        stalenessDebounceTimer = setTimeout(() => {
            stalenessDebounceTimer = undefined;
            void recheckStaleness(getStalenessServiceDeps())
                .then((count) => updateKnowledgeStalenessMessage(count))
                .catch(() => {});
        }, 2000);
    };

    // onChange: file content changed. Skip if already known-stale — re-editing
    // a stale file can't change the count or the affected knowledge/sessions.
    // The shared timer also coalesces this with the onDidSaveTextDocument handler
    // so that a save (which triggers both paths) produces exactly one API call.
    const handleChange = (uri: vscode.Uri) => {
        if (sceneWatcherSuppressed) {
            operationTracker.log(`[Watcher] Suppressed (rename in progress): ${uri.fsPath}`);
            return;
        }
        if (stalenessRegistry.isInputStale(uri.fsPath)) {
            operationTracker.log(`[Watcher] Skipped (already stale): ${uri.fsPath}`);
            return;
        }
        operationTracker.log(`[Watcher] File changed: ${uri.fsPath}`);
        scheduleStalenessCheck();
    };

    // onCreate / onDelete: file set changed — always recheck regardless of
    // current stale state, since a new or removed file may shift staleness.
    const handleCreateOrDelete = (uri: vscode.Uri) => {
        if (sceneWatcherSuppressed) {
            operationTracker.log(`[Watcher] Suppressed (rename in progress): ${uri.fsPath}`);
            return;
        }
        operationTracker.log(`[Watcher] File created/deleted: ${uri.fsPath}`);
        scheduleStalenessCheck();
        void scenesTreeProvider.refresh().catch(() => {});
    };

    const disposables: vscode.Disposable[] = [];
    for (const ext of sceneExtensions) {
        const pattern = new vscode.RelativePattern(projectPath, `${sceneFolder}/**/*.${ext}`);
        operationTracker.log(`[Watcher] Setup: watching ${sceneFolder}/**/*.${ext} in ${projectPath}`);
        const watcher = vscode.workspace.createFileSystemWatcher(pattern);
        disposables.push(
            watcher,
            watcher.onDidCreate(handleCreateOrDelete),
            watcher.onDidDelete(handleCreateOrDelete),
            watcher.onDidChange(handleChange),
        );
    }

    sceneFileWatcherDisposables = disposables;
    if (extensionContext) {
        extensionContext.subscriptions.push(...disposables);
    }
    return disposables;
}

// ---------------------------------------------------------------------------
// Knowledge helper deps factory — injects module-level refs into extracted fns
// ---------------------------------------------------------------------------

function getKnowledgeHelperDeps(): KnowledgeReviewHelperDeps {
    return {
        ensureKnowledgeReviewPanel,
        knowledgeTreeProvider,
        detectProjectPath,
        ensureServer,
        ensureApiClient,
        showInformationMessage: (msg) => { void vscode.window.showInformationMessage(msg); },
        showErrorMessage: (msg) => { void vscode.window.showErrorMessage(msg); },
    };
}

async function runTrackedOperation<T>(
    profile: {
        id: string;
        title: string;
        statusMessage?: string;
        slowThresholdMs?: number;
        progressThresholdMs?: number;
        progressLocation?: vscode.ProgressLocation;
    },
    operation: () => Promise<T>,
): Promise<T> {
    if (!operationTracker) {
        return operation();
    }
    return operationTracker.run(profile, operation);
}

async function navigateToFindingLine(finding: Finding): Promise<void> {
    if (finding.line_start === null) {
        return;
    }

    const scenePath = finding.scene_path || diagnosticsProvider.scenePath;
    if (!scenePath) {
        return;
    }

    const line = Math.max(0, finding.line_start - 1);
    const endLine = Math.max(0, (finding.line_end || finding.line_start) - 1);
    const range = new vscode.Range(line, 0, endLine, 0);

    const scenePathLower = scenePath.toLowerCase();
    const existingEditor = vscode.window.visibleTextEditors.find(
        e => e.document.uri.fsPath.toLowerCase() === scenePathLower
    );

    if (existingEditor) {
        existingEditor.selection = new vscode.Selection(range.start, range.end);
        existingEditor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    } else {
        const uri = vscode.Uri.file(scenePath);
        await vscode.window.showTextDocument(uri, {
            viewColumn: vscode.ViewColumn.One,
            selection: range,
            preserveFocus: true,
        });
    }
}

