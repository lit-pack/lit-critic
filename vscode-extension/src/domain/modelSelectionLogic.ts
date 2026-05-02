export interface AnalysisModelConfigReader {
    inspect<T>(section: string): {
        globalValue?: T;
        workspaceValue?: T;
        workspaceFolderValue?: T;
    } | undefined;
    get<T>(section: string, defaultValue: T): T;
}

export type AnalysisModel = 'opus' | 'sonnet' | 'haiku';

const VALID_ANALYSIS_MODELS: ReadonlySet<string> = new Set(['opus', 'sonnet', 'haiku']);

/**
 * Resolve the configured analysis model.
 *
 * Key: litCritic.analysisModel
 * Default: sonnet
 */
export function getConfiguredAnalysisModel(config: AnalysisModelConfigReader): AnalysisModel {
    const model = config.get<string>('analysisModel', 'sonnet');
    if (VALID_ANALYSIS_MODELS.has(model)) {
        return model as AnalysisModel;
    }
    return 'sonnet';
}

export function buildAnalysisStartStatusMessage(model: AnalysisModel = 'sonnet'): string {
    const labels: Record<AnalysisModel, string> = {
        opus: 'Running analysis (Opus)...',
        sonnet: 'Running analysis (Sonnet)...',
        haiku: 'Running analysis (Haiku)...',
    };
    return labels[model] ?? 'Running analysis...';
}
