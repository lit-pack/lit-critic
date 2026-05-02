/**
 * Status Bar — single consolidated lit-critic status bar item.
 *
 * States (one item, priority 100):
 *
 *   Idle / ready        — $(book) lit-critic
 *                          Normal background; tooltip shows cumulative budget if any.
 *
 *   Loop active (LLM)   — $(sync~spin) lit-critic: Extracting…
 *                          warningBackground — theme-enabled highlight while busy.
 *
 *   Analyzing (session) — $(sync~spin) lit-critic: Analyzing…
 *                          warningBackground.
 *
 *   Session progress    — $(book) 3/12 findings
 *                          Normal background.
 *
 *   Session complete    — $(book) Review complete
 *                          Normal background.
 *
 *   Server error        — $(error) lit-critic
 *                          errorBackground.
 */

import * as vscode from 'vscode';

type PrimaryState =
    | { kind: 'ready' }
    | { kind: 'analyzing'; message: string }
    | { kind: 'progress'; current: number; total: number }
    | { kind: 'complete' }
    | { kind: 'error'; message: string };

export class StatusBar implements vscode.Disposable {
    private readonly item: vscode.StatusBarItem;

    /** Last set primary state (used to restore after loop goes idle). */
    private _primaryState: PrimaryState = { kind: 'ready' };

    constructor() {
        this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this._render();
        this.item.show();
    }

    // -------------------------------------------------------------------------
    // Primary item: main analysis state
    // -------------------------------------------------------------------------

    /** No active session. */
    setReady(): void {
        this._primaryState = { kind: 'ready' };
        this._render();
    }

    /** Analysis is running. */
    setAnalyzing(message?: string): void {
        this._primaryState = { kind: 'analyzing', message: message || 'Analyzing...' };
        this._render();
    }

    /** Active session — show progress. */
    setProgress(current: number, total: number): void {
        this._primaryState = { kind: 'progress', current, total };
        this._render();
    }

    /** All findings processed. */
    setComplete(): void {
        this._primaryState = { kind: 'complete' };
        this._render();
    }

    /** Server error or not running. */
    setError(message: string): void {
        this._primaryState = { kind: 'error', message };
        this._render();
    }

    // -------------------------------------------------------------------------
    // Internal rendering
    // -------------------------------------------------------------------------

    private _render(): void {
        // Restore primary state.
        switch (this._primaryState.kind) {
            case 'ready': {
                this.item.text = '$(book) lit-critic';
                this.item.tooltip = 'lit-critic ready';
                this.item.backgroundColor = undefined;
                this.item.command = undefined;
                break;
            }
            case 'analyzing': {
                const msg = this._primaryState.message;
                this.item.text = `$(sync~spin) lit-critic: ${msg}`;
                this.item.tooltip = `${msg} · lit-critic is busy — please wait.`;
                this.item.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
                this.item.command = undefined;
                break;
            }
            case 'progress': {
                const { current, total } = this._primaryState;
                this.item.text = `$(book) ${current}/${total} findings`;
                this.item.tooltip = `lit-critic: ${current} of ${total} findings reviewed`;
                this.item.backgroundColor = undefined;
                this.item.command = undefined;
                break;
            }
            case 'complete': {
                this.item.text = '$(book) Review complete';
                this.item.tooltip = 'All findings have been reviewed';
                this.item.backgroundColor = undefined;
                this.item.command = undefined;
                break;
            }
            case 'error': {
                this.item.text = '$(error) lit-critic';
                this.item.tooltip = this._primaryState.message;
                this.item.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
                this.item.command = undefined;
                break;
            }
        }
    }

    dispose(): void {
        this.item.dispose();
    }
}
