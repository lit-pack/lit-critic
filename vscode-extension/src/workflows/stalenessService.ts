import { ApiClient } from '../apiClient';
import { ScenesTreeProvider } from '../scenesTreeProvider';
import { KnowledgeTreeProvider } from '../knowledgeTreeProvider';
import { StalenessRegistry } from './stalenessRegistry';

// ---------------------------------------------------------------------------
// Deps interface
// ---------------------------------------------------------------------------

export interface StalenessServiceDeps {
    detectProjectPath: () => string | undefined;
    getServerManager: () => { isRunning: boolean } | undefined;
    ensureApiClient: () => ApiClient;
    stalenessRegistry: StalenessRegistry;
    scenesTreeProvider: ScenesTreeProvider;
    knowledgeTreeProvider: KnowledgeTreeProvider;
    log?: (msg: string) => void;
}

// ---------------------------------------------------------------------------
// recheckStaleness
// ---------------------------------------------------------------------------

/**
 * Re-query input staleness from the backend and push the results to all tree
 * providers. Called automatically after knowledge refresh and session re-run.
 * Returns the count of stale inputs found (0 = everything up to date).
 */
export async function recheckStaleness(deps: StalenessServiceDeps): Promise<number> {
    const projectPath = deps.detectProjectPath();
    if (!projectPath || !deps.getServerManager()?.isRunning) {
        return 0;
    }

    const client = deps.ensureApiClient();
    const result = await client.getInputStaleness(projectPath);
    deps.log?.(
        `[Staleness] response stale_inputs.length=${result.stale_inputs.length} ` +
        `paths=${JSON.stringify(result.stale_inputs.map((e) => e.path))} ` +
        `projectPath=${projectPath}`,
    );
    deps.stalenessRegistry.update(result.stale_inputs);

    // Push stale input paths to ScenesTreeProvider
    const staleInputPaths = new Set(result.stale_inputs.map((e) => e.path));
    deps.scenesTreeProvider.setStaleInputPaths(staleInputPaths);

    // Push stale entity keys to KnowledgeTreeProvider
    const hasAllStale = result.stale_inputs.some((e) => e.affected_knowledge === 'all');
    deps.knowledgeTreeProvider.setAllEntitiesStale(hasAllStale);
    if (!hasAllStale) {
        const staleEntityKeys = new Set<string>();
        for (const entry of result.stale_inputs) {
            const affected = entry.affected_knowledge;
            if (Array.isArray(affected)) {
                for (const k of affected) {
                    staleEntityKeys.add(`${k.category}:${k.entity_key}`);
                }
            }
        }
        deps.knowledgeTreeProvider.setStaleEntityKeys(staleEntityKeys);
    }

    // Push orphaned scene keys to KnowledgeTreeProvider
    const orphanedSceneKeys = new Set<string>(
        (result.orphaned_scenes ?? []).map((e) => e.scene_key),
    );
    deps.knowledgeTreeProvider.setOrphanedSceneKeys(orphanedSceneKeys);

    // The set* calls above already fire _onDidChangeTreeData on each provider,
    // causing VS Code to re-render badges using cached data. Full tree refreshes
    // (fetching fresh data from the server) are the responsibility of the caller
    // when data has actually changed (e.g. after knowledge refresh or analyze).
    return result.stale_inputs.length;
}
