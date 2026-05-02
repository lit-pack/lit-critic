/**
 * StartupService — repo discovery, repo-path recovery, and server startup logic.
 *
 * Extracted from extension.ts so that startup branches can be unit-tested
 * without instantiating real VS Code APIs or a real ServerManager.
 *
 * All VS Code and filesystem interactions are injected through StartupPorts.
 */

import * as path from 'path';

import { REPO_MARKER, validateRepoPath } from '../repoPreflight';

// ---------------------------------------------------------------------------
// Port interface — injected by extension.ts with real VS Code/fs adapters
// ---------------------------------------------------------------------------

export interface StartupPorts {
    // Configuration
    getConfiguredRepoPath(): string;
    getAutoStartEnabled(): boolean;
    updateConfiguredRepoPath(value: string): Promise<void>;

    // File system
    pathExists(p: string): boolean;

    // Workspace
    getWorkspaceFolders(): Array<{ uri: { fsPath: string } }> | undefined;

    // VS Code UI — for recovery prompts
    showErrorModal(
        message: string,
        ...buttons: string[]
    ): Promise<string | undefined>;
    showFolderPicker(): Promise<string | undefined>;
    openSettings(settingKey: string): Promise<void>;
    getConfiguredRepoPathAfterSettingsEdit(): string;

    // Progress / status
    withProgressNotification(title: string, message: string, task: () => Promise<void>): Promise<void>;

    // Activity view reveal
    executeCommand(commandId: string): Promise<void>;
}

// ---------------------------------------------------------------------------
// StartupService class
// ---------------------------------------------------------------------------

export class StartupService {
    constructor(private readonly ports: StartupPorts) {}

    // -----------------------------------------------------------------------
    // Repo-root discovery
    // -----------------------------------------------------------------------

    /**
     * Find the repo root (directory containing REPO_MARKER).
     *
     * Resolution order:
     *   1. The `litCritic.repoPath` setting (explicit override).
     *   2. Walk up from each workspace folder.
     */
    findRepoRoot(): string | undefined {
        // 1. Explicit setting
        const configured = this.ports.getConfiguredRepoPath();
        if (configured) {
            const validation = validateRepoPath(configured);
            if (validation.ok) {
                return validation.path || configured;
            }
        }

        // 2. Walk up from workspace folders
        return this.findRepoRootFromWorkspace();
    }

    /**
     * Walk up from each workspace folder (up to 5 levels) looking for REPO_MARKER.
     */
    findRepoRootFromWorkspace(): string | undefined {
        const folders = this.ports.getWorkspaceFolders();
        if (!folders) {
            return undefined;
        }

        for (const folder of folders) {
            let dir = folder.uri.fsPath;
            for (let i = 0; i < 5; i++) {
                const marker = path.join(dir, REPO_MARKER);
                try {
                    if (this.ports.pathExists(marker)) {
                        return dir;
                    }
                } catch {
                    // ignore FS errors on any individual candidate
                }
                const parent = path.dirname(dir);
                if (parent === dir) {
                    break;
                }
                dir = parent;
            }
        }

        return undefined;
    }

    /**
     * Detect the project path (directory containing CANON.md) from workspace.
     */
    detectProjectPath(): string | undefined {
        const folders = this.ports.getWorkspaceFolders();
        if (!folders) {
            return undefined;
        }

        for (const folder of folders) {
            const canonPath = path.join(folder.uri.fsPath, 'CANON.md');
            if (this.ports.pathExists(canonPath)) {
                return folder.uri.fsPath;
            }
        }

        return undefined;
    }

    // -----------------------------------------------------------------------
    // Interactive repo-path recovery
    // -----------------------------------------------------------------------

    /**
     * Ensure a valid repo root exists, prompting the user interactively if not.
     *
     * Returns the validated repo path, or throws when the user cancels.
     */
    async ensureRepoRootWithRecovery(): Promise<string> {
        // Fast path: configured path is already valid.
        const configured = this.ports.getConfiguredRepoPath();
        const configuredValidation = validateRepoPath(configured || undefined);
        if (configuredValidation.ok) {
            return configuredValidation.path || configured;
        }

        // Fast path: workspace auto-detection is valid.
        const workspaceRoot = this.findRepoRootFromWorkspace();
        if (workspaceRoot) {
            const wsValidation = validateRepoPath(workspaceRoot);
            if (wsValidation.ok) {
                return wsValidation.path || workspaceRoot;
            }
        }

        // Interactive recovery loop.
        let currentMessage = configured
            ? configuredValidation.message
            : `Could not locate lit-critic installation (${REPO_MARKER}).`;

        // eslint-disable-next-line no-constant-condition
        while (true) {
            const action = await this.ports.showErrorModal(
                `lit-critic startup preflight failed. ${currentMessage}`,
                'Select Folder…',
                'Open Settings',
                'Cancel',
            );

            if (action === 'Cancel' || !action) {
                throw new Error('Repository path setup cancelled.');
            }

            if (action === 'Open Settings') {
                await this.ports.openSettings('litCritic.repoPath');
                const candidate = this.ports.getConfiguredRepoPathAfterSettingsEdit();
                const validation = validateRepoPath(candidate || undefined);
                if (validation.ok) {
                    return validation.path || candidate;
                }
                currentMessage = validation.message;
                continue;
            }

            // 'Select Folder…'
            const selected = await this.ports.showFolderPicker();
            if (!selected) {
                currentMessage = `No folder selected. Please choose a directory containing ${REPO_MARKER}.`;
                continue;
            }

            const validation = validateRepoPath(selected);
            if (!validation.ok) {
                currentMessage = validation.message;
                continue;
            }

            const normalized = validation.path || selected;
            await this.ports.updateConfiguredRepoPath(normalized);
            return normalized;
        }
    }

    // -----------------------------------------------------------------------
    // Server startup helpers
    // -----------------------------------------------------------------------

    /**
     * Start the server with a progress notification and set the presenter to
     * ready when done.  The caller is responsible for handling errors.
     *
     * `serverStart` and `syncRepoPath` are injected so this method remains
     * testable without a real ServerManager.
     */
    async startServerWithBusyUi(
        repoRoot: string,
        serverStart: () => Promise<void>,
        syncRepoPath: (p: string) => Promise<void>,
        setAnalyzing: (msg: string) => void,
        setReady: () => void,
    ): Promise<void> {
        setAnalyzing('Starting server...');
        await this.ports.withProgressNotification(
            'lit-critic: Starting server',
            'Launching lit-critic backend...',
            () => serverStart(),
        );

        // Keep repo-path sync best-effort; failures are non-fatal.
        await syncRepoPath(repoRoot).catch(() => undefined);

        setReady();
    }

    // -----------------------------------------------------------------------
    // Activity view reveal
    // -----------------------------------------------------------------------

    /**
     * If the current workspace is a detected lit-critic project (CANON.md
     * present), automatically reveal the lit-critic activity container.
     */
    async revealLitCriticActivityContainerIfProjectDetected(): Promise<void> {
        const projectPath = this.detectProjectPath();
        if (!projectPath) {
            return;
        }

        try {
            await this.ports.executeCommand('workbench.view.extension.lit-critic');
        } catch {
            // Non-fatal.
        }
    }
}
