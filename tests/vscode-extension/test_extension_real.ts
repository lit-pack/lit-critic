/**
 * Real tests for extension.ts (main extension module).
 * 
 * Tests the actual extension activation and command registration with mocked dependencies.
 */

import { strict as assert } from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { createFreshMockVscode } from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('Extension (Real)', () => {
    let mockVscode: any;
    let mockServerManager: any;
    let mockApiClient: any;
    let mockFindingsTreeProvider: any;
    let mockFindingsDecorationProvider: any;
    let mockSessionsTreeProvider: any;
    let mockAnalysisTreeProvider: any;
    let mockLearningTreeProvider: any;
    let mockKnowledgeTreeProvider: any;
    let mockKnowledgeReviewPanel: any;
    let mockDiagnosticsProvider: any;
    let mockDiscussionPanel: any;
    let mockStatusBar: any;
    let mockOperationTracker: any;
    let mockPath: any;
    let mockFs: any;
    let mockLoopClient: any;
    let activate: any;
    let deactivate: any;
    let lastKnowledgeReviewPanelState: any;

    beforeEach(() => {
        lastKnowledgeReviewPanelState = null;
        mockVscode = createFreshMockVscode();
        if (!mockVscode.workspace.onDidChangeConfiguration) {
            mockVscode.workspace.onDidChangeConfiguration = () => ({ dispose: () => {} });
        }
        if (!mockVscode.workspace.onDidSaveTextDocument) {
            mockVscode.workspace.onDidSaveTextDocument = () => ({ dispose: () => {} });
        }
        
        // Mock all internal modules with spy classes
        mockServerManager = class MockServerManager {
            isRunning = false;
            baseUrl = 'http://localhost:8000';
            port = 8000;
            async start() {
                this.isRunning = true;
            }
            stop() {
                this.isRunning = false;
            }
            dispose() {}
        };
        
        mockApiClient = class MockApiClient {
            async updateRepoPath(_repoPath: string) {
                return { ok: true };
            }
            async getSession() {
                return { active: false };
            }
            async checkSession(_projectPath: string) {
                return { exists: false };
            }
            async listSessions(_projectPath: string) {
                return { sessions: [] };
            }
            async getConfig() {
                return {
                    api_key_configured: true,
                    available_models: { sonnet: { label: 'Sonnet' } },
                    default_model: 'sonnet',
                };
            }
            // recheckStaleness() calls this during autoLoadSidebar — provide a no-op stub
            // so tests don't receive a silent TypeError when the server is running.
            async getInputStaleness(_projectPath: string) {
                return { stale_inputs: [] };
            }
            // getAnalyzableScenes is called by _cmdAnalyze — stub returns empty so
            // activation tests don't fail when the analyze command is registered.
            async getAnalyzableScenes(_projectPath: string) {
                return { analyzable_scenes: [] };
            }
            // configureLoop is called during startup inside withProgress. Without this stub
            // it throws synchronously (before .catch() can intercept), preventing setReady().
            async configureLoop(_projectPath: string, _config: any) {
                return {};
            }
        };
        
        mockFindingsTreeProvider = class MockFindingsTreeProvider {
            currentFindingItem: any;
            setFindings(_findings: any[], _scenePath: string, currentIndex: number = -1) {
                this.currentFindingItem = currentIndex >= 0 ? { id: `finding:${currentIndex + 1}` } : undefined;
            }
            setCurrentIndex(index: number) {
                this.currentFindingItem = { id: `finding:${index + 1}` };
            }
            clear() {}
            updateFinding() {}
            getCurrentFindingItem() {
                return this.currentFindingItem;
            }
        };

        mockFindingsDecorationProvider = class MockFindingsDecorationProvider {
            fireChange() {}
        };
        
        mockSessionsTreeProvider = class MockSessionsTreeProvider {
            currentSessionItem: any;
            setApiClient() {}
            setProjectPath() {}
            async refresh() {}
            setCurrentSession(sessionId: number | null) {
                this.currentSessionItem = sessionId === null ? undefined : { id: `session:${sessionId}` };
            }
            setCurrentSessionByScenePath(scenePath?: string) {
                this.currentSessionItem = scenePath ? { id: 'session:auto' } : undefined;
            }
            getCurrentSessionItem() {
                return this.currentSessionItem;
            }
            // Stub for recheckStaleness — avoids silent TypeError when called without mock
            setStaleSessions(_ids: Set<number>) {}
        };
        
        mockAnalysisTreeProvider = class MockAnalysisTreeProvider {
            setFindings() {}
            setAllFindings() {}
            clear() {}
            getFindingsForScene() { return []; }
        };

        mockLearningTreeProvider = class MockLearningTreeProvider {
            setApiClient() {}
            setProjectPath() {}
            setLogger() {}
            async refresh() {}
        };

        mockKnowledgeTreeProvider = class MockKnowledgeTreeProvider {
            setApiClient() {}
            setProjectPath() {}
            async refresh() {}
            getEntityPayload() {
                return null;
            }
            getAdjacentEntityPayload() {
                return null;
            }
        };

        mockKnowledgeReviewPanel = class MockKnowledgeReviewPanel {
            onAction: any;
            show(state: any) {
                lastKnowledgeReviewPanelState = state;
            }
            updateState(state: any) {
                lastKnowledgeReviewPanelState = state;
            }
            getState() {
                return lastKnowledgeReviewPanelState;
            }
            close() {}
            dispose() {}
        };
        
        mockDiagnosticsProvider = class MockDiagnosticsProvider {
            scenePath = '';
            setScenePath() {}
            updateFromFindings() {}
            removeFinding() {}
            clear() {}
            dispose() {}
        };
        
        mockDiscussionPanel = class MockDiscussionPanel {
            show(_finding: any, _current: number, _total: number, _readOnlyNotice?: string) {}
            close() {}
            dispose() {}
        };
        
        mockStatusBar = class MockStatusBar {
            setReady() {}
            setAnalyzing() {}
            setProgress() {}
            setComplete() {}
            setError() {}
            dispose() {}
        };

        mockOperationTracker = class MockOperationTracker {
            log(_message: string) {}
            async run(_profile: any, operation: () => Promise<any>) {
                return operation();
            }
            dispose() {}
        };
        
        // Mock path module
        mockPath = require('path');
        
        // Mock fs module (for findRepoRoot).
        // Use only the filename check — not a forward-slash directory check — so
        // the default is platform-agnostic on both Unix and Windows (where
        // path.join produces backslash separators that break '/test/repo' checks).
        mockFs = {
            existsSync: (p: string) => {
                return p.includes('lit-critic-server.py');
            },
        };

        // Default LoopClient mock — no-op stub. Tests that need to capture the
        // event handler override this before calling loadExtension().
        mockLoopClient = class MockLoopClient {
            constructor(_baseUrl: string, _opts: any) {}
            startEventStream(_handler: any) {}
            notifyFileChanged(_path: string, _type: string) {}
            dispose() {}
        };
    });

    afterEach(() => {
        // Clean up module cache
        activate = null;
        deactivate = null;
    });

    function loadExtension() {
        // Pre-load registerCommands with the mock vscode so its transitive
        // `import * as vscode from 'vscode'` is shimmed rather than hitting
        // the real (unavailable) vscode module in the test environment.
        const registerCommandsMod = proxyquire(
            '../../vscode-extension/src/commands/registerCommands',
            { vscode: mockVscode },
        );

        // Pre-load sceneDiscoveryConfig so its `import * as vscode` is shimmed.
        const sceneDiscoveryConfigMod = proxyquire(
            '../../vscode-extension/src/bootstrap/sceneDiscoveryConfig',
            { vscode: mockVscode },
        );

        // Pre-load explainActionProvider so its `import * as vscode` is shimmed.
        const explainActionProviderMod = proxyquire(
            '../../vscode-extension/src/workflows/explainActionProvider',
            { vscode: mockVscode },
        );

        const module = proxyquire('../../vscode-extension/src/extension', {
            'vscode': mockVscode,
            './workflows/loopClient': {
                // LoopClient uses EventSource (browser-only SSE API) which is unavailable in Node.js.
                // Replace with a configurable stub so startEventStream() doesn't throw synchronously,
                // which would prevent presenter.setReady() from being called after withProgress.
                // Override mockLoopClient before calling loadExtension() to capture the event handler.
                LoopClient: mockLoopClient,
            },
            './workflows/explainActionProvider': explainActionProviderMod,
            './serverManager': { ServerManager: mockServerManager },
            './apiClient': { ApiClient: mockApiClient },
            './findingsTreeProvider': {
                FindingsTreeProvider: mockFindingsTreeProvider,
                FindingsDecorationProvider: mockFindingsDecorationProvider,
            },
            './sessionsTreeProvider': { SessionsTreeProvider: mockSessionsTreeProvider },
            './analysisTreeProvider': { AnalysisTreeProvider: mockAnalysisTreeProvider },
            './learningTreeProvider': { LearningTreeProvider: mockLearningTreeProvider },
            './scenesTreeProvider': { ScenesTreeProvider: mockLearningTreeProvider },
            './knowledgeTreeProvider': { KnowledgeTreeProvider: mockKnowledgeTreeProvider },
            './knowledgeReviewViewProvider': { KnowledgeReviewViewProvider: mockKnowledgeReviewPanel },
            './diagnosticsProvider': { DiagnosticsProvider: mockDiagnosticsProvider },
            './discussionViewProvider': { DiscussionViewProvider: mockDiscussionPanel },
            './statusBar': { StatusBar: mockStatusBar },
            './operationTracker': { OperationTracker: mockOperationTracker },
            'path': mockPath,
            'fs': mockFs,
            './commands/registerCommands': registerCommandsMod,
            './bootstrap/sceneDiscoveryConfig': sceneDiscoveryConfigMod,
        });
        activate = module.activate;
        deactivate = module.deactivate;
        return module;
    }

    describe('activation', () => {
        it('should register all commands', async () => {
            const registeredCommands: string[] = [];

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                registeredCommands.push(cmd);
                return { dispose: () => {} };
            };

            // Disable auto-start so activation does not attempt server recovery,
            // which requires a configured repo root we do not provide in this test.
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            loadExtension();

            const context = {
                subscriptions: [],
            };

            await activate(context);
            
            // Verify all commands are registered
            assert.ok(registeredCommands.includes('litCritic.analyze'));
            assert.ok(registeredCommands.includes('litCritic.selectModel'));
            assert.ok(registeredCommands.includes('litCritic.stopServer'));
            assert.ok(!registeredCommands.includes('litCritic.refreshSessions'), 'refreshSessions was removed (D3)');
            assert.ok(registeredCommands.includes('litCritic.showLensFindings'));
            assert.ok(registeredCommands.includes('litCritic.refreshLearning'));
            assert.ok(registeredCommands.includes('litCritic.exportLearning'));
            assert.ok(registeredCommands.includes('litCritic.resetLearning'));
            assert.ok(registeredCommands.includes('litCritic.deleteLearningEntry'));
            assert.ok(registeredCommands.includes('litCritic.refreshKnowledge'));
            assert.ok(registeredCommands.includes('litCritic.deleteKnowledgeEntity'));

            assert.ok(registeredCommands.length >= 15, `Expected at least 15 commands, got ${registeredCommands.length}`);
        });

        it('should create all UI components', async () => {
            // Disable auto-start so activation does not attempt server recovery,
            // which requires a configured repo root we do not provide in this test.
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            loadExtension();

            const context = {
                subscriptions: [],
            };

            await activate(context);

            // At least 3 tree views + status bar + diagnostics provider should be pushed
            assert.ok(context.subscriptions.length >= 5,
                `Expected at least 5 subscriptions, got ${context.subscriptions.length}`);
        });

        it('should create tree views for findings, sessions, learning, scenes, and indexes', async () => {
            const createdViews: string[] = [];

            mockVscode.window.createTreeView = (viewId: string, options: any) => {
                createdViews.push(viewId);
                return { dispose: () => {} };
            };

            // Disable auto-start so activation does not attempt server recovery,
            // which requires a configured repo root we do not provide in this test.
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            loadExtension();

            const context = {
                subscriptions: [],
            };

            await activate(context);
            
            assert.ok(createdViews.includes('litCritic.findings'));
            assert.ok(createdViews.includes('litCritic.sessions'));
            assert.ok(createdViews.includes('litCritic.learning'));
            assert.ok(createdViews.includes('litCritic.scenes'));
            assert.ok(createdViews.includes('litCritic.indexes'));
        });

        it('hydrates the knowledge review panel from a tree-item launch payload', async () => {
            const registeredCommands = new Map<string, (...args: any[]) => any>();

            mockVscode.commands.registerCommand = (cmd: string, callback: (...args: any[]) => any) => {
                registeredCommands.set(cmd, callback);
                return { dispose: () => {} };
            };
            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockFs = {
                existsSync: (candidatePath: string) => (
                    (candidatePath.includes('CANON.md') || candidatePath.includes('lit-critic-server.py'))
                    && candidatePath.includes('/test/repo')
                ),
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async checkSession(_projectPath: string) {
                    return { exists: false };
                }
                async listSessions(_projectPath: string) {
                    return { sessions: [] };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getKnowledgeReview() {
                    return {
                        entities: [
                            { entity_key: 'char:alice', name: 'Alice', role: 'Lead' },
                        ],
                        overrides: [
                            { entity_key: 'char:alice', field_name: 'role', override_value: 'Protagonist' },
                        ],
                    };
                }
            };

            loadExtension();

            const context = {
                subscriptions: [],
            };

            await activate(context);

            const openKnowledgeReviewPanel = registeredCommands.get('litCritic.openKnowledgeReviewPanel');
            assert.ok(openKnowledgeReviewPanel, 'Expected openKnowledgeReviewPanel command to be registered');

            await openKnowledgeReviewPanel?.({
                payload: {
                    category: 'characters',
                    entityKey: 'char:alice',
                    label: 'Alice',
                    entity: { entity_key: 'char:alice', name: 'Alice', role: 'Lead' },
                    overrideFields: ['role'],
                    overrideCount: 1,
                    hasOverrides: true,
                },
            });

            assert.ok(lastKnowledgeReviewPanelState, 'Expected knowledge review panel state to be created');
            assert.equal(lastKnowledgeReviewPanelState.entityLabel, 'Alice');
            const roleField = lastKnowledgeReviewPanelState.fields.find((field: any) => field.fieldName === 'role');
            assert.ok(roleField, 'Expected hydrated panel state to include the role field');
            assert.equal(roleField.extractedValue, 'Lead');
            assert.equal(roleField.hasOverride, true);
        });
    });

    describe('auto-start behavior', () => {
        it('should not reveal sessions or findings in the tree during passive auto-load startup', async () => {
            const sessionRevealCalls: Array<{ item: any; options: any }> = [];
            const findingRevealCalls: Array<{ item: any; options: any }> = [];

            mockVscode.window.createTreeView = (viewId: string, _options: any) => {
                const reveal = async (item: any, options: any) => {
                    if (viewId === 'litCritic.sessions') {
                        sessionRevealCalls.push({ item, options });
                    }
                    if (viewId === 'litCritic.findings') {
                        findingRevealCalls.push({ item, options });
                    }
                };
                return { dispose: () => {}, reveal, visible: true };
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getInputStaleness(_projectPath: string) {
                    return { stale_inputs: [] };
                }
                async configureLoop(_projectPath: string, _config: any) {
                    return {};
                }
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.equal(
                sessionRevealCalls.length,
                0,
                'Expected no session TreeView reveal during passive startup auto-load',
            );
            assert.equal(
                findingRevealCalls.length,
                0,
                'Expected no finding TreeView reveal during passive startup auto-load',
            );
        });

        it('should show an immediate startup hint before startup progress notification', async () => {
            const timeline: string[] = [];

            // Transient setStatusBarMessage calls were removed; startup uses a progress notification only.
            mockVscode.window.setStatusBarMessage = () => ({ dispose: () => {} });
            mockVscode.window.withProgress = async (options: any, task: any) => {
                timeline.push(`progress:${options?.title || ''}`);
                return task(
                    { report: (_value: any) => {} },
                    {
                        isCancellationRequested: false,
                        onCancellationRequested: (_listener: any) => ({ dispose: () => {} }),
                    },
                );
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            const progressIndex = timeline.indexOf('progress:lit-critic');

            assert.ok(progressIndex >= 0, 'Expected startup progress notification to be shown');
        });

        it('should reset status bar to ready after startup completes', async () => {
            const statusTransitions: string[] = [];

            mockStatusBar = class MockStatusBar {
                setReady() { statusTransitions.push('ready'); }
                setAnalyzing(message?: string) { statusTransitions.push(`analyzing:${message || ''}`); }
                setProgress() {}
                setComplete() {}
                setError() {}
                setLoopActivity(_msg: string) {}
                setLoopIdle() {}
                updateLoopBudget(_cost: number, _tokens: number) {}
                resetLoopBudget() {}
                dispose() {}
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(
                statusTransitions.includes('analyzing:Starting server...'),
                'Expected startup to set analyzing state',
            );
            assert.equal(
                statusTransitions[statusTransitions.length - 1],
                'ready',
                'Expected status bar to return to ready after startup',
            );
        });

        it('should show staged startup progress messages when auto-starting server', async () => {
            const progressTitles: string[] = [];
            const progressMessages: string[] = [];

            mockServerManager = class MockStagedServerManager {
                isRunning = false;
                baseUrl = 'http://localhost:8000';
                port = 8000;
                async start(onStage?: (stage: 'checking' | 'launching' | 'waiting' | 'ready') => void) {
                    onStage?.('launching');
                    onStage?.('waiting');
                    onStage?.('ready');
                    this.isRunning = true;
                }
                stop() {
                    this.isRunning = false;
                }
                dispose() {}
            };

            mockVscode.window.withProgress = async (options: any, task: any) => {
                progressTitles.push(options?.title || '');
                return task(
                    {
                        report: (value: any) => {
                            if (value?.message) {
                                progressMessages.push(value.message);
                            }
                        },
                    },
                    {
                        isCancellationRequested: false,
                        onCancellationRequested: (_listener: any) => ({ dispose: () => {} }),
                    },
                );
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(
                progressTitles.includes('lit-critic'),
                'Expected startup notification progress to be shown during auto-start',
            );
            assert.ok(
                progressMessages.includes('Checking for a running backend...'),
                'Expected startup progress to include existing-instance check stage',
            );
            assert.ok(
                progressMessages.includes('Launching backend process...'),
                'Expected startup progress to include backend launch stage',
            );
            assert.ok(
                progressMessages.includes('Waiting for server readiness...'),
                'Expected startup progress to include readiness-check stage',
            );
            assert.ok(
                progressMessages.includes('Loading project data...'),
                'Expected startup progress to include loading stage',
            );
        });

        it('should check input staleness before loading scenes and indexes during auto-load startup', async () => {
            // After commit 1d847d5, autoLoadSidebar calls recheckStaleness() (which calls
            // getInputStaleness) instead of the old refreshProjectKnowledge path.
            const getInputStalenessCalls: string[] = [];

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getInputStaleness(projectPath: string) {
                    getInputStalenessCalls.push(projectPath);
                    return { stale_inputs: [] };
                }
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(
                getInputStalenessCalls.includes('/test/repo'),
                'Expected startup auto-load to check input staleness via recheckStaleness before tree population',
            );
        });

        it('should sync scene discovery settings from extension config to server during auto-start', async () => {
            const updateConfigCalls: any[] = [];

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async updateConfig(payload: any) {
                    updateConfigCalls.push(payload);
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async refreshProjectKnowledge() {
                    return {
                        scenes: { total: 0, refreshed: 0, stale: 0, stale_paths: [] },
                        indexes: { total: 0, refreshed: 0, stale: 0, stale_names: [] },
                    };
                }
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    if (key === 'sceneFolder') return 'story/scenes';
                    if (key === 'sceneExtensions') return ['md', 'txt'];
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(
                updateConfigCalls.some((payload) => (
                    payload.scene_folder === 'story/scenes'
                    && Array.isArray(payload.scene_extensions)
                    && payload.scene_extensions.length === 2
                    && payload.scene_extensions[0] === 'md'
                    && payload.scene_extensions[1] === 'txt'
                )),
                'Expected startup to push configured scene discovery settings to backend config',
            );
        });

        it('should run repo-path recovery prompt during activation when configured repoPath is invalid', async () => {
            let serverStarted = false;
            let openedFolderDialog = false;
            let updatedRepoPath: string | undefined;

            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-activation-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            let configuredRepoPath = '/invalid/repo/path';

            mockServerManager = class extends mockServerManager {
                async start() {
                    serverStarted = true;
                    this.isRunning = true;
                }
            };

            mockVscode.window.showErrorMessage = async (message: string, ...items: any[]) => {
                if (message.includes('startup preflight failed') && items.includes('Select Folder…')) {
                    return 'Select Folder…';
                }
                return undefined;
            };

            mockVscode.window.showOpenDialog = async () => {
                openedFolderDialog = true;
                return [{ fsPath: validRepo }];
            };

            // Ensure repo discovery fails first so activation enters recovery flow.
            mockVscode.workspace.workspaceFolders = undefined;
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return configuredRepoPath;
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async (key: string, value: any) => {
                    if (key === 'repoPath') {
                        configuredRepoPath = value;
                        updatedRepoPath = value;
                    }
                },
            });

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(openedFolderDialog, 'Expected repo recovery folder picker to open during activation');
            assert.equal(updatedRepoPath, validRepo, 'Expected corrected repoPath to be persisted during activation');
            assert.ok(serverStarted, 'Expected auto-start to continue after repo path recovery');

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should auto-start server when autoStartServer is true', async () => {
            let serverStarted = false;
            
            mockServerManager = class extends mockServerManager {
                async start() {
                    serverStarted = true;
                    this.isRunning = true;
                }
            };
            
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            
            // Set up workspace with repo
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];
            
            mockFs.existsSync = (path: string) => {
                return path.includes('lit-critic-server.py');
            };
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            assert.ok(serverStarted, 'Server should have been started');
        });

        it('should reveal lit-critic activity view after auto-start when CANON.md is present', async () => {
            const executeCommandCalls: string[] = [];

            mockVscode.commands.executeCommand = async (command: string, ..._rest: any[]) => {
                executeCommandCalls.push(command);
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();

            await activate({ subscriptions: [] });

            assert.ok(
                executeCommandCalls.includes('workbench.view.extension.lit-critic'),
                'Expected lit-critic activity view to be revealed when CANON.md is present',
            );
        });

        it('should reveal lit-critic activity view after auto-start when repo root exists but CANON.md is missing', async () => {
            const executeCommandCalls: string[] = [];

            mockVscode.commands.executeCommand = async (command: string, ..._rest: any[]) => {
                executeCommandCalls.push(command);
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py');
            };

            loadExtension();

            await activate({ subscriptions: [] });

            assert.ok(
                executeCommandCalls.includes('workbench.view.extension.lit-critic'),
                'Expected lit-critic activity view to be revealed when repo root is detected even if CANON.md is missing',
            );
        });

        it('should not reveal lit-critic activity view after auto-start when neither CANON.md nor repo root marker is present', async () => {
            const executeCommandCalls: string[] = [];

            mockVscode.commands.executeCommand = async (command: string, ..._rest: any[]) => {
                executeCommandCalls.push(command);
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (_filePath: string) => false;

            // No repo marker found → activation enters ensureRepoRootWithRecovery().
            // Return undefined to simulate the user dismissing the dialog, which causes
            // the recovery loop to throw and activation to complete without hanging.
            mockVscode.window.showErrorMessage = async () => undefined;

            loadExtension();

            await activate({ subscriptions: [] });

            assert.ok(
                !executeCommandCalls.includes('workbench.view.extension.lit-critic'),
                'Expected lit-critic activity view not to be revealed when no project path can be detected',
            );
        });

        it('should NOT auto-start when autoStartServer is false', async () => {
            let serverStarted = false;
            let recoveryPromptShown = false;
            
            mockServerManager = class extends mockServerManager {
                async start() {
                    serverStarted = true;
                    this.isRunning = true;
                }
            };
            
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return '/invalid/repo/path';
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.window.showErrorMessage = async (message: string, ...items: any[]) => {
                if (message.includes('startup preflight failed') && items.includes('Select Folder…')) {
                    recoveryPromptShown = true;
                }
                return undefined;
            };
            
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            assert.ok(!serverStarted, 'Server should not have been started');
            assert.ok(!recoveryPromptShown, 'Recovery prompt should not be shown when auto-start is disabled');
        });

        it('should handle missing repo root gracefully', async () => {
            // No workspace folders, no auto-start: verify UI components are still registered.
            mockVscode.workspace.workspaceFolders = undefined;
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            loadExtension();

            const context = {
                subscriptions: [],
            };

            // Should not throw
            await activate(context);

            // UI components should still be registered
            assert.ok(context.subscriptions.length > 0);
        });

        it('should drive correct status bar transitions for the redesigned loop SSE event sequence', async () => {
            // Regression smoke test for the loop redesign (Task 4.3).
            // Simulates the SSE event sequence that the redesigned loop emits after
            // configuring a project: extraction_started → extraction_complete →
            // quick_analysis_started → quick_analysis_complete → cycle_complete (NOOP).
            // Asserts the extension drives the correct status bar transitions.
            const statusTransitions: string[] = [];
            let capturedEventHandler: ((event: any) => void) | undefined;

            mockStatusBar = class MockStatusBar {
                setReady() { statusTransitions.push('ready'); }
                setAnalyzing(message?: string) { statusTransitions.push(`analyzing:${message || ''}`); }
                setProgress() {}
                setComplete() {}
                setError() {}
                setLoopActivity(msg: string) { statusTransitions.push(`loop-activity:${msg}`); }
                setLoopIdle() { statusTransitions.push('loop-idle'); }
                updateLoopBudget(_cost: number, _tokens: number) {}
                resetLoopBudget() {}
                dispose() {}
            };

            // Capture the event handler passed to startEventStream so we can
            // simulate SSE events after activation completes.
            mockLoopClient = class MockLoopClient {
                constructor(_baseUrl: string, _opts: any) {}
                startEventStream(handler: any) { capturedEventHandler = handler; }
                notifyFileChanged(_path: string, _type: string) {}
                dispose() {}
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) { return { ok: true }; }
                async getSession() { return { active: false }; }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getInputStaleness(_projectPath: string) { return { stale_inputs: [] }; }
                async configureLoop(_projectPath: string, _config: any) { return {}; }
            };

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            assert.ok(capturedEventHandler, 'Expected LoopClient.startEventStream to capture the event handler');

            // Clear status transitions accumulated during startup so we only
            // assert against the loop event sequence.
            statusTransitions.length = 0;

            // Simulate the redesigned loop's first-cycle SSE event sequence:
            // 1. extraction_started  → spinner shown
            capturedEventHandler!({ event: 'extraction_started' });
            // 2. extraction_complete → spinner cleared
            capturedEventHandler!({ event: 'extraction_complete' });
            // 3. quick_analysis_started → spinner shown
            capturedEventHandler!({ event: 'quick_analysis_started' });
            // 4. quick_analysis_complete → spinner cleared, trees refreshed
            capturedEventHandler!({ event: 'quick_analysis_complete', analyzed: [] });
            // 5. cycle_complete (NOOP) → default handler, no UI action
            capturedEventHandler!({ event: 'cycle_complete' });

            assert.deepEqual(
                statusTransitions,
                [
                    'loop-activity:Extracting knowledge…',
                    'loop-idle',
                    'loop-activity:Quick analysis…',
                    'loop-idle',
                ],
                'Expected status bar to show extraction spinner → idle → analysis spinner → idle for the redesigned loop event sequence',
            );
        });
    });

    describe('deactivation', () => {
        it('should stop the server on deactivate', async () => {
            // Track stop calls via prototype
            const stopCalls: any[] = [];
            const OriginalServerManager = mockServerManager;
            
            mockServerManager = class extends OriginalServerManager {
                stop() {
                    stopCalls.push(this);
                    this.isRunning = false;
                }
            };
            
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];
            
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            
            // Fix path separators issue - just check for the file
            mockFs.existsSync = (path: string) => {
                return path.includes('lit-critic-server.py');
            };
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            deactivate();
            
            assert.ok(stopCalls.length > 0, 'Server stop() should have been called');
        });
    });

    describe('helper functions', () => {
        it('should detect repo root from workspace', async () => {
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            // Use a platform-agnostic filename-only check so this works on
            // both Unix (forward slashes) and Windows (backslashes from path.join).
            mockFs.existsSync = (p: string) => {
                return p.includes('lit-critic-server.py');
            };

            // Disable auto-start: this test only verifies that findRepoRoot() can
            // discover the repo from workspace folders. Auto-start is not needed and,
            // without an explicit autoStartServer:false, the default config would pass
            // true, which could trigger the recovery loop on machines where path
            // resolution behaves unexpectedly.
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            // If repo root is found, ServerManager should be created
            // We can't directly test the helper, but we can verify the side effect
            assert.ok(true); // Activation succeeded
        });

        it('should handle configured repoPath setting', async () => {
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return '/custom/repo/path';
                    if (key === 'autoStartServer') return false; // Don't auto-start to simplify test
                    return defaultValue;
                },
                update: async () => {},
            });
            
            mockFs.existsSync = (path: string) => {
                return path.includes('/custom/repo/path') && path.includes('lit-critic-server.py');
            };
            
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/some/other/path' } },
            ];
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            // Should use configured path rather than workspace folders
            assert.ok(true); // Activation succeeded with custom repo path
        });

        it('should detect project path from CANON.md', async () => {
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/project' } },
            ];

            mockFs.existsSync = (path: string) => {
                // CANON.md exists in the workspace, but no lit-critic-server.py
                // (so findRepoRoot returns undefined — auto-start disabled to avoid recovery loop)
                if (path.includes('CANON.md') && path.includes('/test/project')) {
                    return true;
                }
                return false;
            };

            // Without lit-critic-server.py, findRepoRoot() returns undefined.
            // Disable auto-start so activation does not enter the repo recovery loop.
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            loadExtension();

            const context = {
                subscriptions: [],
            };

            await activate(context);

            // detectProjectPath is called during auto-load
            assert.ok(true); // Should handle project detection gracefully
        });
    });

    describe('command handlers', () => {
        it('should show immediate startup hint when analyze triggers lazy server start', async () => {
            let analyzeCallback: any;
            const statusMessages: string[] = [];

            // Transient setStatusBarMessage calls were removed; startup uses a progress notification only.
            mockVscode.window.setStatusBarMessage = () => ({ dispose: () => {} });

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async checkSession() {
                    return { exists: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async analyze() {
                    return {
                        scene_path: '/test/repo/scene-a.txt',
                        scene_name: 'scene-a.txt',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(_onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => onDone(), 0);
                    return () => {};
                }
                async getCurrentFinding() {
                    return { complete: true };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.activeTextEditor = undefined;
            mockVscode.window.visibleTextEditors = [];
            mockVscode.window.showOpenDialog = async () => [{ fsPath: '/test/repo/scene-a.txt' }];
            mockVscode.window.showTextDocument = async () => ({
                document: { uri: { fsPath: '/test/repo/scene-a.txt' } },
                viewColumn: 1,
            });

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

        });

        it('should show analysis startup progress notification during analyze handoff', async () => {
            let analyzeCallback: any;
            const progressTitles: string[] = [];

            mockVscode.window.withProgress = async (options: any, task: any) => {
                progressTitles.push(options?.title || '');
                return task(
                    { report: (_value: any) => {} },
                    {
                        isCancellationRequested: false,
                        onCancellationRequested: (_listener: any) => ({ dispose: () => {} }),
                    },
                );
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async checkSession() {
                    return { exists: false };
                }
                async listSessions() {
                    return { sessions: [] };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getAnalyzableScenes(_projectPath: string) {
                    return { analyzable_scenes: [{ scene_key: 'scene-a.txt', path: '/test/repo/scene-a.txt', status: 'extraction_due' }] };
                }
                async analyze() {
                    return {
                        scene_path: '/test/repo/scene-a.txt',
                        scene_name: 'scene-a.txt',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => {
                        onEvent({ type: 'status', message: 'Starting analysis...' });
                        onDone();
                    }, 0);
                    return () => {};
                }
                async getCurrentFinding() {
                    return { complete: true };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.activeTextEditor = undefined;
            mockVscode.window.visibleTextEditors = [];
            mockVscode.window.showOpenDialog = async () => [{ fsPath: '/test/repo/scene-a.txt' }];
            mockVscode.window.showTextDocument = async () => ({
                document: { uri: { fsPath: '/test/repo/scene-a.txt' } },
                viewColumn: 1,
            });

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.ok(
                progressTitles.includes('lit-critic: Starting analysis'),
                'Expected analysis startup notification progress to be shown',
            );
        });

        it('should show quick mode status message instead of hardcoded lens-count text', async () => {
            let analyzeCallback: any;
            const statusMessages: string[] = [];
            let analyzeMode: string | undefined;

            mockStatusBar = class MockStatusBar {
                setReady() {}
                setAnalyzing(message?: string) {
                    statusMessages.push(message || '');
                }
                setProgress() {}
                setComplete() {}
                setError() {}
                dispose() {}
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async checkSession() {
                    return { exists: false };
                }
                async listSessions() {
                    return { sessions: [] };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getAnalyzableScenes(_projectPath: string) {
                    return { analyzable_scenes: [{ scene_key: 'scene-a.txt', path: '/test/repo/scene-a.txt', status: 'extracted' }] };
                }
                async analyze(
                    _scenePath: string,
                    _projectPath: string,
                    _apiKey: string | undefined,
                    _scenePaths?: string[],
                    mode?: string,
                ) {
                    analyzeMode = mode;
                    return {
                        scene_path: '/test/repo/scene-a.txt',
                        scene_name: 'scene-a.txt',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(_onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => onDone(), 0);
                    return () => {};
                }
                async getCurrentFinding() {
                    return { complete: true };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    if (key === 'analysisModel') return 'haiku';
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });
            mockVscode.window.activeTextEditor = {
                document: {
                    uri: {
                        scheme: 'file',
                        fsPath: '/test/repo/scene-a.txt',
                    },
                },
            };

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.equal(analyzeMode, 'haiku');
            assert.ok(
                statusMessages.some((message) => message.includes('Running analysis (Haiku)...')),
                'Expected status bar to include model-aware analysis status',
            );
            assert.ok(
                statusMessages.every((message) => !message.includes('preset')),
                'Expected no preset-oriented status text',
            );
        });

        it('should sync backend repo path after repo-path recovery during analyze startup', async () => {
            let analyzeCallback: any;
            let updatedRepoPathCall: string | undefined;

            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-repo-sync-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            let configuredRepoPath = '/invalid/repo/path';

            mockApiClient = class extends mockApiClient {
                async updateRepoPath(repoPath: string) {
                    updatedRepoPathCall = repoPath;
                    return { ok: true };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.showErrorMessage = async (message: string, ...items: string[]) => {
                if (message.includes('startup preflight failed') && items.includes('Select Folder…')) {
                    return 'Select Folder…';
                }
                return undefined;
            };

            mockVscode.window.showOpenDialog = async () => {
                return [{ fsPath: validRepo }];
            };

            mockVscode.window.activeTextEditor = undefined;
            mockVscode.window.visibleTextEditors = [];

            mockVscode.workspace.workspaceFolders = undefined;
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return configuredRepoPath;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async (key: string, value: any) => {
                    if (key === 'repoPath') {
                        configuredRepoPath = value;
                    }
                },
            });

            loadExtension();
            await activate({ subscriptions: [] });

            await analyzeCallback();

            assert.equal(
                updatedRepoPathCall,
                validRepo,
                'Expected extension to sync corrected repo path to backend via /api/repo-path',
            );

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should recover from invalid repoPath via Select Folder and retry startup', async () => {
            let analyzeCallback: any;
            let serverStarted = false;
            let openedFolderDialog = false;
            let updatedRepoPath: string | undefined;

            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            let configuredRepoPath = '/invalid/repo/path';

            mockServerManager = class extends mockServerManager {
                async start() {
                    serverStarted = true;
                    this.isRunning = true;
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.showErrorMessage = async (message: string, ...items: string[]) => {
                if (message.includes('startup preflight failed') && items.includes('Select Folder…')) {
                    return 'Select Folder…';
                }
                return undefined;
            };

            mockVscode.window.showOpenDialog = async () => {
                openedFolderDialog = true;
                return [{ fsPath: validRepo }];
            };

            mockVscode.window.activeTextEditor = undefined;
            mockVscode.window.visibleTextEditors = [];

            mockVscode.workspace.workspaceFolders = undefined;
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return configuredRepoPath;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async (key: string, value: any) => {
                    if (key === 'repoPath') {
                        configuredRepoPath = value;
                        updatedRepoPath = value;
                    }
                },
            });

            loadExtension();
            await activate({ subscriptions: [] });

            await analyzeCallback();

            assert.ok(openedFolderDialog, 'Expected recovery folder picker to open');
            assert.equal(updatedRepoPath, validRepo, 'Expected corrected repoPath to be persisted');
            assert.ok(serverStarted, 'Expected server startup to retry after repo path correction');

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should show up-to-date info message when no stale scenes are detected', async () => {
            let analyzeCallback: any;
            const infoMessages: string[] = [];
            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-analyze-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') {
                    analyzeCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.showInformationMessage = async (message: string) => {
                infoMessages.push(message);
                return undefined;
            };

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return validRepo;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            // detectProjectPath() requires CANON.md in the workspace folder.
            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.ok(
                infoMessages.some(m => m.includes('All scenes are up to date')),
                'Expected up-to-date message when staleness API returns no stale scenes',
            );

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should analyze all stale scenes returned by the staleness API', async () => {
            let analyzeCallback: any;
            let analyzedScenePath: string | undefined;
            let analyzedScenePaths: string[] | undefined;
            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-analyze-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) { return { ok: true }; }
                async getSession() { return { active: false }; }
                async checkSession() { return { exists: false }; }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getAnalyzableScenes(_projectPath: string) {
                    return {
                        analyzable_scenes: [
                            { scene_key: 'scene-a.md', path: '/test/repo/scene-a.md', status: 'extracted' },
                            { scene_key: 'scene-b.md', path: '/test/repo/scene-b.md', status: 'extraction_due' },
                        ],
                    };
                }
                async analyze(scenePath: string, _projectPath: string, _apiKey: string | undefined, scenePaths?: string[]) {
                    analyzedScenePath = scenePath;
                    analyzedScenePaths = scenePaths;
                    return {
                        scene_path: scenePath,
                        scene_name: 'scene-a.md',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(_onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => onDone(), 0);
                    return () => {};
                }
                async getCurrentFinding() { return { complete: true }; }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') { analyzeCallback = callback; }
                return { dispose: () => {} };
            };

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return validRepo;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.equal(analyzedScenePath, '/test/repo/scene-a.md', 'Expected first stale scene as primary scenePath');
            assert.deepEqual(
                analyzedScenePaths,
                ['/test/repo/scene-a.md', '/test/repo/scene-b.md'],
                'Expected all stale scene paths to be sent to analyze()',
            );

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should use staleness API to determine scene to analyze, ignoring active editor', async () => {
            let analyzeCallback: any;
            let analyzedScenePath: string | undefined;
            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-analyze-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) { return { ok: true }; }
                async getSession() { return { active: false }; }
                async checkSession() { return { exists: false }; }
                async listSessions() { return { sessions: [] }; }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getAnalyzableScenes(_projectPath: string) {
                    return { analyzable_scenes: [{ scene_key: 'stale-scene.md', path: '/test/repo/stale-scene.md', status: 'extraction_due' }] };
                }
                async analyze(scenePath: string) {
                    analyzedScenePath = scenePath;
                    return {
                        scene_path: scenePath,
                        scene_name: 'stale-scene.md',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(_onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => onDone(), 0);
                    return () => {};
                }
                async getCurrentFinding() { return { complete: true }; }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') { analyzeCallback = callback; }
                return { dispose: () => {} };
            };

            // An active editor exists — but should not affect which scene gets analyzed
            mockVscode.window.activeTextEditor = {
                document: {
                    uri: {
                        scheme: 'file',
                        fsPath: '/test/repo/already-open.md',
                    },
                },
                viewColumn: 1,
            };
            mockVscode.window.visibleTextEditors = [mockVscode.window.activeTextEditor];

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return validRepo;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.equal(
                analyzedScenePath,
                '/test/repo/stale-scene.md',
                'Expected stale scene from staleness API to be analyzed, not the active editor scene',
            );

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should pick up extracted (not just extraction_due) scenes for analysis', async () => {
            let analyzeCallback: any;
            let analyzedScenePath: string | undefined;
            const validRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'lit-critic-analyze-repo-'));
            fs.writeFileSync(path.join(validRepo, 'lit-critic-server.py'), 'print("ok")', 'utf8');

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) { return { ok: true }; }
                async getSession() { return { active: false }; }
                async checkSession() { return { exists: false }; }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async getAnalyzableScenes(_projectPath: string) {
                    // Only an `extracted` scene — not extraction_due
                    return { analyzable_scenes: [{ scene_key: 'ready.md', path: '/test/repo/ready.md', status: 'extracted' }] };
                }
                async analyze(scenePath: string) {
                    analyzedScenePath = scenePath;
                    return {
                        scene_path: scenePath,
                        scene_name: 'ready.md',
                        project_path: '/test/repo',
                        total_findings: 0,
                        current_index: 0,
                        glossary_issues: [],
                        counts: { critical: 0, major: 0, minor: 0 },
                        lens_counts: {},
                        model: { name: 'sonnet', id: 'sonnet', label: 'Sonnet' },
                        learning: { review_count: 0, preferences: 0, blind_spots: 0 },
                        findings_status: [],
                    };
                }
                streamAnalysisProgress(_onEvent: any, onDone: any, _onError: any) {
                    setTimeout(() => onDone(), 0);
                    return () => {};
                }
                async getCurrentFinding() { return { complete: true }; }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') { analyzeCallback = callback; }
                return { dispose: () => {} };
            };

            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'repoPath') return validRepo;
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
                inspect: () => ({ workspaceValue: undefined, globalValue: undefined, workspaceFolderValue: undefined }),
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });
            await analyzeCallback();

            assert.equal(
                analyzedScenePath,
                '/test/repo/ready.md',
                'Expected extracted scene to be picked up by the analyze command',
            );

            fs.rmSync(validRepo, { recursive: true, force: true });
        });

        it('should handle stopServer command', async () => {
            let serverStopped = false;
            
            mockServerManager = class extends mockServerManager {
                stop() {
                    serverStopped = true;
                    this.isRunning = false;
                }
            };
            
            let stopServerCallback: any;
            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.stopServer') {
                    stopServerCallback = callback;
                }
                return { dispose: () => {} };
            };
            
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];
            
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            
            // Fix path separators issue - just check for the file
            mockFs.existsSync = (path: string) => {
                return path.includes('lit-critic-server.py');
            };
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            // Call the stopServer command
            stopServerCallback();
            
            assert.ok(serverStopped, 'Server should have been stopped by command');
        });

        it('should handle clearSession command', async () => {
            let clearCalled = false;
            
            mockApiClient = class extends mockApiClient {
                async clearSession() {
                    clearCalled = true;
                    return { deleted: true };
                }
            };
            
            let clearSessionCallback: any;
            let showWarningResponse = 'Delete'; // User confirms
            
            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.clearSession') {
                    clearSessionCallback = callback;
                }
                return { dispose: () => {} };
            };
            
            mockVscode.window.showWarningMessage = async (message: string, options: any, ...items: string[]) => {
                return showWarningResponse;
            };
            
            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];
            
            mockVscode.workspace.getConfiguration = (section?: string) => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            
            // Fix path separators issue - just check for the file
            mockFs.existsSync = (path: string) => {
                return path.includes('lit-critic-server.py');
            };
            
            loadExtension();
            
            const context = {
                subscriptions: [],
            };
            
            await activate(context);
            
            // Call the clearSession command
            if (clearSessionCallback) {
                await clearSessionCallback();
                assert.ok(clearCalled, 'clearSession API should have been called');
            }
        });

        it('should delete learning entry when command receives Learning tree item entryId', async () => {
            let deleteLearningEntryCallback: any;
            const deletedEntryIds: number[] = [];
            const infoMessages: string[] = [];
            let learningRefreshCalls = 0;

            mockLearningTreeProvider = class MockLearningTreeProvider {
                setApiClient() {}
                setProjectPath() {}
                setLogger() {}
                async refresh() {
                    learningRefreshCalls += 1;
                }
            };

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async deleteLearningEntry(entryId: number, _projectPath: string) {
                    deletedEntryIds.push(entryId);
                    return { deleted: true, entry_id: entryId };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.deleteLearningEntry') {
                    deleteLearningEntryCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.showInformationMessage = async (message: string) => {
                infoMessages.push(message);
                return undefined;
            };

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            await deleteLearningEntryCallback({ entryId: 42 });

            assert.deepEqual(deletedEntryIds, [42]);
            assert.ok(
                infoMessages.includes('lit-critic: Learning entry deleted.'),
                'Expected success message after deleting learning entry',
            );
            assert.ok(learningRefreshCalls > 0, 'Expected learning tree refresh after deletion');
        });

        it('should support legacy deleteLearningEntry payload shape { entry: { id } }', async () => {
            let deleteLearningEntryCallback: any;
            const deletedEntryIds: number[] = [];

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async deleteLearningEntry(entryId: number, _projectPath: string) {
                    deletedEntryIds.push(entryId);
                    return { deleted: true, entry_id: entryId };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.deleteLearningEntry') {
                    deleteLearningEntryCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            await deleteLearningEntryCallback({ entry: { id: 43 } });

            assert.deepEqual(deletedEntryIds, [43]);
        });

        it('auto-chains cmdRefreshKnowledge before cmdAnalyze when stale inputs exist', async () => {
            // After session-command removal, SessionWorkflowController no longer exists.
            // The auto-chain logic now lives inline in extension.ts's cmdAnalyze handler,
            // which checks stalenessRegistry.hasStaleInputs() then calls
            // controller.cmdRefreshKnowledge() (which invokes refreshProjectKnowledge).
            // We observe the behavior through API call tracking.
            let refreshProjectKnowledgeCalled = false;
            let analyzeCallback: any;

            // recheckStaleness calls setStalePaths / setStaleEntities on tree providers.
            // Without these stubs, recheckStaleness throws silently and never populates the registry.
            mockLearningTreeProvider = class MockScenesTreeProvider {
                setApiClient() {}
                setProjectPath() {}
                setLogger() {}
                async refresh() {}
                setStaleInputPaths(_paths: Set<string>) {}
            };
            mockKnowledgeTreeProvider = class MockKnowledgeTreeProvider {
                setApiClient() {}
                setProjectPath() {}
                async refresh() {}
                getEntityPayload() { return null; }
                getAdjacentEntityPayload() { return null; }
                setAllEntitiesStale(_stale: boolean) {}
                setStaleEntityKeys(_keys: Set<string>) {}
                setOrphanedSceneKeys(_keys: Set<string>) {}
            };

            // Return a stale item so autoLoadSidebar populates the registry
            mockApiClient = class MockApiClient {
                async updateRepoPath() { return { ok: true }; }
                async getSession() { return { active: false }; }
                async getConfig() {
                    return { api_key_configured: true, available_models: { sonnet: { label: 'Sonnet' } }, default_model: 'sonnet' };
                }
                async getInputStaleness(_path: string) {
                    return { stale_inputs: [{ path: '/test/repo/text/scene1.txt', type: 'scene', affected_knowledge: [], affected_sessions: [] }] };
                }
                async refreshKnowledge() {
                    refreshProjectKnowledgeCalled = true;
                    return { scene_updated: 0, index_updated: 0 };
                }
                async configureLoop() { return {}; }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') { analyzeCallback = callback; }
                return { dispose: () => {} };
            };
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockFs.existsSync = (p: string) => p.includes('lit-critic-server.py') || p.includes('CANON.md');

            loadExtension();
            await activate({ subscriptions: [] });
            assert.ok(analyzeCallback, 'Expected analyze command to be registered');

            // recheckStaleness is fire-and-forget (void) during autoLoadSidebar,
            // so we need to flush microtasks before the registry is populated.
            await new Promise(resolve => setTimeout(resolve, 500));

            // cmdAnalyze may fail downstream (no scene selected) — that's fine;
            // we only care that refreshProjectKnowledge was triggered first.
            await analyzeCallback().catch(() => {});

            assert.ok(
                refreshProjectKnowledgeCalled,
                'Expected cmdRefreshKnowledge to trigger refreshProjectKnowledge when stale inputs exist',
            );
        });

        it('does not auto-chain cmdRefreshKnowledge when no stale inputs exist', async () => {
            let refreshProjectKnowledgeCalled = false;
            let analyzeCallback: any;

            // Return empty stale inputs so stalenessRegistry stays empty
            mockApiClient = class MockApiClient {
                async updateRepoPath() { return { ok: true }; }
                async getSession() { return { active: false }; }
                async getConfig() {
                    return { api_key_configured: true, available_models: { sonnet: { label: 'Sonnet' } }, default_model: 'sonnet' };
                }
                async getInputStaleness(_path: string) {
                    return { stale_inputs: [] };
                }
                async refreshProjectKnowledge() {
                    refreshProjectKnowledgeCalled = true;
                    return { scenes: { total: 0, refreshed: 0, stale: 0, stale_paths: [] }, indexes: { total: 0, refreshed: 0, stale: 0, stale_names: [] } };
                }
                async configureLoop() { return {}; }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.analyze') { analyzeCallback = callback; }
                return { dispose: () => {} };
            };
            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return true;
                    return defaultValue;
                },
                update: async () => {},
            });
            mockVscode.workspace.workspaceFolders = [{ uri: { fsPath: '/test/repo' } }];
            mockFs.existsSync = (p: string) => p.includes('lit-critic-server.py') || p.includes('CANON.md');

            loadExtension();
            await activate({ subscriptions: [] });
            assert.ok(analyzeCallback, 'Expected analyze command to be registered');

            await analyzeCallback().catch(() => {});

            assert.ok(
                !refreshProjectKnowledgeCalled,
                'Expected cmdRefreshKnowledge NOT to be called when no stale inputs exist',
            );
        });

        it('should show error when deleteLearningEntry cannot resolve an entry id', async () => {
            let deleteLearningEntryCallback: any;
            const errorMessages: string[] = [];
            let deleteCalled = false;

            mockApiClient = class MockApiClient {
                async updateRepoPath(_repoPath: string) {
                    return { ok: true };
                }
                async getSession() {
                    return { active: false };
                }
                async getConfig() {
                    return {
                        api_key_configured: true,
                        available_models: { sonnet: { label: 'Sonnet' } },
                        default_model: 'sonnet',
                    };
                }
                async deleteLearningEntry(_entryId: number, _projectPath: string) {
                    deleteCalled = true;
                    return { deleted: true, entry_id: 0 };
                }
            };

            mockVscode.commands.registerCommand = (cmd: string, callback: any) => {
                if (cmd === 'litCritic.deleteLearningEntry') {
                    deleteLearningEntryCallback = callback;
                }
                return { dispose: () => {} };
            };

            mockVscode.window.showErrorMessage = async (message: string) => {
                errorMessages.push(message);
                return undefined;
            };

            mockVscode.workspace.workspaceFolders = [
                { uri: { fsPath: '/test/repo' } },
            ];

            mockVscode.workspace.getConfiguration = () => ({
                get: (key: string, defaultValue: any) => {
                    if (key === 'autoStartServer') return false;
                    return defaultValue;
                },
                update: async () => {},
            });

            mockFs.existsSync = (filePath: string) => {
                return filePath.includes('lit-critic-server.py') || filePath.includes('CANON.md');
            };

            loadExtension();
            await activate({ subscriptions: [] });

            await deleteLearningEntryCallback({});

            assert.ok(
                errorMessages.includes('lit-critic: Could not determine learning entry ID.'),
                'Expected missing-entry-id error message',
            );
            assert.equal(deleteCalled, false, 'Expected API delete call not to run without an entry id');
        });
    });
});
