import { WorkflowDeps } from './workflowController';

export async function cmdRefreshLearning(deps: WorkflowDeps): Promise<void> {
    try {
        await deps.runTrackedOperation(
            { id: 'refresh-learning', title: 'Refreshing learning data', statusMessage: 'Refreshing learning data...' },
            async () => {
                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) {
                    void deps.ui.showErrorMessage(
                        'lit-critic: Could not detect project directory (no CANON.md found in workspace).'
                    );
                    return;
                }
                const client = deps.getApiClient();
                deps.learningTreeProvider.setApiClient(client);
                deps.learningTreeProvider.setProjectPath(projectPath);
                await deps.learningTreeProvider.refresh();
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}

export async function cmdExportLearning(deps: WorkflowDeps): Promise<void> {
    try {
        await deps.runTrackedOperation(
            { id: 'export-learning', title: 'Exporting learning data', statusMessage: 'Exporting learning data...' },
            async () => {
                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) { return; }
                const client = deps.getApiClient();
                const result = await client.exportLearning(projectPath);
                void deps.ui.showInformationMessage(`lit-critic: LEARNING.md exported to ${result.path}`);
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        deps.presenter.setError(msg);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}

export async function cmdResetLearning(deps: WorkflowDeps): Promise<void> {
    try {
        await deps.runTrackedOperation(
            { id: 'reset-learning', title: 'Resetting learning data', statusMessage: 'Resetting learning data...' },
            async () => {
                const confirm = await deps.ui.showWarningMessage(
                    'Reset all learning data? This will delete all preferences, blind spots, and resolutions. This cannot be undone.',
                    true, 'Reset',
                );
                if (confirm !== 'Reset') { return; }

                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) { return; }

                await deps.getApiClient().resetLearning(projectPath);
                void deps.ui.showInformationMessage('lit-critic: Learning data reset.');
                await deps.learningTreeProvider.refresh();
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        deps.presenter.setError(msg);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}

export async function cmdDeleteLearningEntry(item: any, deps: WorkflowDeps): Promise<void> {
    try {
        await deps.runTrackedOperation(
            { id: 'delete-learning-entry', title: 'Deleting learning entry', statusMessage: 'Deleting learning entry...' },
            async () => {
                const entryId = typeof item === 'number'
                    ? item
                    : (item?.entryId ?? item?.entry?.id);

                if (!entryId) {
                    void deps.ui.showErrorMessage('lit-critic: Could not determine learning entry ID.');
                    return;
                }

                await deps.ensureServer();
                const projectPath = deps.detectProjectPath();
                if (!projectPath) { return; }

                await deps.getApiClient().deleteLearningEntry(entryId, projectPath);
                void deps.ui.showInformationMessage('lit-critic: Learning entry deleted.');
                await deps.learningTreeProvider.refresh();
            },
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void deps.ui.showErrorMessage(`lit-critic: ${msg}`);
    }
}
