import { strict as assert } from 'assert';

import { cmdSelectModel } from '../../vscode-extension/src/workflows/modelSelectionWorkflow';
import { WorkflowDeps } from '../../vscode-extension/src/workflows/workflowController';

// ---------------------------------------------------------------------------
// Canned server config
// ---------------------------------------------------------------------------

const cannedConfig = {
    api_key_configured: true,
    available_models: {
        sonnet: { label: 'Sonnet 4.5', provider: 'anthropic' },
        haiku: { label: 'Haiku 4.5', provider: 'anthropic' },
        opus: { label: 'Opus 4.6', provider: 'anthropic' },
    },
    default_model: 'sonnet',
    analysis_modes: ['quick', 'deep'],
    model_slots: { frontier: 'opus', deep: 'sonnet', quick: 'haiku' },
};

// ---------------------------------------------------------------------------
// Mock deps factory
// ---------------------------------------------------------------------------

function makeTrackedDeps(configOverrides: Record<string, any> = {}) {
    const infoMessages: string[] = [];
    const errorMessages: string[] = [];
    const configUpdates: Array<{ key: string; value: any; target: number }> = [];
    const quickPickCalls: Array<{ items: any[]; options: any }> = [];
    let quickPickResponses: any[] = [];
    let qpCallIndex = 0;

    const extConfig = {
        get: (key: string, defaultValue: any) => configOverrides[key] ?? defaultValue,
        inspect: () => undefined,
        update: async (key: string, value: any, target: number) => {
            configUpdates.push({ key, value, target });
        },
    };

    const deps: WorkflowDeps = {
        getApiClient: () => ({
            getConfig: async () => ({ ...cannedConfig }),
        } as any),
        ensureServer: async () => {},
        getServerManager: () => ({ isRunning: true, stop: () => {} } as any),
        state: {} as any,
        presenter: { setError: () => {} } as any,
        findingsTreeProvider: {} as any,
        learningTreeProvider: {} as any,
        knowledgeTreeProvider: {} as any,
        knowledgeTreeView: undefined,
        diagnosticsProvider: {} as any,
        ensureDiscussionPanel: () => ({} as any),
        getDiscussionPanel: () => undefined,
        runTrackedOperation: async (_p, op) => op(),
        detectProjectPath: () => '/project',
        ui: {
            showInformationMessage: async (msg: string) => { infoMessages.push(msg); return undefined; },
            showErrorMessage: async (msg: string) => { errorMessages.push(msg); return undefined; },
            showWarningMessage: async () => undefined,
            showInputBox: async () => undefined,
            showQuickPick: async (items: any[], options: any) => {
                quickPickCalls.push({ items, options });
                const resp = quickPickResponses[qpCallIndex++];
                return resp;
            },
            showOpenDialog: async () => undefined,
            showTextDocument: async () => ({}),
            withProgress: async (_t, task) => task({ report: () => {} }),
            navigateToFindingLine: async () => {},
            pathExists: () => true,
            getOpenTextDocumentPaths: () => [],
            getExtensionConfig: () => extConfig,
        },
    };

    return {
        deps,
        infoMessages,
        errorMessages,
        configUpdates,
        quickPickCalls,
        // Provide responses for successive quickPick calls
        setQuickPickResponses(...responses: any[]) {
            quickPickResponses = responses;
            qpCallIndex = 0;
        },
    };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('modelSelectionWorkflow — cmdSelectModel()', () => {
    it('user cancels picker — no writes', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponses(undefined);
        await cmdSelectModel(t.deps);
        assert.equal(t.configUpdates.length, 0);
    });

    it('selecting Sonnet writes analysisModel=sonnet and shows info message', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponses({ label: 'Sonnet', value: 'sonnet', description: 'Balanced analysis' });
        await cmdSelectModel(t.deps);
        assert.equal(t.configUpdates.length, 1);
        assert.equal(t.configUpdates[0].key, 'analysisModel');
        assert.equal(t.configUpdates[0].value, 'sonnet');
        assert.ok(t.infoMessages.some(m => m.includes('Sonnet')));
    });

    it('selecting Opus writes analysisModel=opus and shows info message', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponses({ label: 'Opus', value: 'opus', description: 'Deepest analysis' });
        await cmdSelectModel(t.deps);
        assert.equal(t.configUpdates.length, 1);
        assert.equal(t.configUpdates[0].key, 'analysisModel');
        assert.equal(t.configUpdates[0].value, 'opus');
        assert.ok(t.infoMessages.some(m => m.includes('Opus')));
    });

    it('selecting Haiku writes analysisModel=haiku and shows info message', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponses({ label: 'Haiku', value: 'haiku', description: 'Fast & cheap' });
        await cmdSelectModel(t.deps);
        assert.equal(t.configUpdates.length, 1);
        assert.equal(t.configUpdates[0].key, 'analysisModel');
        assert.equal(t.configUpdates[0].value, 'haiku');
        assert.ok(t.infoMessages.some(m => m.includes('Haiku')));
    });

    it('current model is marked as selected in picker items', async () => {
        const t = makeTrackedDeps({ analysisModel: 'haiku' });
        t.setQuickPickResponses(undefined); // cancel immediately
        await cmdSelectModel(t.deps);
        const firstPickCall = t.quickPickCalls[0];
        const haikuItem = firstPickCall?.items.find((i: any) => i.value === 'haiku');
        assert.ok(haikuItem, 'Expected haiku item in picker');
        assert.ok(haikuItem.detail?.includes('✓'), 'Expected current model to be marked as selected');
    });

    it('picker is shown exactly once', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponses({ label: 'Sonnet', value: 'sonnet' });
        await cmdSelectModel(t.deps);
        assert.equal(t.quickPickCalls.length, 1);
    });
});
