import { strict as assert } from 'assert';
import * as path from 'path';

import { StartupService, StartupPorts } from '../../vscode-extension/src/bootstrap/startupService';
import { REPO_MARKER } from '../../vscode-extension/src/repoPreflight';

// ---------------------------------------------------------------------------
// The project root is one level up from the vscode-extension/ directory where
// mocha runs.  It contains lit-critic-server.py, which is required for
// validateRepoPath to return ok: true.
// ---------------------------------------------------------------------------
const PROJECT_ROOT = path.resolve(process.cwd(), '..');

// ---------------------------------------------------------------------------
// Fake StartupPorts factory — only override what each test needs
// ---------------------------------------------------------------------------

function makePorts(overrides: Partial<StartupPorts> = {}): StartupPorts {
    return {
        getConfiguredRepoPath: () => '',
        getAutoStartEnabled: () => true,
        updateConfiguredRepoPath: async (_v) => {},
        pathExists: (_p) => false,
        getWorkspaceFolders: () => undefined,
        showErrorModal: async (_msg, ..._btns) => 'Cancel',
        showFolderPicker: async () => undefined,
        openSettings: async (_key) => {},
        getConfiguredRepoPathAfterSettingsEdit: () => '',
        withProgressNotification: async (_title, _msg, task) => { await task(); },
        executeCommand: async (_cmd) => {},
        ...overrides,
    };
}

// ---------------------------------------------------------------------------
// findRepoRoot
// ---------------------------------------------------------------------------

describe('StartupService.findRepoRoot', () => {
    it('returns configured path when it points to a directory with the marker', () => {
        // Use the real project root as a valid path (lit-critic-server.py lives there).
        const ports = makePorts({
            getConfiguredRepoPath: () => PROJECT_ROOT,
            pathExists: (p) => p.includes(REPO_MARKER),
        });
        const svc = new StartupService(ports);
        const result = svc.findRepoRoot();
        // validateRepoPath checks the real filesystem; since PROJECT_ROOT does
        // contain lit-critic-server.py, the path is valid.
        assert.ok(result, 'should resolve configured path');
    });

    it('falls back to workspace walk when configured path is empty', () => {
        const fakeRoot = '/fake/project';
        const ports = makePorts({
            getConfiguredRepoPath: () => '',
            getWorkspaceFolders: () => [{ uri: { fsPath: fakeRoot } }],
            pathExists: (p) => p === path.join(fakeRoot, REPO_MARKER),
        });
        const svc = new StartupService(ports);
        const result = svc.findRepoRoot();
        assert.equal(result, fakeRoot);
    });

    it('returns undefined when no configured path and no workspace marker', () => {
        const ports = makePorts({
            getConfiguredRepoPath: () => '',
            getWorkspaceFolders: () => [{ uri: { fsPath: '/no/marker/here' } }],
            pathExists: () => false,
        });
        const svc = new StartupService(ports);
        const result = svc.findRepoRoot();
        assert.equal(result, undefined);
    });
});

// ---------------------------------------------------------------------------
// findRepoRootFromWorkspace
// ---------------------------------------------------------------------------

describe('StartupService.findRepoRootFromWorkspace', () => {
    it('returns undefined when workspace folders are undefined', () => {
        const svc = new StartupService(makePorts({ getWorkspaceFolders: () => undefined }));
        assert.equal(svc.findRepoRootFromWorkspace(), undefined);
    });

    it('finds marker at the direct folder level', () => {
        const root = '/my/repo';
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: root } }],
            pathExists: (p) => p === path.join(root, REPO_MARKER),
        });
        const svc = new StartupService(ports);
        assert.equal(svc.findRepoRootFromWorkspace(), root);
    });

    it('walks up parent directories and finds the marker', () => {
        const repoRoot = '/parent/repo';
        const deeper = `${repoRoot}/child/scene`;
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: deeper } }],
            pathExists: (p) => p === path.join(repoRoot, REPO_MARKER),
        });
        const svc = new StartupService(ports);
        assert.equal(svc.findRepoRootFromWorkspace(), repoRoot);
    });

    it('returns undefined when marker is not found within 5 levels', () => {
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: '/a/b/c/d/e/f' } }],
            pathExists: () => false,
        });
        const svc = new StartupService(ports);
        assert.equal(svc.findRepoRootFromWorkspace(), undefined);
    });
});

// ---------------------------------------------------------------------------
// detectProjectPath
// ---------------------------------------------------------------------------

describe('StartupService.detectProjectPath', () => {
    it('returns undefined when no workspace folders', () => {
        const svc = new StartupService(makePorts({ getWorkspaceFolders: () => undefined }));
        assert.equal(svc.detectProjectPath(), undefined);
    });

    it('returns the folder that contains CANON.md', () => {
        const projectDir = '/my/novel';
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: projectDir } }],
            pathExists: (p) => p === path.join(projectDir, 'CANON.md'),
        });
        const svc = new StartupService(ports);
        assert.equal(svc.detectProjectPath(), projectDir);
    });

    it('returns undefined when CANON.md is absent', () => {
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: '/no/canon/here' } }],
            pathExists: () => false,
        });
        const svc = new StartupService(ports);
        assert.equal(svc.detectProjectPath(), undefined);
    });
});

// ---------------------------------------------------------------------------
// ensureRepoRootWithRecovery
// ---------------------------------------------------------------------------

describe('StartupService.ensureRepoRootWithRecovery', () => {
    it('returns immediately when configured path already valid (uses real fs, project root)', async () => {
        const ports = makePorts({
            // Feed back the real project root — it contains lit-critic-server.py
            getConfiguredRepoPath: () => PROJECT_ROOT,
        });
        const svc = new StartupService(ports);
        const result = await svc.ensureRepoRootWithRecovery();
        assert.ok(result.length > 0);
    });

    it('returns workspace root when configured path is empty but workspace root is valid', async () => {
        const ports = makePorts({
            getConfiguredRepoPath: () => '',
            getWorkspaceFolders: () => [{ uri: { fsPath: PROJECT_ROOT } }],
            // pathExists is used inside findRepoRootFromWorkspace to locate the
            // marker. PROJECT_ROOT contains lit-critic-server.py so this returns true.
            pathExists: (p) => p.endsWith(REPO_MARKER),
        });
        const svc = new StartupService(ports);
        const result = await svc.ensureRepoRootWithRecovery();
        assert.ok(result.length > 0);
    });

    it('throws when user clicks Cancel', async () => {
        const ports = makePorts({
            getConfiguredRepoPath: () => '/nonexistent/path',
            getWorkspaceFolders: () => undefined,
            showErrorModal: async () => 'Cancel',
        });
        const svc = new StartupService(ports);
        await assert.rejects(
            () => svc.ensureRepoRootWithRecovery(),
            /cancelled/i,
        );
    });

    it('throws when modal is dismissed without action', async () => {
        const ports = makePorts({
            getConfiguredRepoPath: () => '/nonexistent/path',
            getWorkspaceFolders: () => undefined,
            showErrorModal: async () => undefined,
        });
        const svc = new StartupService(ports);
        await assert.rejects(
            () => svc.ensureRepoRootWithRecovery(),
            /cancelled/i,
        );
    });

    it('loops again when folder picker is dismissed without selection', async () => {
        let modalCallCount = 0;
        const ports = makePorts({
            getConfiguredRepoPath: () => '/bad/path',
            getWorkspaceFolders: () => undefined,
            showErrorModal: async () => {
                modalCallCount += 1;
                // First call: pick folder (returns nothing); second call: cancel
                return modalCallCount === 1 ? 'Select Folder…' : 'Cancel';
            },
            showFolderPicker: async () => undefined, // dismiss
        });
        const svc = new StartupService(ports);
        await assert.rejects(() => svc.ensureRepoRootWithRecovery(), /cancelled/i);
        assert.equal(modalCallCount, 2);
    });

    it('persists and returns chosen folder path when valid folder is selected', async () => {
        let savedPath = '';
        const ports = makePorts({
            getConfiguredRepoPath: () => '/invalid/path',
            getWorkspaceFolders: () => undefined,
            showErrorModal: async () => 'Select Folder…',
            // Use the real project root — it contains lit-critic-server.py so
            // validateRepoPath will return ok: true and exit the loop.
            showFolderPicker: async () => PROJECT_ROOT,
            updateConfiguredRepoPath: async (v) => { savedPath = v; },
        });
        const svc = new StartupService(ports);
        const result = await svc.ensureRepoRootWithRecovery();
        assert.ok(result.length > 0);
        assert.ok(savedPath.length > 0, 'should have persisted the chosen path');
    });

    it('re-reads config after Open Settings and returns if now valid', async () => {
        let settingsOpened = false;
        const ports = makePorts({
            getConfiguredRepoPath: () => '/invalid/before-settings',
            getWorkspaceFolders: () => undefined,
            showErrorModal: async () => {
                return settingsOpened ? 'Cancel' : 'Open Settings';
            },
            openSettings: async (_key) => { settingsOpened = true; },
            // After settings are opened, return the real project root which is valid.
            getConfiguredRepoPathAfterSettingsEdit: () => PROJECT_ROOT,
        });
        const svc = new StartupService(ports);
        const result = await svc.ensureRepoRootWithRecovery();
        assert.ok(result.length > 0, 'should return path resolved after settings edit');
    });
});

// ---------------------------------------------------------------------------
// startServerWithBusyUi
// ---------------------------------------------------------------------------

describe('StartupService.startServerWithBusyUi', () => {
    it('calls serverStart inside withProgressNotification then setReady', async () => {
        const events: string[] = [];
        const ports = makePorts({
            withProgressNotification: async (_title, _msg, task) => {
                events.push('progress:start');
                await task();
                events.push('progress:end');
            },
        });
        const svc = new StartupService(ports);

        await svc.startServerWithBusyUi(
            '/some/root',
            async () => { events.push('server:start'); },
            async () => { events.push('sync:repoPath'); },
            (msg) => { events.push(`setAnalyzing:${msg}`); },
            () => { events.push('setReady'); },
        );

        assert.deepEqual(events, [
            'setAnalyzing:Starting server...',
            'progress:start',
            'server:start',
            'progress:end',
            'sync:repoPath',
            'setReady',
        ]);
    });

    it('continues (setReady is still called) even when syncRepoPath rejects', async () => {
        const events: string[] = [];
        const ports = makePorts({
            withProgressNotification: async (_t, _m, task) => { await task(); },
        });
        const svc = new StartupService(ports);

        await svc.startServerWithBusyUi(
            '/root',
            async () => {},
            async () => { throw new Error('sync failed'); },
            () => {},
            () => { events.push('setReady'); },
        );

        assert.deepEqual(events, ['setReady']);
    });
});

// ---------------------------------------------------------------------------
// revealLitCriticActivityContainerIfProjectDetected
// ---------------------------------------------------------------------------

describe('StartupService.revealLitCriticActivityContainerIfProjectDetected', () => {
    it('executes activity-view command when CANON.md is present', async () => {
        let executedCmd = '';
        const projectDir = '/my/novel';
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: projectDir } }],
            pathExists: (p) => p === path.join(projectDir, 'CANON.md'),
            executeCommand: async (cmd) => { executedCmd = cmd; },
        });
        const svc = new StartupService(ports);
        await svc.revealLitCriticActivityContainerIfProjectDetected();
        assert.equal(executedCmd, 'workbench.view.extension.lit-critic');
    });

    it('does not execute command when CANON.md is absent', async () => {
        let executedCmd = '';
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: '/no/project' } }],
            pathExists: () => false,
            executeCommand: async (cmd) => { executedCmd = cmd; },
        });
        const svc = new StartupService(ports);
        await svc.revealLitCriticActivityContainerIfProjectDetected();
        assert.equal(executedCmd, '');
    });

    it('does not throw when executeCommand rejects', async () => {
        const projectDir = '/my/novel';
        const ports = makePorts({
            getWorkspaceFolders: () => [{ uri: { fsPath: projectDir } }],
            pathExists: (p) => p === path.join(projectDir, 'CANON.md'),
            executeCommand: async () => { throw new Error('no view'); },
        });
        const svc = new StartupService(ports);
        // Should resolve without throwing
        await assert.doesNotReject(() =>
            svc.revealLitCriticActivityContainerIfProjectDetected()
        );
    });
});
