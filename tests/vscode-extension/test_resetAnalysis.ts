/**
 * Tests for the litCritic.resetAllAnalysis command handler.
 *
 * Covers: confirmation dialog, API call, tree/diagnostics clearing,
 * cancel path, missing project path, and API error handling.
 */

import { strict as assert } from 'assert';

declare const describe: (name: string, fn: () => void) => void;
declare const beforeEach: (fn: () => void) => void;
declare const it: (name: string, fn: () => Promise<void> | void) => void;

const proxyquire = require('proxyquire').noCallThru();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createMockUi(overrides: Record<string, any> = {}) {
    return {
        showInformationMessage: async (_msg: string, ..._items: string[]) => undefined,
        showErrorMessage: async (_msg: string, ..._items: string[]) => undefined,
        showWarningMessage: async (_msg: string, _modal: boolean, ..._items: string[]) => undefined,
        showInputBox: async () => undefined,
        showQuickPick: async () => undefined,
        showOpenDialog: async () => undefined,
        showTextDocument: async () => ({}),
        withProgress: async (_title: string, task: any) => task({ report: () => {} }),
        navigateToFindingLine: async () => {},
        pathExists: () => true,
        getOpenTextDocumentPaths: () => [],
        getExtensionConfig: () => ({ get: (_k: string, d: any) => d, inspect: () => undefined }),
        ...overrides,
    };
}

function createMockApiClient(overrides: Record<string, any> = {}) {
    return {
        deleteAllAnalysisSnapshots: async (_projectPath: string) => {},
        ...overrides,
    };
}

function createMockDeps(overrides: Record<string, any> = {}) {
    const analysisTreeClearCalls: any[] = [];
    const findingsTreeClearCalls: any[] = [];
    const diagnosticsClearCalls: any[] = [];

    // Extract known override keys so they don't clobber full mock objects
    const { ui: uiOverrides, apiClient: apiClientOverrides, detectProjectPath, ...restOverrides } = overrides;

    const deps: any = {
        detectProjectPath: detectProjectPath ?? (() => '/test/project'),
        getApiClient: () => createMockApiClient(apiClientOverrides),
        ensureServer: async () => {},
        getServerManager: () => ({ stop: () => {}, isRunning: true }),
        state: { get: () => undefined, set: () => {} },
        presenter: {},
        findingsTreeProvider: {
            clear: () => { findingsTreeClearCalls.push('clear'); },
        },
        learningTreeProvider: {
            setApiClient: () => {},
            setProjectPath: () => {},
            refresh: async () => {},
        },
        knowledgeTreeProvider: {
            setApiClient: () => {},
            setProjectPath: () => {},
            refresh: async () => {},
            setFlaggedEntities: () => {},
            clearFlaggedEntities: () => {},
        },
        diagnosticsProvider: {
            clear: () => { diagnosticsClearCalls.push('clear'); },
        },
        analysisTreeProvider: {
            clear: () => { analysisTreeClearCalls.push('clear'); },
        },
        ensureDiscussionPanel: () => ({}),
        getDiscussionPanel: () => undefined,
        runTrackedOperation: async (_profile: any, op: any) => op(),
        ui: createMockUi(uiOverrides),
        log: () => {},
        ...restOverrides,
    };

    return {
        deps,
        analysisTreeClearCalls,
        findingsTreeClearCalls,
        diagnosticsClearCalls,
    };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('cmdResetAllAnalysis', () => {
    let WorkflowController: any;

    // Stubs for modules imported by workflowController but irrelevant here
    const stubs: Record<string, any> = {};

    beforeEach(() => {
        const mod = proxyquire('../../vscode-extension/src/workflows/workflowController', {
            vscode: { '@noCallThru': true },
            ...stubs,
        });
        WorkflowController = mod.WorkflowController;
    });

    // -------------------------------------------------------------------
    // Confirmation dialog
    // -------------------------------------------------------------------

    it('shows a warning dialog with Reset button', async () => {
        let capturedMsg = '';
        let capturedModal = false;
        let capturedItems: string[] = [];

        const { deps } = createMockDeps({
            ui: {
                showWarningMessage: async (msg: string, modal: boolean, ...items: string[]) => {
                    capturedMsg = msg;
                    capturedModal = modal;
                    capturedItems = items;
                    return undefined; // user cancelled
                },
            },
        });

        const ctrl = new WorkflowController(deps);
        await ctrl.cmdResetAllAnalysis();

        assert.ok(capturedMsg.includes('Reset all analysis'), `Expected warning about reset, got: "${capturedMsg}"`);
        assert.equal(capturedModal, true, 'Expected modal dialog');
        assert.deepEqual(capturedItems, ['Reset'], 'Expected a single "Reset" button');
    });

    // -------------------------------------------------------------------
    // Confirm → clears everything
    // -------------------------------------------------------------------

    it('on confirm: clears UI state (no API call needed)', async () => {
        const { deps, analysisTreeClearCalls, findingsTreeClearCalls, diagnosticsClearCalls } = createMockDeps({
            ui: {
                showWarningMessage: async (_msg: string, _modal: boolean, ...items: string[]) => 'Reset',
            },
        });

        const ctrl = new WorkflowController(deps);
        await ctrl.cmdResetAllAnalysis();

        assert.equal(analysisTreeClearCalls.length, 1, 'Expected analysisTreeProvider.clear() called once');
        assert.equal(findingsTreeClearCalls.length, 1, 'Expected findingsTreeProvider.clear() called once');
        assert.equal(diagnosticsClearCalls.length, 1, 'Expected diagnosticsProvider.clear() called once');
    });

    it('on confirm: shows success info message', async () => {
        let infoMsg = '';

        const { deps } = createMockDeps({
            ui: {
                showWarningMessage: async () => 'Reset',
                showInformationMessage: async (msg: string) => { infoMsg = msg; return undefined; },
            },
        });

        const ctrl = new WorkflowController(deps);
        await ctrl.cmdResetAllAnalysis();

        assert.ok(infoMsg.includes('reset'), `Expected info message about reset, got: "${infoMsg}"`);
    });

    // -------------------------------------------------------------------
    // Cancel → does nothing
    // -------------------------------------------------------------------

    it('on cancel: does not call API or clear UI', async () => {
        let apiCalled = false;

        const { deps, analysisTreeClearCalls, findingsTreeClearCalls, diagnosticsClearCalls } = createMockDeps({
            ui: {
                showWarningMessage: async () => undefined, // user dismissed
            },
            apiClient: {
                resetAllSessions: async () => { apiCalled = true; },
            },
        });

        const ctrl = new WorkflowController(deps);
        await ctrl.cmdResetAllAnalysis();

        assert.equal(apiCalled, false, 'API should not be called on cancel');
        assert.equal(analysisTreeClearCalls.length, 0);
        assert.equal(findingsTreeClearCalls.length, 0);
        assert.equal(diagnosticsClearCalls.length, 0);
    });

    // -------------------------------------------------------------------
    // No project path → shows error
    // -------------------------------------------------------------------

    it('shows error when no project path detected', async () => {
        let errorMsg = '';

        const { deps } = createMockDeps({
            detectProjectPath: () => undefined,
            ui: {
                showErrorMessage: async (msg: string) => { errorMsg = msg; return undefined; },
            },
        });

        const ctrl = new WorkflowController(deps);
        await ctrl.cmdResetAllAnalysis();

        assert.ok(errorMsg.includes('project directory'), `Expected project-not-found error, got: "${errorMsg}"`);
    });


    // -------------------------------------------------------------------
    // analysisTreeProvider is optional — no crash when undefined
    // -------------------------------------------------------------------

    it('does not crash when analysisTreeProvider is undefined', async () => {
        const { deps } = createMockDeps({
            ui: {
                showWarningMessage: async () => 'Reset',
            },
        });
        deps.analysisTreeProvider = undefined;

        const ctrl = new WorkflowController(deps);
        // Should not throw
        await ctrl.cmdResetAllAnalysis();
    });
});
