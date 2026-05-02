/**
 * Diagnostics Provider — maps findings to VS Code diagnostics (squiggly underlines).
 *
 * Severity mapping:
 *   critical → DiagnosticSeverity.Error     (red squiggle)
 *   major    → DiagnosticSeverity.Warning   (yellow squiggle)
 *   minor    → DiagnosticSeverity.Information (blue squiggle)
 *
 * Line numbers: findings use 1-based line_start/line_end; VS Code uses 0-based.
 */

import * as vscode from 'vscode';
import { AnalysisSnapshot, Finding, SessionInfo } from './types';

const SEVERITY_MAP: Record<string, vscode.DiagnosticSeverity> = {
    'critical': vscode.DiagnosticSeverity.Error,
    'major': vscode.DiagnosticSeverity.Warning,
    'minor': vscode.DiagnosticSeverity.Information,
};

export class DiagnosticsProvider implements vscode.Disposable {
    private collection: vscode.DiagnosticCollection;
    private _scenePath: string | null = null;
    private _scenePaths: string[] = [];

    /** The primary scene file path currently being reviewed (read-only). */
    get scenePath(): string | null {
        return this._scenePath;
    }

    /** All scene file paths in the current multi-scene session. */
    get scenePaths(): string[] {
        return this._scenePaths;
    }

    constructor() {
        this.collection = vscode.languages.createDiagnosticCollection('litCritic');
    }

    /**
     * Set the scene file(s) being reviewed.
     * For multi-scene sessions, pass all scene paths so diagnostics can be
     * distributed across the correct URIs.
     */
    setScenePath(scenePath: string, scenePaths?: string[]): void {
        this._scenePath = scenePath;
        this._scenePaths = scenePaths && scenePaths.length > 0 ? scenePaths : [scenePath];
    }

    /**
     * Update diagnostics from an analysis snapshot (new model).
     * Displays active findings; suppresses silenced and resolved findings.
     */
    updateFromSnapshot(snapshot: AnalysisSnapshot): void {
        if (snapshot.scene_paths.length > 0) {
            this._scenePath = snapshot.scene_paths[0];
            this._scenePaths = snapshot.scene_paths;
        }
        this.updateFromFindings(snapshot.findings);
    }

    /**
     * Refresh diagnostics from session info (legacy — for backward compat with old sessions).
     */
    updateFromSession(session: SessionInfo): void {
        if (!this.scenePath || !session.findings_status) {
            return;
        }
        // Prefer updateFromFindings() with full data; this is a legacy convenience stub.
        this.collection.clear();
    }

    /**
     * Update diagnostics from a full list of findings.
     * Groups findings by their scene_path and sets diagnostics per URI.
     * Active findings are shown; silenced and resolved findings are suppressed.
     * Call this after analysis completes or after any finding status change.
     */
    updateFromFindings(findings: Finding[]): void {
        if (!this.scenePath) {
            return;
        }

        // Group findings by scene_path (multi-scene support)
        const grouped = new Map<string, vscode.Diagnostic[]>();

        for (const finding of findings) {
            // Suppress silenced, resolved, and legacy-resolved findings
            if (finding.status === 'silenced' || finding.status === 'resolved' ||
                finding.status === 'accepted' || finding.status === 'rejected' ||
                finding.status === 'withdrawn') {
                continue;
            }

            const targetPath = finding.scene_path || this.scenePath;
            if (!grouped.has(targetPath)) {
                grouped.set(targetPath, []);
            }
            grouped.get(targetPath)!.push(this.findingToDiagnostic(finding));
        }

        // Clear previous diagnostics for all known scene paths
        this.collection.clear();

        // Set diagnostics per URI
        for (const [filePath, diagnostics] of grouped) {
            const uri = vscode.Uri.file(filePath);
            this.collection.set(uri, diagnostics);
        }
    }

    /**
     * Update a single finding's diagnostic (e.g., after a silence action changes its status).
     */
    updateSingleFinding(finding: Finding): void {
        if (!this.scenePath) {
            return;
        }

        const targetPath = finding.scene_path || this.scenePath;
        const uri = vscode.Uri.file(targetPath);
        const existing = this.collection.get(uri) || [];
        const updated: vscode.Diagnostic[] = [];

        // Replace or remove the diagnostic for this finding
        for (const diag of existing) {
            if (diag.code === finding.number) {
                // Remove if silenced, resolved, or legacy-resolved
                if (finding.status === 'silenced' || finding.status === 'resolved' ||
                    finding.status === 'accepted' || finding.status === 'rejected' ||
                    finding.status === 'withdrawn') {
                    continue;
                }
                // Replace with updated diagnostic
                updated.push(this.findingToDiagnostic(finding));
            } else {
                updated.push(diag);
            }
        }

        this.collection.set(uri, updated);
    }

    /**
     * Remove the diagnostic for a specific finding (when accepted/rejected/withdrawn).
     * Searches all tracked scene URIs for the finding.
     */
    removeFinding(findingNumber: number, findingScenePath?: string | null): void {
        if (!this.scenePath) {
            return;
        }

        // If we know which file the finding belongs to, target that URI directly
        if (findingScenePath) {
            const uri = vscode.Uri.file(findingScenePath);
            const existing = this.collection.get(uri) || [];
            const filtered = [...existing].filter(d => d.code !== findingNumber);
            this.collection.set(uri, filtered);
            return;
        }

        // Otherwise search all scene paths
        for (const scenePath of this._scenePaths) {
            const uri = vscode.Uri.file(scenePath);
            const existing = this.collection.get(uri) || [];
            const filtered = [...existing].filter(d => d.code !== findingNumber);
            if (filtered.length !== existing.length) {
                this.collection.set(uri, filtered);
                break;
            }
        }
    }

    /**
     * Clear all diagnostics.
     */
    clear(): void {
        this.collection.clear();
        this._scenePath = null;
        this._scenePaths = [];
    }

    dispose(): void {
        this.collection.dispose();
    }

    // ------------------------------------------------------------------
    // Private helpers
    // ------------------------------------------------------------------

    private findingOriginLabel(finding: Finding): string {
        const origin = ((finding as Finding & { origin?: string }).origin || 'llm').toLowerCase();
        if (origin === 'deterministic') {
            return 'Deterministic';
        }
        if (origin === 'llm') {
            return 'LLM';
        }
        return origin.charAt(0).toUpperCase() + origin.slice(1);
    }

    private findingToDiagnostic(finding: Finding): vscode.Diagnostic {
        const range = this.findingToRange(finding);
        const severity = SEVERITY_MAP[finding.severity] ?? vscode.DiagnosticSeverity.Warning;
        const originLabel = this.findingOriginLabel(finding);

        const baseMessage = finding.evidence || `Finding #${finding.number} (${finding.lens})`;
        const message = `[Origin: ${originLabel}] ${baseMessage}`;
        const diagnostic = new vscode.Diagnostic(range, message, severity);
        diagnostic.source = `lit-critic (${finding.lens})`;
        diagnostic.code = finding.number;

        // Add impact and options as related information
        if (finding.impact) {
            diagnostic.message += `\n\nImpact: ${finding.impact}`;
        }
        if (finding.options && finding.options.length > 0) {
            diagnostic.message += `\n\nSuggestions:\n${finding.options.map((o, i) => `  ${i + 1}. ${o}`).join('\n')}`;
        }
        if (finding.stale) {
            diagnostic.message += '\n\n⚠️ This finding may be stale (scene was edited in this region).';
            diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
        }

        return diagnostic;
    }

    private findingToRange(finding: Finding): vscode.Range {
        if (finding.line_start !== null && finding.line_start !== undefined) {
            const startLine = Math.max(0, finding.line_start - 1); // 1-based → 0-based
            const endLine = finding.line_end !== null && finding.line_end !== undefined
                ? Math.max(0, finding.line_end - 1)
                : startLine;

            // Full line range (column 0 to end of line)
            return new vscode.Range(
                new vscode.Position(startLine, 0),
                new vscode.Position(endLine, Number.MAX_SAFE_INTEGER)
            );
        }

        // No line numbers — place at top of file
        return new vscode.Range(
            new vscode.Position(0, 0),
            new vscode.Position(0, 0)
        );
    }
}
