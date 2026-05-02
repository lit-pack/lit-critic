import { KnowledgeEntityTreeItemPayload } from '../types';
import { WorkflowDeps } from './workflowController';

// ---------------------------------------------------------------------------
// Helper: resolve payload from various item shapes
// ---------------------------------------------------------------------------

export function resolveKnowledgeEntityPayload(item: any): KnowledgeEntityTreeItemPayload | null {
    const candidate = item?.payload ?? item;
    if (!candidate || typeof candidate !== 'object') {
        return null;
    }

    const entity = (candidate as Record<string, unknown>).entity;
    const overrideFields = (candidate as Record<string, unknown>).overrideFields;
    if (
        typeof (candidate as Record<string, unknown>).category !== 'string'
        || typeof (candidate as Record<string, unknown>).entityKey !== 'string'
        || typeof (candidate as Record<string, unknown>).label !== 'string'
        || !entity
        || typeof entity !== 'object'
        || !Array.isArray(overrideFields)
    ) {
        return null;
    }

    return candidate as KnowledgeEntityTreeItemPayload;
}

// ---------------------------------------------------------------------------
// Helper: editable fields
// ---------------------------------------------------------------------------

export function isEditableKnowledgeValue(value: unknown): boolean {
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

export function getEditableKnowledgeFields(payload: KnowledgeEntityTreeItemPayload): string[] {
    const entityFields = Object.entries(payload.entity)
        .filter(([fieldName, value]) => fieldName !== 'entity_key' && isEditableKnowledgeValue(value))
        .map(([fieldName]) => fieldName);
    return Array.from(new Set([...entityFields, ...payload.overrideFields]));
}

export function toKnowledgeFieldValue(payload: KnowledgeEntityTreeItemPayload, fieldName: string): string {
    const value = payload.entity[fieldName];
    if (typeof value === 'string') {
        return value;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value);
    }
    return '';
}

// ---------------------------------------------------------------------------
// Helper: refresh knowledge tree
// ---------------------------------------------------------------------------

export async function refreshKnowledgeTree(projectPath: string, deps: WorkflowDeps): Promise<void> {
    const client = deps.getApiClient();
    deps.knowledgeTreeProvider.setApiClient(client);
    deps.knowledgeTreeProvider.setProjectPath(projectPath);
    await deps.knowledgeTreeProvider.refresh();
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export async function cmdEditKnowledgeEntry(item: any, deps: WorkflowDeps): Promise<boolean> {
    if (item?.payload) {
        void deps.knowledgeTreeView?.reveal(item, { select: true, focus: false });
    }
    try {
        return await deps.runTrackedOperation(
            { id: 'edit-knowledge-entry', title: 'Editing knowledge entry', statusMessage: 'Editing knowledge entry...' },
            async () => {
                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) {
                    void deps.ui.showErrorMessage(
                        'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
                    );
                    return false;
                }

                const payload = resolveKnowledgeEntityPayload(item);
                if (!payload) {
                    void deps.ui.showErrorMessage('lit-critic: Could not determine knowledge entry to edit.');
                    return false;
                }

                const editableFields = getEditableKnowledgeFields(payload);
                if (editableFields.length === 0) {
                    void deps.ui.showErrorMessage('lit-critic: This knowledge entry has no editable fields.');
                    return false;
                }

                const presetFieldName = typeof item?.fieldName === 'string' ? item.fieldName : undefined;
                let fieldName = presetFieldName;
                if (!fieldName) {
                    const selectedField = await deps.ui.showQuickPick(
                        editableFields.map((candidateFieldName) => ({
                            label: candidateFieldName,
                            description: toKnowledgeFieldValue(payload, candidateFieldName) || 'No current value',
                        })),
                        {
                            placeHolder: `Choose a field to edit for ${payload.label}`,
                        },
                    );
                    if (!selectedField) {
                        return false;
                    }
                    fieldName = typeof selectedField === 'string' ? selectedField : selectedField.label;
                }

                if (!editableFields.includes(fieldName)) {
                    void deps.ui.showErrorMessage(`lit-critic: ${fieldName} is not editable for ${payload.label}.`);
                    return false;
                }

                const currentValue = toKnowledgeFieldValue(payload, fieldName);
                let value = typeof item?.value === 'string' ? item.value : undefined;
                if (value === undefined) {
                    value = await deps.ui.showInputBox({
                        prompt: `Edit ${fieldName} for ${payload.label}. Leave reset actions for removing overrides.`,
                        placeHolder: `Enter a new value for ${fieldName}`,
                        value: currentValue,
                        ignoreFocusOut: true,
                        validateInput: (nextValue: string) => nextValue.trim().length > 0
                            ? null
                            : 'Value cannot be empty. Use Reset Knowledge Override to remove an override.',
                    });
                    if (value === undefined) {
                        return false;
                    }
                }

                if (value.trim().length === 0) {
                    void deps.ui.showErrorMessage(
                        'lit-critic: Value cannot be empty. Use Reset Knowledge Override to remove an override.',
                    );
                    return false;
                }

                await deps.getApiClient().submitOverride(
                    payload.category,
                    payload.entityKey,
                    fieldName,
                    value,
                    projectPath,
                );
                await refreshKnowledgeTree(projectPath, deps);
                void deps.ui.showInformationMessage(
                    `lit-critic: Saved ${fieldName} override for ${payload.label}.`,
                );
                return true;
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
        return false;
    }
}

export async function cmdResetKnowledgeOverride(item: any, deps: WorkflowDeps): Promise<boolean> {
    try {
        return await deps.runTrackedOperation(
            { id: 'reset-knowledge-override', title: 'Resetting knowledge override', statusMessage: 'Resetting knowledge override...' },
            async () => {
                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) {
                    void deps.ui.showErrorMessage(
                        'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
                    );
                    return false;
                }

                const payload = resolveKnowledgeEntityPayload(item);
                if (!payload) {
                    void deps.ui.showErrorMessage('lit-critic: Could not determine knowledge entry to reset.');
                    return false;
                }

                if (payload.overrideFields.length === 0) {
                    void deps.ui.showErrorMessage('lit-critic: This knowledge entry has no overrides to reset.');
                    return false;
                }

                let fieldName = typeof item?.fieldName === 'string' ? item.fieldName : payload.overrideFields[0];
                if (!payload.overrideFields.includes(fieldName)) {
                    void deps.ui.showErrorMessage(`lit-critic: ${fieldName} is not overridden for ${payload.label}.`);
                    return false;
                }

                if (!item?.fieldName && payload.overrideFields.length > 1) {
                    const selectedField = await deps.ui.showQuickPick(
                        payload.overrideFields.map((overrideField) => ({
                            label: overrideField,
                            description: toKnowledgeFieldValue(payload, overrideField) || 'Overridden field',
                        })),
                        {
                            placeHolder: `Choose an override to reset for ${payload.label}`,
                            activeItemLabel: payload.overrideFields[0],
                        },
                    );
                    if (!selectedField) {
                        return false;
                    }
                    fieldName = typeof selectedField === 'string' ? selectedField : selectedField.label;
                }

                await deps.getApiClient().deleteOverride(
                    payload.category,
                    payload.entityKey,
                    fieldName,
                    projectPath,
                );
                await refreshKnowledgeTree(projectPath, deps);
                void deps.ui.showInformationMessage(
                    `lit-critic: Reset ${fieldName} override for ${payload.label}.`,
                );
                return true;
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
        return false;
    }
}

export async function cmdResetAllKnowledge(deps: WorkflowDeps): Promise<void> {
    const projectPath = deps.detectProjectPath();
    if (!projectPath) {
        void deps.ui.showErrorMessage(
            'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
        );
        return;
    }

    const answer = await deps.ui.showWarningMessage(
        'Reset all knowledge? This will delete all extracted entities, overrides and review flags. This cannot be undone.',
        true,
        'Reset',
    );
    if (answer !== 'Reset') {
        return;
    }

    try {
        await deps.getApiClient().resetAllKnowledge(projectPath);
        await refreshKnowledgeTree(projectPath, deps);
        void deps.ui.showInformationMessage('All knowledge has been reset.');
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}
