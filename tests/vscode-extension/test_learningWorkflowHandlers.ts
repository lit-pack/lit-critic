import { strict as assert } from 'assert';

import {
    cmdRefreshLearning,
    cmdExportLearning,
    cmdResetLearning,
    cmdDeleteLearningEntry,
} from '../../vscode-extension/src/workflows/learningWorkflowHandlers';
import { WorkflowDeps } from '../../vscode-extension/src/workflows/workflowController';

// ---------------------------------------------------------------------------
// Mock deps factory
// ---------------------------------------------------------------------------

function makeDeps(overrides: Partial<WorkflowDeps> = {}): WorkflowDeps & {
    infoMessages: string[];
    errorMessages: string[];
    warningMessages: string[];
    learningRefreshCalls: number;
    learningSetApiClientCalls: string[];
    deleteLearningEntryCalls: Array<{ entryId: number; projectPath: string }>;
    exportLearningCalls: string[];
    resetLearningCalls: string[];
    presenterErrors: string[];
} {
    const infoMessages: string[] = [];
    const errorMessages: string[] = [];
    const warningMessages: string[] = [];
    const learningRefreshCalls: number[] = [];
    const learningSetApiClientCalls: string[] = [];
    const deleteLearningEntryCalls: Array<{ entryId: number; projectPath: string }> = [];
    const exportLearningCalls: string[] = [];
    const resetLearningCalls: string[] = [];
    const presenterErrors: string[] = [];

    const deps: WorkflowDeps = {
        getApiClient: () => ({
            exportLearning: async (projectPath: string) => {
                exportLearningCalls.push(projectPath);
                return { path: '/project/LEARNING.md' };
            },
            resetLearning: async (projectPath: string) => {
                resetLearningCalls.push(projectPath);
                return {};
            },
            deleteLearningEntry: async (entryId: number, projectPath: string) => {
                deleteLearningEntryCalls.push({ entryId, projectPath });
                return { deleted: true, entry_id: entryId };
            },
        } as any),
        ensureServer: async () => {},
        getServerManager: () => ({ isRunning: true, stop: () => {} } as any),
        state: {
            allFindings: [],
            currentFindingIndex: 0,
            totalFindings: 0,
            indexChangeDismissed: false,
        } as any,
        presenter: {
            setError: (msg: string) => presenterErrors.push(msg),
            setReady: () => {},
            setAnalyzing: () => {},
        } as any,
        findingsTreeProvider: {} as any,
        learningTreeProvider: {
            setApiClient: (client: any) => learningSetApiClientCalls.push('set'),
            setProjectPath: () => {},
            refresh: async () => { learningRefreshCalls.push(1); },
        } as any,
        knowledgeTreeProvider: {} as any,
        knowledgeTreeView: undefined,
        diagnosticsProvider: {} as any,
        ensureDiscussionPanel: () => ({ show: () => {}, close: () => {} } as any),
        getDiscussionPanel: () => undefined,
        runTrackedOperation: async (_profile, operation) => operation(),
        detectProjectPath: () => '/project',
        ui: {
            showInformationMessage: async (msg: string) => { infoMessages.push(msg); return undefined; },
            showErrorMessage: async (msg: string) => { errorMessages.push(msg); return undefined; },
            showWarningMessage: async (msg: string, _modal: boolean, ...items: string[]) => {
                warningMessages.push(msg);
                return items[0]; // default: return first button (confirm)
            },
            showInputBox: async () => undefined,
            showQuickPick: async () => undefined,
            showOpenDialog: async () => undefined,
            showTextDocument: async () => ({}),
            withProgress: async (_title, task) => task({ report: () => {} }),
            navigateToFindingLine: async () => {},
            pathExists: () => true,
            getOpenTextDocumentPaths: () => [],
            getExtensionConfig: () => ({ get: (_k: string, def: any) => def, inspect: () => undefined }),
        },
        ...overrides,
    };

    return {
        ...deps,
        infoMessages,
        errorMessages,
        warningMessages,
        learningRefreshCalls: learningRefreshCalls.length as any,
        learningSetApiClientCalls,
        deleteLearningEntryCalls,
        exportLearningCalls,
        resetLearningCalls,
        presenterErrors,
    } as any;
}

// Re-implement with tracking as actual getters
function makeTrackedDeps(overrides: Partial<WorkflowDeps> = {}) {
    const infoMessages: string[] = [];
    const errorMessages: string[] = [];
    const warningMessages: string[] = [];
    let learningRefreshCount = 0;
    const learningSetApiClientCalls: string[] = [];
    const deleteLearningEntryCalls: Array<{ entryId: number; projectPath: string }> = [];
    const exportLearningCalls: string[] = [];
    const resetLearningCalls: string[] = [];
    const presenterErrors: string[] = [];
    let warningResponse: string | undefined = 'Reset'; // default: confirm

    const deps: WorkflowDeps = {
        getApiClient: () => ({
            exportLearning: async (projectPath: string) => {
                exportLearningCalls.push(projectPath);
                return { path: '/project/LEARNING.md' };
            },
            resetLearning: async (projectPath: string) => {
                resetLearningCalls.push(projectPath);
                return {};
            },
            deleteLearningEntry: async (entryId: number, projectPath: string) => {
                deleteLearningEntryCalls.push({ entryId, projectPath });
                return { deleted: true, entry_id: entryId };
            },
        } as any),
        ensureServer: async () => {},
        getServerManager: () => ({ isRunning: true, stop: () => {} } as any),
        state: {
            allFindings: [],
            currentFindingIndex: 0,
            totalFindings: 0,
            indexChangeDismissed: false,
        } as any,
        presenter: {
            setError: (msg: string) => presenterErrors.push(msg),
            setReady: () => {},
            setAnalyzing: () => {},
        } as any,
        findingsTreeProvider: {} as any,
        learningTreeProvider: {
            setApiClient: (_client: any) => learningSetApiClientCalls.push('set'),
            setProjectPath: () => {},
            refresh: async () => { learningRefreshCount++; },
        } as any,
        knowledgeTreeProvider: {} as any,
        knowledgeTreeView: undefined,
        diagnosticsProvider: {} as any,
        ensureDiscussionPanel: () => ({ show: () => {}, close: () => {} } as any),
        getDiscussionPanel: () => undefined,
        runTrackedOperation: async (_profile, operation) => operation(),
        detectProjectPath: () => '/project',
        ui: {
            showInformationMessage: async (msg: string) => { infoMessages.push(msg); return undefined; },
            showErrorMessage: async (msg: string) => { errorMessages.push(msg); return undefined; },
            showWarningMessage: async (_msg: string, _modal: boolean, ...items: string[]) => {
                warningMessages.push(_msg);
                return warningResponse;
            },
            showInputBox: async () => undefined,
            showQuickPick: async () => undefined,
            showOpenDialog: async () => undefined,
            showTextDocument: async () => ({}),
            withProgress: async (_title, task) => task({ report: () => {} }),
            navigateToFindingLine: async () => {},
            pathExists: () => true,
            getOpenTextDocumentPaths: () => [],
            getExtensionConfig: () => ({ get: (_k: string, def: any) => def, inspect: () => undefined }),
        },
        ...overrides,
    };

    return {
        deps,
        infoMessages,
        errorMessages,
        warningMessages,
        get learningRefreshCount() { return learningRefreshCount; },
        learningSetApiClientCalls,
        deleteLearningEntryCalls,
        exportLearningCalls,
        resetLearningCalls,
        presenterErrors,
        setWarningResponse(resp: string | undefined) { warningResponse = resp; },
    };
}

// ---------------------------------------------------------------------------
// cmdRefreshLearning
// ---------------------------------------------------------------------------

describe('learningWorkflowHandlers — cmdRefreshLearning()', () => {
    it('sets apiClient and projectPath on learningTreeProvider and refreshes', async () => {
        const t = makeTrackedDeps();
        await cmdRefreshLearning(t.deps);
        assert.equal(t.learningSetApiClientCalls.length, 1);
        assert.equal(t.learningRefreshCount, 1);
    });

    it('shows error and early-exits when no project path', async () => {
        const t = makeTrackedDeps({
            detectProjectPath: () => undefined,
        });
        await cmdRefreshLearning(t.deps);
        assert.ok(t.errorMessages.some(m => m.includes('Could not detect project directory')));
        assert.equal(t.learningRefreshCount, 0);
    });
});

// ---------------------------------------------------------------------------
// cmdExportLearning
// ---------------------------------------------------------------------------

describe('learningWorkflowHandlers — cmdExportLearning()', () => {
    it('calls exportLearning with projectPath and shows info message', async () => {
        const t = makeTrackedDeps();
        await cmdExportLearning(t.deps);
        assert.equal(t.exportLearningCalls.length, 1);
        assert.equal(t.exportLearningCalls[0], '/project');
        assert.ok(t.infoMessages.some(m => m.includes('LEARNING.md exported')));
    });

    it('early-exits silently when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });
        await cmdExportLearning(t.deps);
        assert.equal(t.exportLearningCalls.length, 0);
        assert.equal(t.infoMessages.length, 0);
    });

    it('shows error message and sets presenter error on API failure', async () => {
        const t = makeTrackedDeps({
            getApiClient: () => ({
                exportLearning: async () => { throw new Error('API error'); },
            } as any),
        });
        await cmdExportLearning(t.deps);
        assert.ok(t.errorMessages.some(m => m.includes('API error')));
        assert.ok(t.presenterErrors.length > 0);
    });
});

// ---------------------------------------------------------------------------
// cmdResetLearning
// ---------------------------------------------------------------------------

describe('learningWorkflowHandlers — cmdResetLearning()', () => {
    it('calls resetLearning and refreshes learning tree when user confirms', async () => {
        const t = makeTrackedDeps();
        t.setWarningResponse('Reset');
        await cmdResetLearning(t.deps);
        assert.equal(t.resetLearningCalls.length, 1);
        assert.equal(t.resetLearningCalls[0], '/project');
        assert.equal(t.learningRefreshCount, 1);
        assert.ok(t.infoMessages.some(m => m.includes('Learning data reset')));
    });

    it('does nothing when user cancels the warning', async () => {
        const t = makeTrackedDeps();
        t.setWarningResponse(undefined); // user dismissed
        await cmdResetLearning(t.deps);
        assert.equal(t.resetLearningCalls.length, 0);
        assert.equal(t.learningRefreshCount, 0);
    });

    it('early-exits silently when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });
        t.setWarningResponse('Reset');
        await cmdResetLearning(t.deps);
        assert.equal(t.resetLearningCalls.length, 0);
    });
});

// ---------------------------------------------------------------------------
// cmdDeleteLearningEntry
// ---------------------------------------------------------------------------

describe('learningWorkflowHandlers — cmdDeleteLearningEntry()', () => {
    it('deletes entry when item has entryId property', async () => {
        const t = makeTrackedDeps();
        await cmdDeleteLearningEntry({ entryId: 42 }, t.deps);
        assert.equal(t.deleteLearningEntryCalls.length, 1);
        assert.equal(t.deleteLearningEntryCalls[0].entryId, 42);
        assert.equal(t.deleteLearningEntryCalls[0].projectPath, '/project');
        assert.ok(t.infoMessages.some(m => m.includes('Learning entry deleted')));
        assert.equal(t.learningRefreshCount, 1);
    });

    it('deletes entry when item has legacy { entry: { id } } shape', async () => {
        const t = makeTrackedDeps();
        await cmdDeleteLearningEntry({ entry: { id: 43 } }, t.deps);
        assert.equal(t.deleteLearningEntryCalls[0].entryId, 43);
    });

    it('deletes entry when item is a number', async () => {
        const t = makeTrackedDeps();
        await cmdDeleteLearningEntry(44, t.deps);
        assert.equal(t.deleteLearningEntryCalls[0].entryId, 44);
    });

    it('shows error and does not call API when entry ID is missing', async () => {
        const t = makeTrackedDeps();
        await cmdDeleteLearningEntry({}, t.deps);
        assert.ok(t.errorMessages.some(m => m.includes('Could not determine learning entry ID')));
        assert.equal(t.deleteLearningEntryCalls.length, 0);
    });

    it('early-exits silently when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });
        await cmdDeleteLearningEntry({ entryId: 42 }, t.deps);
        assert.equal(t.deleteLearningEntryCalls.length, 0);
    });
});
