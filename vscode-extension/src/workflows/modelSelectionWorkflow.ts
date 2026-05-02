import { getConfiguredAnalysisModel } from '../domain/modelSelectionLogic';
import { WorkflowDeps } from './workflowController';

const MODEL_ITEMS = [
    {
        label: 'Opus',
        description: 'Deepest analysis — highest quality, highest cost',
        value: 'opus' as const,
    },
    {
        label: 'Sonnet',
        description: 'Balanced analysis — recommended default',
        value: 'sonnet' as const,
    },
    {
        label: 'Haiku',
        description: 'Fast & cheap — lighter analysis',
        value: 'haiku' as const,
    },
];

export async function cmdSelectModel(deps: WorkflowDeps): Promise<void> {
    try {
        const extConfig = deps.ui.getExtensionConfig();
        const currentModel = getConfiguredAnalysisModel(extConfig);

        const items = MODEL_ITEMS.map((m) => ({
            ...m,
            detail: m.value === currentModel ? '✓ Currently selected' : undefined,
        }));

        const selected = await deps.ui.showQuickPick(items, {
            placeHolder: 'Select analysis model',
            activeItemLabel: MODEL_ITEMS.find((m) => m.value === currentModel)?.label,
        });

        if (!selected) { return; }

        const nextValue = typeof selected === 'string' ? selected : selected.value;
        const writableConfig = extConfig as any;
        if (typeof writableConfig.update === 'function') {
            await writableConfig.update('analysisModel', nextValue, 2 /* Workspace */);
        }

        const label = MODEL_ITEMS.find((m) => m.value === nextValue)?.label ?? nextValue;
        void deps.ui.showInformationMessage(`lit-critic: Analysis model set to ${label}.`);
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}
