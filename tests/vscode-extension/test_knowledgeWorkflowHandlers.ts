import { strict as assert } from 'assert';

import {
    cmdEditKnowledgeEntry,
    cmdResetKnowledgeOverride,
    cmdResetAllKnowledge,
    resolveKnowledgeEntityPayload,
    getEditableKnowledgeFields,
    toKnowledgeFieldValue,
} from '../../vscode-extension/src/workflows/knowledgeWorkflowHandlers';
import { WorkflowDeps } from '../../vscode-extension/src/workflows/workflowController';
import { KnowledgeEntityTreeItemPayload } from '../../vscode-extension/src/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePayload(overrides: Partial<KnowledgeEntityTreeItemPayload> = {}): KnowledgeEntityTreeItemPayload {
    return {
        category: 'characters',
        entityKey: 'alice',
        label: 'Alice',
        entity: { name: 'Alice', role: 'protagonist' },
        overrideFields: [],
        overrideCount: 0,
        hasOverrides: false,
        locked: false,
        ...overrides,
    };
}

function makeTrackedDeps(overrides: Partial<WorkflowDeps> = {}) {
    const infoMessages: string[] = [];
    const errorMessages: string[] = [];
    const submitOverrideCalls: Array<{ category: string; entityKey: string; fieldName: string; value: string; projectPath: string }> = [];
    const deleteOverrideCalls: Array<{ category: string; entityKey: string; fieldName: string; projectPath: string }> = [];
    let knowledgeRefreshCount = 0;
    const USE_FIRST = Symbol('USE_FIRST');
    let quickPickResponse: any = USE_FIRST;
    let inputBoxResponse: string | undefined = 'test value';

    const deps: WorkflowDeps = {
        getApiClient: () => ({
            submitOverride: async (category: string, entityKey: string, fieldName: string, value: string, projectPath: string) => {
                submitOverrideCalls.push({ category, entityKey, fieldName, value, projectPath });
                return {};
            },
            deleteOverride: async (category: string, entityKey: string, fieldName: string, projectPath: string) => {
                deleteOverrideCalls.push({ category, entityKey, fieldName, projectPath });
                return {};
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
            setError: () => {},
            setReady: () => {},
            setAnalyzing: () => {},
        } as any,
        findingsTreeProvider: {} as any,
        learningTreeProvider: {} as any,
        knowledgeTreeProvider: {
            setApiClient: () => {},
            setProjectPath: () => {},
            refresh: async () => { knowledgeRefreshCount++; },
            setFlaggedEntities: () => {},
            clearFlaggedEntities: () => {},
        } as any,
        knowledgeTreeView: { reveal: async () => {} },
        diagnosticsProvider: {} as any,
        ensureDiscussionPanel: () => ({ show: () => {} } as any),
        getDiscussionPanel: () => undefined,
        runTrackedOperation: async (_profile, operation) => operation(),
        detectProjectPath: () => '/project',
        ui: {
            showInformationMessage: async (msg: string) => { infoMessages.push(msg); return undefined; },
            showErrorMessage: async (msg: string) => { errorMessages.push(msg); return undefined; },
            showWarningMessage: async () => undefined,
            showInputBox: async () => inputBoxResponse,
            showQuickPick: async (items: any[]) => quickPickResponse === USE_FIRST ? items[0] : quickPickResponse,
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
        get knowledgeRefreshCount() { return knowledgeRefreshCount; },
        submitOverrideCalls,
        deleteOverrideCalls,
        setQuickPickResponse(resp: any) { quickPickResponse = resp; },
        resetQuickPickToFirst() { quickPickResponse = USE_FIRST; },
        setInputBoxResponse(resp: string | undefined) { inputBoxResponse = resp; },
    };
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

describe('knowledgeWorkflowHandlers — resolveKnowledgeEntityPayload()', () => {
    it('returns null for non-object', () => {
        assert.equal(resolveKnowledgeEntityPayload(null), null);
        assert.equal(resolveKnowledgeEntityPayload('string'), null);
    });

    it('returns null when required fields are missing', () => {
        assert.equal(resolveKnowledgeEntityPayload({ category: 'characters' }), null);
    });

    it('resolves from item.payload wrapper', () => {
        const payload = makePayload();
        const result = resolveKnowledgeEntityPayload({ payload });
        assert.ok(result);
        assert.equal(result!.entityKey, 'alice');
    });

    it('resolves from plain payload object', () => {
        const payload = makePayload();
        const result = resolveKnowledgeEntityPayload(payload);
        assert.ok(result);
    });
});

describe('knowledgeWorkflowHandlers — getEditableKnowledgeFields()', () => {
    it('returns scalar entity fields', () => {
        const payload = makePayload({ entity: { name: 'Alice', age: 30, active: true, nested: {} } });
        const fields = getEditableKnowledgeFields(payload);
        assert.ok(fields.includes('name'));
        assert.ok(fields.includes('age'));
        assert.ok(fields.includes('active'));
        assert.ok(!fields.includes('nested'));
        assert.ok(!fields.includes('entity_key'));
    });

    it('includes override fields even if not in entity', () => {
        const payload = makePayload({ overrideFields: ['custom_field'] });
        const fields = getEditableKnowledgeFields(payload);
        assert.ok(fields.includes('custom_field'));
    });
});

describe('knowledgeWorkflowHandlers — toKnowledgeFieldValue()', () => {
    it('returns string value as-is', () => {
        const payload = makePayload({ entity: { name: 'Alice' } });
        assert.equal(toKnowledgeFieldValue(payload, 'name'), 'Alice');
    });

    it('converts number to string', () => {
        const payload = makePayload({ entity: { age: 30 } });
        assert.equal(toKnowledgeFieldValue(payload, 'age'), '30');
    });

    it('returns empty string for missing field', () => {
        const payload = makePayload();
        assert.equal(toKnowledgeFieldValue(payload, 'missing'), '');
    });
});

// ---------------------------------------------------------------------------
// cmdEditKnowledgeEntry
// ---------------------------------------------------------------------------

describe('knowledgeWorkflowHandlers — cmdEditKnowledgeEntry()', () => {
    it('happy-path: submits override and returns true', async () => {
        const t = makeTrackedDeps();
        t.setInputBoxResponse('Alicia');
        const result = await cmdEditKnowledgeEntry(
            { ...makePayload(), fieldName: 'name' },
            t.deps,
        );
        assert.equal(result, true);
        assert.equal(t.submitOverrideCalls.length, 1);
        assert.equal(t.submitOverrideCalls[0].fieldName, 'name');
        assert.equal(t.submitOverrideCalls[0].value, 'Alicia');
        assert.ok(t.infoMessages.some(m => m.includes('Saved name override')));
        assert.ok(t.knowledgeRefreshCount > 0);
    });

    it('returns false when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });
        const result = await cmdEditKnowledgeEntry(makePayload(), t.deps);
        assert.equal(result, false);
        assert.equal(t.submitOverrideCalls.length, 0);
    });

    it('returns false when payload cannot be resolved', async () => {
        const t = makeTrackedDeps();
        const result = await cmdEditKnowledgeEntry({}, t.deps);
        assert.equal(result, false);
        assert.ok(t.errorMessages.some(m => m.includes('Could not determine knowledge entry')));
    });

    it('returns false when user cancels input box', async () => {
        const t = makeTrackedDeps();
        t.setInputBoxResponse(undefined);
        const result = await cmdEditKnowledgeEntry(
            { ...makePayload(), fieldName: 'name' },
            t.deps,
        );
        assert.equal(result, false);
        assert.equal(t.submitOverrideCalls.length, 0);
    });

    it('returns false and shows error when value is empty string', async () => {
        const t = makeTrackedDeps();
        const result = await cmdEditKnowledgeEntry(
            { ...makePayload(), fieldName: 'name', value: '' },
            t.deps,
        );
        assert.equal(result, false);
        assert.ok(t.errorMessages.some(m => m.includes('cannot be empty')));
    });

    it('shows field picker when no fieldName preset', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponse({ label: 'name' });
        t.setInputBoxResponse('Alicia');
        const result = await cmdEditKnowledgeEntry(makePayload(), t.deps);
        assert.equal(result, true);
        assert.equal(t.submitOverrideCalls[0].fieldName, 'name');
    });
});

// ---------------------------------------------------------------------------
// cmdResetKnowledgeOverride
// ---------------------------------------------------------------------------

describe('knowledgeWorkflowHandlers — cmdResetKnowledgeOverride()', () => {
    it('happy-path: deletes override and returns true', async () => {
        const t = makeTrackedDeps();
        const payload = makePayload({ overrideFields: ['name'], hasOverrides: true });
        const result = await cmdResetKnowledgeOverride(
            { ...payload, fieldName: 'name' },
            t.deps,
        );
        assert.equal(result, true);
        assert.equal(t.deleteOverrideCalls.length, 1);
        assert.equal(t.deleteOverrideCalls[0].fieldName, 'name');
        assert.ok(t.infoMessages.some(m => m.includes('Reset name override')));
        assert.ok(t.knowledgeRefreshCount > 0);
    });

    it('returns false when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });
        const result = await cmdResetKnowledgeOverride(makePayload({ overrideFields: ['name'] }), t.deps);
        assert.equal(result, false);
    });

    it('returns false when payload cannot be resolved', async () => {
        const t = makeTrackedDeps();
        const result = await cmdResetKnowledgeOverride({}, t.deps);
        assert.equal(result, false);
        assert.ok(t.errorMessages.some(m => m.includes('Could not determine knowledge entry')));
    });

    it('returns false when entry has no overrides', async () => {
        const t = makeTrackedDeps();
        const result = await cmdResetKnowledgeOverride(makePayload({ overrideFields: [] }), t.deps);
        assert.equal(result, false);
        assert.ok(t.errorMessages.some(m => m.includes('no overrides to reset')));
    });

    it('shows field picker when multiple override fields and no preset fieldName', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponse({ label: 'role' });
        const payload = makePayload({ overrideFields: ['name', 'role'], hasOverrides: true });
        const result = await cmdResetKnowledgeOverride(payload, t.deps);
        assert.equal(result, true);
        assert.equal(t.deleteOverrideCalls[0].fieldName, 'role');
    });

    it('returns false when user cancels field picker with multiple overrides', async () => {
        const t = makeTrackedDeps();
        t.setQuickPickResponse(undefined);
        const payload = makePayload({ overrideFields: ['name', 'role'], hasOverrides: true });
        const result = await cmdResetKnowledgeOverride(payload, t.deps);
        assert.equal(result, false);
        assert.equal(t.deleteOverrideCalls.length, 0);
    });
});

// ---------------------------------------------------------------------------
// cmdResetAllKnowledge
// ---------------------------------------------------------------------------

describe('knowledgeWorkflowHandlers — cmdResetAllKnowledge()', () => {
    it('calls resetAllKnowledge and refreshes tree when user confirms', async () => {
        let resetCalled = false;
        const t = makeTrackedDeps();
        t.deps.getApiClient = () => ({
            resetAllKnowledge: async (_pp: string) => { resetCalled = true; return { reset: true }; },
        } as any);
        (t.deps.ui as any).showWarningMessage = async () => 'Reset';

        await cmdResetAllKnowledge(t.deps);

        assert.ok(resetCalled, 'resetAllKnowledge should be called on confirm');
        assert.ok(t.knowledgeRefreshCount > 0, 'knowledge tree should be refreshed');
        assert.ok(t.infoMessages.some(m => m.includes('knowledge has been reset')));
    });

    it('does not call resetAllKnowledge when user dismisses the dialog', async () => {
        let resetCalled = false;
        const t = makeTrackedDeps();
        t.deps.getApiClient = () => ({
            resetAllKnowledge: async () => { resetCalled = true; return { reset: true }; },
        } as any);
        // Default showWarningMessage returns undefined (dismissed)

        await cmdResetAllKnowledge(t.deps);

        assert.ok(!resetCalled, 'resetAllKnowledge must not be called when dialog dismissed');
        assert.equal(t.knowledgeRefreshCount, 0, 'tree must not be refreshed on cancel');
    });

    it('shows error when no project path', async () => {
        const t = makeTrackedDeps({ detectProjectPath: () => undefined });

        await cmdResetAllKnowledge(t.deps);

        assert.ok(t.errorMessages.some(m => m.includes('Could not detect project')));
    });
});
