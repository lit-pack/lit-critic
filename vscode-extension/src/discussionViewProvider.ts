/**
 * DiscussionViewProvider — WebviewViewProvider for the Discussion sidebar panel.
 *
 * Lives in the Secondary Side Bar under the `lit-critic-review` view container.
 * Displays a read-only view of the currently selected finding.
 */

import * as vscode from 'vscode';
import { Finding } from './types';
import { getDiscussionPanelHtml } from './ui/discussionPanelView';

interface PendingShowState {
    finding: Finding;
    current: number;
    total: number;
    readOnlyNotice?: string;
}

export class DiscussionViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
    private _view: vscode.WebviewView | undefined;
    private _pendingShow: PendingShowState | undefined;

    resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ): void {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: false,
        };

        webviewView.webview.html = this.getIdleHtml();

        webviewView.onDidDispose(() => {
            this._view = undefined;
        });

        // Apply any state that arrived before the view was resolved
        if (this._pendingShow) {
            const p = this._pendingShow;
            this._pendingShow = undefined;
            this.show(p.finding, p.current, p.total, p.readOnlyNotice);
        }
    }

    /**
     * Show or update the discussion view with a finding.
     */
    show(
        finding: Finding,
        current: number,
        total: number,
        readOnlyNotice?: string,
    ): void {
        if (!this._view) {
            // View not yet resolved — queue and open the sidebar container
            this._pendingShow = { finding, current, total, readOnlyNotice };
            void vscode.commands.executeCommand('litCritic.discussionView.focus');
            return;
        }

        this._view.webview.html = getDiscussionPanelHtml(
            finding,
            current,
            total,
            readOnlyNotice,
        );

        if (!this._view.visible) {
            this._view.show(true);
        }
    }

    /**
     * Reset the view to the idle/empty state.
     * VS Code owns the view lifecycle; we cannot dispose it.
     */
    close(): void {
        this._pendingShow = undefined;
        if (this._view) {
            this._view.webview.html = this.getIdleHtml();
        }
    }

    dispose(): void {
        // Nothing to clean up — no streams or timers.
    }

    private getIdleHtml(): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-editor-foreground);
    background: var(--vscode-editor-background);
    padding: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    margin: 0;
    box-sizing: border-box;
}
.idle-message {
    text-align: center;
    opacity: 0.6;
    font-style: italic;
}
</style>
</head>
<body>
<div class="idle-message">Select a finding to view its details here.</div>
</body>
</html>`;
    }
}
