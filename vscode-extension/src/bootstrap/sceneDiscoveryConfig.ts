import * as vscode from 'vscode';
import { ApiClient } from '../apiClient';

// ---------------------------------------------------------------------------
// Scene discovery defaults
// ---------------------------------------------------------------------------

export const DEFAULT_SCENE_FOLDER = 'text';
export const DEFAULT_SCENE_EXTENSIONS = ['txt'];

// ---------------------------------------------------------------------------
// Debug trace (disabled by default)
// ---------------------------------------------------------------------------

// Set to true temporarily to diagnose startup scene-discovery behavior.
export const DEBUG_SCENES_TRACE = false;

export function debugScenesTrace(message: string, fields?: Record<string, unknown>): void {
    if (!DEBUG_SCENES_TRACE) {
        return;
    }
    if (fields) {
        console.log('[SCENES_TRACE]', message, fields);
        return;
    }
    console.log('[SCENES_TRACE]', message);
}

// ---------------------------------------------------------------------------
// Normalization helpers
// ---------------------------------------------------------------------------

export function normalizeSceneFolder(value: string | undefined): string {
    const trimmed = (value || '').trim();
    return trimmed || DEFAULT_SCENE_FOLDER;
}

export function normalizeSceneExtensions(value: string[] | undefined): string[] {
    const source = Array.isArray(value) ? value : [];
    const normalized: string[] = [];
    const seen = new Set<string>();

    for (const extension of source) {
        const cleaned = String(extension || '').trim().toLowerCase().replace(/^\.+/, '');
        if (!cleaned || seen.has(cleaned)) {
            continue;
        }
        seen.add(cleaned);
        normalized.push(cleaned);
    }

    return normalized.length > 0 ? normalized : [...DEFAULT_SCENE_EXTENSIONS];
}

// ---------------------------------------------------------------------------
// VS Code config accessors
// ---------------------------------------------------------------------------

export function getSceneDiscoverySettingsFromConfig(): { sceneFolder: string; sceneExtensions: string[] } {
    const config = vscode.workspace.getConfiguration('litCritic');
    const inspectFn = (config as any).inspect;
    const inspectedFolder = typeof inspectFn === 'function'
        ? inspectFn.call(config, 'sceneFolder')
        : undefined;
    const inspectedExtensions = typeof inspectFn === 'function'
        ? inspectFn.call(config, 'sceneExtensions')
        : undefined;
    const rawFolder = config.get<string>('sceneFolder', DEFAULT_SCENE_FOLDER);
    const rawExtensions = config.get<string[]>('sceneExtensions', [...DEFAULT_SCENE_EXTENSIONS]);
    const normalizedFolder = normalizeSceneFolder(rawFolder);
    const normalizedExtensions = normalizeSceneExtensions(rawExtensions);

    debugScenesTrace('getSceneDiscoverySettingsFromConfig', {
        rawFolder,
        rawExtensions,
        normalizedFolder,
        normalizedExtensions,
        folderInspect: {
            defaultValue: inspectedFolder?.defaultValue,
            globalValue: inspectedFolder?.globalValue,
            workspaceValue: inspectedFolder?.workspaceValue,
            workspaceFolderValue: inspectedFolder?.workspaceFolderValue,
        },
        extensionsInspect: {
            defaultValue: inspectedExtensions?.defaultValue,
            globalValue: inspectedExtensions?.globalValue,
            workspaceValue: inspectedExtensions?.workspaceValue,
            workspaceFolderValue: inspectedExtensions?.workspaceFolderValue,
        },
    });

    return {
        sceneFolder: normalizedFolder,
        sceneExtensions: normalizedExtensions,
    };
}

export async function syncSceneDiscoverySettingsToServer(client: ApiClient): Promise<void> {
    const { sceneFolder, sceneExtensions } = getSceneDiscoverySettingsFromConfig();
    debugScenesTrace('syncSceneDiscoverySettingsToServer payload', {
        sceneFolder,
        sceneExtensions,
    });
    await client.updateConfig({
        scene_folder: sceneFolder,
        scene_extensions: sceneExtensions,
    });
}
