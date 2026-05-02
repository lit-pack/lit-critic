import * as vscode from 'vscode';

import { DiagnosticsProvider } from '../diagnosticsProvider';
import { FindingsTreeProvider } from '../findingsTreeProvider';
import { StatusBar } from '../statusBar';
import { Finding } from '../types';

/**
 * Interface that DiscussionViewProvider implements.
 * Decouples WorkbenchPresenter and WorkflowDeps from the concrete panel implementation.
 */
export interface IDiscussionView {
    show(finding: Finding, current: number, total: number, readOnlyNotice?: string): void;
    close(): void;
    dispose(): void;
}

export interface WorkbenchPresenterDeps {
    statusBar: StatusBar;
    diagnosticsProvider: DiagnosticsProvider;
    findingsTreeProvider: FindingsTreeProvider;
    ensureDiscussionPanel: () => IDiscussionView;
    getDiscussionPanel: () => IDiscussionView | undefined;
}

function _extractCostText(value: unknown): string | undefined {
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : undefined;
    }

    if (value && typeof value === 'object') {
        const rec = value as Record<string, unknown>;
        const candidates = [
            rec.hint,
            rec.text,
            rec.summary,
            rec.label,
            rec.cost_hint,
            rec.costHint,
        ];
        for (const candidate of candidates) {
            if (typeof candidate === 'string' && candidate.trim().length > 0) {
                return candidate.trim();
            }
        }
    }

    return undefined;
}

export function formatModeCostHint(mode: string, hintValue: unknown): string | undefined {
    const hintText = _extractCostText(hintValue);
    if (!hintText) {
        return undefined;
    }
    return `Cost hint (${mode}): ${hintText}`;
}

export function formatTierCostSummary(summaryValue: unknown): string | undefined {
    const summaryText = _extractCostText(summaryValue);
    if (!summaryText) {
        return undefined;
    }
    return `Tier cost summary: ${summaryText}`;
}

export class WorkbenchPresenter {
    private findingsTreeView: vscode.TreeView<any> | undefined;

    constructor(private readonly deps: WorkbenchPresenterDeps) {}

    bindTreeViews(findingsTreeView: vscode.TreeView<any>, _sessionsTreeView?: vscode.TreeView<any>): void {
        this.findingsTreeView = findingsTreeView;
    }

    setReady(): void {
        this.deps.statusBar.setReady();
    }

    setAnalyzing(message?: string): void {
        this.deps.statusBar.setAnalyzing(message);
    }

    setProgress(current: number, total: number): void {
        this.deps.statusBar.setProgress(current, total);
    }

    setComplete(): void {
        this.deps.statusBar.setComplete();
    }

    setError(message: string): void {
        this.deps.statusBar.setError(message);
    }

    closeDiscussion(): void {
        this.deps.getDiscussionPanel()?.close();
    }

    setFindingsPresentation(findings: Finding[], scenePath: string, currentIndex: number, scenePaths?: string[]): void {
        this.deps.findingsTreeProvider.setFindings(findings, scenePath, currentIndex);
        this.revealCurrentFindingSelection();
        this.deps.diagnosticsProvider.setScenePath(scenePath, scenePaths);
    }

    setCurrentFindingIndex(index: number): void {
        this.deps.findingsTreeProvider.setCurrentIndex(index);
        this.revealCurrentFindingSelection();
    }

    updateFindingPresentation(finding: Finding, allFindings: Finding[]): void {
        this.deps.findingsTreeProvider.updateFinding(finding);
        this.deps.diagnosticsProvider.updateFromFindings(allFindings);
    }

    removeFindingDiagnostic(findingNumber: number): void {
        this.deps.diagnosticsProvider.removeFinding(findingNumber);
    }

    updateSingleFindingDiagnostic(finding: Finding): void {
        this.deps.diagnosticsProvider.updateSingleFinding(finding);
    }

    updateDiagnosticsFromFindings(allFindings: Finding[]): void {
        this.deps.diagnosticsProvider.updateFromFindings(allFindings);
    }

    clearSessionPresentation(): void {
        this.deps.diagnosticsProvider.clear();
        this.deps.findingsTreeProvider.clear();
        this.deps.statusBar.setReady();
    }

    revealCurrentFindingSelection(): void {
        const item = this.deps.findingsTreeProvider.getCurrentFindingItem?.();
        if (!this.findingsTreeView || typeof this.findingsTreeView.reveal !== 'function' || !item) {
            return;
        }

        const revealResult = this.findingsTreeView.reveal(item, {
            select: true,
            focus: false,
            expand: true,
        });
        void Promise.resolve(revealResult).catch(() => {
            // Non-fatal: tree may not be visible/materialized yet.
        });
    }

}
