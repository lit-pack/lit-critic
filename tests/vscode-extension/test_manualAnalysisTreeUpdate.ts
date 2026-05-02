/**
 * Tests for manual analysis → Analysis tree integration.
 *
 * Verifies that when _cmdAnalyze completes with findings, the
 * analysisTreeProvider receives grouped findings per scene and
 * diagnosticsProvider is updated.
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
        showOpenDialog: async () => [{ fsPath: '/project/text/chapter-01.md' }],
        showTextDocument: async () => ({}),
        withProgress: async (_title: string, task: any) => task({ report: () => {} }),
        navigateToFindingLine: async () => {},
        pathExists: () => true,
        getOpenTextDocumentPaths: () => [],
        getExtensionConfig: () => ({
            get: (_k: string, d: any) => d,
            inspect: () => undefined,
        }),
        ...overrides,
    };
}

function makeSummary(overrides: Record<string, any> = {}) {
    return {
        total_findings: 2,
        counts: { critical: 0, major: 1, minor: 1 },
        model: { label: 'test-model' },
        discussion_model: undefined,
        scene_path: '/project/text/chapter-01.md',
        scene_paths: ['/project/text/chapter-01.md'],
        session_id: 'test-session',
        error: undefined,
        findings_status: [
            {
                number: 1,
                severity: 'major',
                lens: 'prose',
                location: 'Paragraph 3',
                line_start: 10,
                line_end: 12,
                evidence: 'Awkward phrasing.',
                status: 'active',
                scene_path: '/project/text/chapter-01.md',
            },
            {
                number: 2,
                severity: 'minor',
                lens: 'structure',
                location: 'Opening',
                line_start: 1,
                line_end: 3,
                evidence: 'Weak hook.',
                status: 'active',
                scene_path: '/project/text/chapter-01.md',
            },
        ],
        ...overrides,
    };
}

function createMockDeps(overrides: Record<string, any> = {}) {
    const analysisTreeSetFindingsCalls: Array<{ scenePath: string; findings: any[] }> = [];
    const diagnosticsUpdateCalls: any[] = [];
    const diagnosticsSetScenePathCalls: any[] = [];

    const { ui: uiOverrides, apiClient: apiClientOverrides, ...restOverrides } = overrides;

    const mockApiClient: any = {
        getInputStaleness: async (_projectPath: string) => ({
            stale_inputs: [{ path: '/project/text/chapter-01.md', type: 'scene' }],
        }),
        getAnalyzableScenes: async (_projectPath: string) => ({
            analyzable_scenes: [{ path: '/project/text/chapter-01.md', reason: 'stale' }],
        }),
        analyze: async () => makeSummary(apiClientOverrides?.summaryOverrides),
        getConfig: async () => undefined,
        streamAnalysisProgress: (_onEvent: any, onEnd: any, _onError: any) => {
            // Immediately close the stream
            onEnd();
        },
        ...apiClientOverrides,
    };

    const deps: any = {
        detectProjectPath: () => '/test/project',
        getApiClient: () => mockApiClient,
        ensureServer: async () => {},
        getServerManager: () => ({ stop: () => {}, isRunning: true }),
        state: { allFindings: [], totalFindings: 0 },
        presenter: {
            setAnalyzing: () => {},
            setError: () => {},
        },
        findingsTreeProvider: {
            setFindings: () => {},
            clear: () => {},
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
            setScenePath: (...args: any[]) => { diagnosticsSetScenePathCalls.push(args); },
            updateFromFindings: (findings: any) => { diagnosticsUpdateCalls.push(findings); },
            clear: () => {},
        },
        analysisTreeProvider: {
            setFindings: (scenePath: string, findings: any[]) => {
                analysisTreeSetFindingsCalls.push({ scenePath, findings });
            },
            clear: () => {},
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
        analysisTreeSetFindingsCalls,
        diagnosticsUpdateCalls,
        diagnosticsSetScenePathCalls,
    };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Manual analysis → Analysis tree update', () => {
    let WorkflowController: any;

    beforeEach(() => {
        const mod = proxyquire('../../vscode-extension/src/workflows/workflowController', {
            '../apiClient': {},
            '../analysisTreeProvider': {},
            '../diagnosticsProvider': {},
            '../findingsTreeProvider': {},
            '../learningTreeProvider': {},
            '../ui/workbenchPresenter': {
                formatModeCostHint: () => undefined,
                formatTierCostSummary: () => undefined,
            },
            '../domain/modelSelectionLogic': {
                buildAnalysisStartStatusMessage: () => 'Analyzing...',
                getConfiguredAnalysisModel: () => 'sonnet',
            },
            '../types': {},
            './stateStore': {},
            './learningWorkflowHandlers': {},
            './knowledgeWorkflowHandlers': {},
            './modelSelectionWorkflow': {},
            path: require('path'),
        });
        WorkflowController = mod.WorkflowController;
    });

    it('feeds findings into analysisTreeProvider grouped by scene after successful analysis', async () => {
        const { deps, analysisTreeSetFindingsCalls, diagnosticsUpdateCalls } = createMockDeps();
        const ctrl = new WorkflowController(deps);

        await ctrl.cmdAnalyze();

        // analysisTreeProvider.setFindings should have been called once for the single scene
        assert.equal(analysisTreeSetFindingsCalls.length, 1, 'Expected 1 setFindings call for 1 scene');
        assert.equal(
            analysisTreeSetFindingsCalls[0].scenePath,
            '/project/text/chapter-01.md',
        );
        assert.equal(analysisTreeSetFindingsCalls[0].findings.length, 2);

        // diagnosticsProvider should also have been updated
        assert.equal(diagnosticsUpdateCalls.length, 1);
    });

    it('groups findings by scene_path when multiple scenes are returned', async () => {
        const multiSceneSummary = {
            summaryOverrides: {
                total_findings: 3,
                counts: { critical: 1, major: 1, minor: 1 },
                scene_paths: ['/project/text/ch01.md', '/project/text/ch02.md'],
                findings_status: [
                    {
                        number: 1, severity: 'critical', lens: 'prose',
                        location: 'P1', line_start: 1, line_end: 2,
                        evidence: 'E1', status: 'active',
                        scene_path: '/project/text/ch01.md',
                    },
                    {
                        number: 2, severity: 'major', lens: 'structure',
                        location: 'P2', line_start: 5, line_end: 7,
                        evidence: 'E2', status: 'active',
                        scene_path: '/project/text/ch02.md',
                    },
                    {
                        number: 3, severity: 'minor', lens: 'prose',
                        location: 'P3', line_start: 10, line_end: 12,
                        evidence: 'E3', status: 'active',
                        scene_path: '/project/text/ch01.md',
                    },
                ],
            },
        };

        const { deps, analysisTreeSetFindingsCalls } = createMockDeps({
            apiClient: {
                analyze: async () => makeSummary(multiSceneSummary.summaryOverrides),
                getConfig: async () => undefined,
                streamAnalysisProgress: (_onEvent: any, onEnd: any) => { onEnd(); },
            },
        });
        const ctrl = new WorkflowController(deps);

        await ctrl.cmdAnalyze();

        // Should be 2 calls: one per scene
        assert.equal(analysisTreeSetFindingsCalls.length, 2, 'Expected 2 setFindings calls for 2 scenes');

        const ch01Call = analysisTreeSetFindingsCalls.find(
            (c: any) => c.scenePath === '/project/text/ch01.md',
        );
        const ch02Call = analysisTreeSetFindingsCalls.find(
            (c: any) => c.scenePath === '/project/text/ch02.md',
        );
        assert.ok(ch01Call, 'Missing setFindings call for ch01');
        assert.ok(ch02Call, 'Missing setFindings call for ch02');
        assert.equal(ch01Call!.findings.length, 2, 'ch01 should have 2 findings');
        assert.equal(ch02Call!.findings.length, 1, 'ch02 should have 1 finding');
    });

    it('does not call analysisTreeProvider.setFindings when no findings_status in summary', async () => {
        const { deps, analysisTreeSetFindingsCalls } = createMockDeps({
            apiClient: {
                analyze: async () => makeSummary({ findings_status: undefined }),
                getConfig: async () => undefined,
                streamAnalysisProgress: (_onEvent: any, onEnd: any) => { onEnd(); },
            },
        });
        const ctrl = new WorkflowController(deps);

        await ctrl.cmdAnalyze();

        assert.equal(analysisTreeSetFindingsCalls.length, 0);
    });

    it('skips analysisTreeProvider when it is undefined', async () => {
        const { deps } = createMockDeps();
        deps.analysisTreeProvider = undefined;
        const ctrl = new WorkflowController(deps);

        // Should not throw
        await ctrl.cmdAnalyze();
    });

    it('uses summary.scene_path as fallback when finding has no scene_path', async () => {
        const noScenePathSummary = {
            findings_status: [
                {
                    number: 1, severity: 'major', lens: 'prose',
                    location: 'P1', line_start: 1, line_end: 2,
                    evidence: 'E1', status: 'active',
                    // No scene_path on the finding
                },
            ],
        };

        const { deps, analysisTreeSetFindingsCalls } = createMockDeps({
            apiClient: {
                analyze: async () => makeSummary(noScenePathSummary),
                getConfig: async () => undefined,
                streamAnalysisProgress: (_onEvent: any, onEnd: any) => { onEnd(); },
            },
        });
        const ctrl = new WorkflowController(deps);

        await ctrl.cmdAnalyze();

        assert.equal(analysisTreeSetFindingsCalls.length, 1);
        // Falls back to summary.scene_path
        assert.equal(
            analysisTreeSetFindingsCalls[0].scenePath,
            '/project/text/chapter-01.md',
        );
    });
});
