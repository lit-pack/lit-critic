/**
 * ExplainCodeActionProvider — registers "Explain (Quick)" and "Explain (Deep)"
 * code actions on lit-critic diagnostic squiggles.
 *
 * When the cursor is on a finding diagnostic, these actions appear in the
 * lightbulb menu (Ctrl+.) so the author can request an explanation with one click.
 *
 * "Explain (Quick)" is the preferred/default action (cheap, fast model).
 * "Explain (Deep)" uses the frontier model for nuanced literary judgment.
 */

import * as vscode from 'vscode';

/** Source prefix set by DiagnosticsProvider for all lit-critic diagnostics. */
const LIT_CRITIC_SOURCE_PREFIX = 'lit-critic';

export class ExplainCodeActionProvider implements vscode.CodeActionProvider {
    static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

    provideCodeActions(
        _document: vscode.TextDocument,
        _range: vscode.Range | vscode.Selection,
        context: vscode.CodeActionContext,
    ): vscode.CodeAction[] | undefined {
        // Only act on lit-critic diagnostics
        const litDiags = context.diagnostics.filter(
            (d) => typeof d.source === 'string' && d.source.startsWith(LIT_CRITIC_SOURCE_PREFIX),
        );

        if (litDiags.length === 0) {
            return undefined;
        }

        const actions: vscode.CodeAction[] = [];

        for (const diag of litDiags) {
            const findingNumber = typeof diag.code === 'number' ? diag.code : undefined;
            if (findingNumber === undefined) {
                continue;
            }

            // "Explain (Quick)" — default one-click action, cheap fast model
            const quickAction = new vscode.CodeAction(
                `💡 Explain this finding (Quick) — #${findingNumber}`,
                vscode.CodeActionKind.QuickFix,
            );
            quickAction.command = {
                command: 'litCritic.explainFindingQuick',
                title: 'Explain finding (Quick)',
                arguments: [findingNumber],
            };
            quickAction.isPreferred = true;
            actions.push(quickAction);

            // "Explain (Deep)" — secondary action, frontier model for complex literary judgments
            const deepAction = new vscode.CodeAction(
                `🔍 Explain this finding (Deep) — #${findingNumber}`,
                vscode.CodeActionKind.QuickFix,
            );
            deepAction.command = {
                command: 'litCritic.explainFindingDeep',
                title: 'Explain finding (Deep)',
                arguments: [findingNumber],
            };
            actions.push(deepAction);
        }

        return actions.length > 0 ? actions : undefined;
    }
}
