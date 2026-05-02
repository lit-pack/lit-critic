import { strict as assert } from 'assert';

import {
    recheckStaleness,
    StalenessServiceDeps,
} from '../../vscode-extension/src/workflows/stalenessService';
import { StalenessRegistry } from '../../vscode-extension/src/workflows/stalenessRegistry';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStaleInput(overrides: Record<string, unknown> = {}) {
    return {
        path: '/project/ch1.txt',
        type: 'scene' as const,
        affected_knowledge: [] as any[],
        affected_sessions: [] as number[],
        ...overrides,
    };
}

function makeDeps(overrides: Partial<StalenessServiceDeps> = {}): StalenessServiceDeps & {
    scenesSetStaleInputPaths: Set<string>[];
    knowledgeSetAllEntitiesStale: boolean[];
    knowledgeSetStaleEntityKeys: Set<string>[];
    refreshCalls: string[];
} {
    const scenesSetStaleInputPaths: Set<string>[] = [];
    const knowledgeSetAllEntitiesStale: boolean[] = [];
    const knowledgeSetStaleEntityKeys: Set<string>[] = [];
    const refreshCalls: string[] = [];

    const scenesTreeProvider: any = {
        setStaleInputPaths: (s: Set<string>) => scenesSetStaleInputPaths.push(s),
        setApiClient: () => {},
        setProjectPath: () => {},
        refresh: async () => { refreshCalls.push('scenes'); },
    };

    const knowledgeTreeProvider: any = {
        setAllEntitiesStale: (v: boolean) => knowledgeSetAllEntitiesStale.push(v),
        setStaleEntityKeys: (s: Set<string>) => knowledgeSetStaleEntityKeys.push(s),
        setOrphanedSceneKeys: (_keys: Set<string>) => {},
        setApiClient: () => {},
        setProjectPath: () => {},
        refresh: async () => { refreshCalls.push('knowledge'); },
    };

    const deps: StalenessServiceDeps = {
        detectProjectPath: () => '/project',
        getServerManager: () => ({ isRunning: true }),
        ensureApiClient: () => ({
            getInputStaleness: async (_projectPath: string) => ({ stale_inputs: [] }),
        } as any),
        stalenessRegistry: new StalenessRegistry(),
        scenesTreeProvider,
        knowledgeTreeProvider,
        ...overrides,
    };

    return {
        ...deps,
        scenesSetStaleInputPaths,
        knowledgeSetAllEntitiesStale,
        knowledgeSetStaleEntityKeys,
        refreshCalls,
    };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('stalenessService — recheckStaleness()', () => {
    it('returns 0 when detectProjectPath returns undefined', async () => {
        const deps = makeDeps({ detectProjectPath: () => undefined });
        const result = await recheckStaleness(deps);
        assert.equal(result, 0);
        assert.equal(deps.refreshCalls.length, 0);
    });

    it('returns 0 when server is not running', async () => {
        const deps = makeDeps({ getServerManager: () => ({ isRunning: false }) });
        const result = await recheckStaleness(deps);
        assert.equal(result, 0);
        assert.equal(deps.refreshCalls.length, 0);
    });

    it('returns 0 when server manager is undefined', async () => {
        const deps = makeDeps({ getServerManager: () => undefined });
        const result = await recheckStaleness(deps);
        assert.equal(result, 0);
    });

    it('returns stale_inputs.length from the api response', async () => {
        const staleInputs = [
            makeStaleInput({ path: '/a.txt' }),
            makeStaleInput({ path: '/b.txt' }),
        ];
        const deps = makeDeps({
            ensureApiClient: () => ({
                getInputStaleness: async () => ({ stale_inputs: staleInputs }),
            } as any),
        });
        const result = await recheckStaleness(deps);
        assert.equal(result, 2);
    });

    it('returns 0 for empty stale_inputs', async () => {
        const deps = makeDeps();
        const result = await recheckStaleness(deps);
        assert.equal(result, 0);
    });

    it('updates the stalenessRegistry with stale_inputs', async () => {
        const staleInputs = [makeStaleInput({ path: '/ch1.txt' })];
        const deps = makeDeps({
            ensureApiClient: () => ({
                getInputStaleness: async () => ({ stale_inputs: staleInputs }),
            } as any),
        });
        await recheckStaleness(deps);
        assert.equal(deps.stalenessRegistry.isInputStale('/ch1.txt'), true);
        assert.equal(deps.stalenessRegistry.isInputStale('/ch2.txt'), false);
    });

    it('pushes stale input paths to scenesTreeProvider', async () => {
        const staleInputs = [
            makeStaleInput({ path: '/a.txt' }),
            makeStaleInput({ path: '/b.txt' }),
        ];
        const deps = makeDeps({
            ensureApiClient: () => ({
                getInputStaleness: async () => ({ stale_inputs: staleInputs }),
            } as any),
        });
        await recheckStaleness(deps);
        assert.equal(deps.scenesSetStaleInputPaths.length, 1);
        const pathSet = deps.scenesSetStaleInputPaths[0];
        assert.ok(pathSet.has('/a.txt'));
        assert.ok(pathSet.has('/b.txt'));
    });

    it('sets all entities stale when any entry has affected_knowledge=all', async () => {
        const staleInputs = [makeStaleInput({ affected_knowledge: 'all' })];
        const deps = makeDeps({
            ensureApiClient: () => ({
                getInputStaleness: async () => ({ stale_inputs: staleInputs }),
            } as any),
        });
        await recheckStaleness(deps);
        assert.equal(deps.knowledgeSetAllEntitiesStale[0], true);
        // setStaleEntityKeys should NOT be called when hasAllStale is true
        assert.equal(deps.knowledgeSetStaleEntityKeys.length, 0);
    });

    it('pushes specific stale entity keys when affected_knowledge is an array', async () => {
        const staleInputs = [
            makeStaleInput({
                affected_knowledge: [
                    { category: 'characters', entity_key: 'Alice' },
                    { category: 'terms', entity_key: 'sword' },
                ],
            }),
        ];
        const deps = makeDeps({
            ensureApiClient: () => ({
                getInputStaleness: async () => ({ stale_inputs: staleInputs }),
            } as any),
        });
        await recheckStaleness(deps);
        assert.equal(deps.knowledgeSetAllEntitiesStale[0], false);
        const keySet = deps.knowledgeSetStaleEntityKeys[0];
        assert.ok(keySet.has('characters:Alice'));
        assert.ok(keySet.has('terms:sword'));
    });

    // Test for stale session IDs removed — sessionsTreeProvider no longer in StalenessServiceDeps.

    it('does NOT call refresh() on tree providers — badge updates via set*() are sufficient', async () => {
        // recheckStaleness() is a lightweight staleness check. It updates tree
        // badges by calling setStaleInputPaths / setStaleEntityKeys
        // (which each fire _onDidChangeTreeData internally), so explicit refresh()
        // calls are redundant and wasteful. Full tree refreshes are the caller's
        // responsibility after data-changing operations (e.g. after knowledge refresh).
        const deps = makeDeps();
        await recheckStaleness(deps);
        assert.equal(deps.refreshCalls.length, 0);
    });

    it('passes projectPath to getInputStaleness', async () => {
        let capturedPath: string | undefined;
        const deps = makeDeps({
            detectProjectPath: () => '/custom/path',
            ensureApiClient: () => ({
                getInputStaleness: async (p: string) => {
                    capturedPath = p;
                    return { stale_inputs: [] };
                },
            } as any),
        });
        await recheckStaleness(deps);
        assert.equal(capturedPath, '/custom/path');
    });
});
