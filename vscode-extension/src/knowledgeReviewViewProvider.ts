/**
 * KnowledgeReviewViewProvider — WebviewViewProvider for the Knowledge Review sidebar panel.
 *
 * Replaces KnowledgeReviewPanel (WebviewPanel) with a WebviewView that lives in the
 * Secondary Side Bar under the `lit-critic-review` view container.
 *
 * Public surface is identical to KnowledgeReviewPanel so callers need no changes:
 *   show(state), updateState(state), getState(), close(), onAction
 *
 * Note: retainContextWhenHidden is set at registration time via
 *   vscode.window.registerWebviewViewProvider(..., { webviewOptions: { retainContextWhenHidden: true } })
 */

import * as vscode from 'vscode';
import {
    KnowledgeReviewPanelAction,
    KnowledgeReviewPanelFieldState,
    KnowledgeReviewPanelState,
} from './types';
import { getKnowledgeReviewPanelHtml } from './ui/knowledgeReviewPanelView';

type IncomingMessage = KnowledgeReviewPanelAction;

function cloneState(state: KnowledgeReviewPanelState): KnowledgeReviewPanelState {
    return {
        ...state,
        fields: state.fields.map((field: KnowledgeReviewPanelFieldState) => ({ ...field })),
    };
}

function applyFieldDraft(
    state: KnowledgeReviewPanelState,
    fieldName: string,
    value: string,
): KnowledgeReviewPanelState {
    const fields = state.fields.map((field) => {
        if (field.fieldName !== fieldName) {
            return field;
        }
        return {
            ...field,
            draftValue: value,
            isDirty: value !== field.effectiveValue,
        };
    });
    const dirty = fields.some((f) => f.isDirty);
    return { ...state, fields, selectedFieldName: fieldName, dirty, status: dirty ? 'dirty' : 'idle' };
}

export class KnowledgeReviewViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
    private _view: vscode.WebviewView | undefined;
    private _state: KnowledgeReviewPanelState | null = null;
    private _pendingState: KnowledgeReviewPanelState | null = null;

    onAction: ((action: KnowledgeReviewPanelAction) => void | Promise<void>) | null = null;

    resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ): void {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
        };

        webviewView.webview.html = this.getIdleHtml();

        webviewView.onDidDispose(() => {
            this._view = undefined;
        });

        webviewView.webview.onDidReceiveMessage((message: IncomingMessage) => {
            void this.handleMessage(message);
        });

        // Apply any state that arrived before the view was resolved
        if (this._pendingState) {
            const pending = this._pendingState;
            this._pendingState = null;
            this.show(pending);
        }
    }

    show(state: KnowledgeReviewPanelState): void {
        this._state = cloneState(state);

        if (!this._view) {
            // View not yet resolved — queue and open the sidebar container
            this._pendingState = cloneState(state);
            void vscode.commands.executeCommand('litCritic.knowledgeReviewView.focus');
            return;
        }

        this.render();

        if (!this._view.visible) {
            this._view.show(true);
        }
    }

    updateState(state: KnowledgeReviewPanelState): void {
        this._state = cloneState(state);
        if (!this._view) {
            this._pendingState = cloneState(state);
            void vscode.commands.executeCommand('litCritic.knowledgeReviewView.focus');
            return;
        }
        this.render();
    }

    getState(): KnowledgeReviewPanelState | null {
        return this._state ? cloneState(this._state) : null;
    }

    /**
     * Reset the view to idle/empty state.
     * VS Code owns the view lifecycle; we cannot dispose it.
     */
    close(): void {
        this._state = null;
        this._pendingState = null;
        if (this._view) {
            this._view.webview.html = this.getIdleHtml();
        }
    }

    dispose(): void {
        this._state = null;
        this._pendingState = null;
    }

    private async handleMessage(message: IncomingMessage): Promise<void> {
        if (!this._state) {
            return;
        }

        if (message.type === 'change-field') {
            this._state = applyFieldDraft(this._state, message.fieldName, message.value);
            // No render() — draft changes are managed client-side to preserve textarea focus.
        }

        if (message.type === 'select-field') {
            this._state = { ...this._state, selectedFieldName: message.fieldName };
            this.render();
        }

        if (message.type === 'close') {
            this.close();
        }

        await this.onAction?.(message);
    }

    private render(): void {
        if (!this._view || !this._state) {
            return;
        }

        if (this._view.webview.html) {
            void this._view.webview.postMessage({
                type: 'setState',
                state: cloneState(this._state),
            });
        }

        this._view.webview.html = getKnowledgeReviewPanelHtml(this._state);
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
<div class="idle-message">Select a knowledge entity to review it here.</div>
</body>
</html>`;
    }
}
