/**
 * registerCommands — centralises all command-to-handler mappings.
 *
 * Keeping command IDs and their handlers in one place makes it easy to:
 *   - enumerate expected command IDs in tests,
 *   - add new commands without touching the activation entry point,
 *   - avoid business logic in the registration site.
 */

import * as vscode from 'vscode';

// ---------------------------------------------------------------------------
// Type for the handler map passed in by the caller
// ---------------------------------------------------------------------------

export interface CommandHandlers {
    cmdAnalyze: () => Promise<void>;
    cmdSelectModel: () => Promise<void>;
    cmdStopServer: () => void;
    cmdShowLensFindings: (args: { scenePath: string; lens: string }) => void;
    cmdShowSceneFindings: (args: { scenePath: string }) => void;
    cmdRefreshLearning: () => Promise<void>;
    cmdExportLearning: () => Promise<void>;
    cmdResetLearning: () => Promise<void>;
    cmdDeleteLearningEntry: (item: any) => Promise<void>;
    cmdRefreshKnowledge: () => Promise<void>;
    cmdEditKnowledgeEntry?: (item: any) => Promise<void>;
    cmdResetKnowledgeOverride?: (item?: any) => Promise<void>;
    cmdOpenKnowledgeReviewPanel?: (item?: any) => Promise<void>;
    cmdDeleteKnowledgeEntity?: (item: any) => Promise<void>;
    cmdNextKnowledgeEntity?: () => Promise<void>;
    cmdPreviousKnowledgeEntity?: () => Promise<void>;
    cmdToggleEntityLock?: (item?: any) => Promise<void>;
    cmdKeepFlaggedEntity?: (item?: any) => Promise<void>;
    cmdDeleteFlaggedEntity?: (item?: any) => Promise<void>;
    cmdResetAllKnowledge?: () => Promise<void>;
    cmdResetAllAnalysis?: () => Promise<void>;
    cmdDeleteSceneAnalysis?: (item: any) => Promise<void>;
    cmdExplainFindingQuick?: (findingNumber: number) => Promise<void>;
    cmdExplainFindingDeep?: (findingNumber: number) => Promise<void>;
    cmdPauseLoop?: () => Promise<void>;
    cmdResumeLoop?: () => Promise<void>;
    [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// All command IDs registered by the extension
// ---------------------------------------------------------------------------

export const COMMAND_IDS = [
    'litCritic.analyze',
    'litCritic.selectModel',
    'litCritic.stopServer',
    'litCritic.showLensFindings',
    'litCritic.showSceneFindings',
    'litCritic.refreshLearning',
    'litCritic.exportLearning',
    'litCritic.resetLearning',
    'litCritic.deleteLearningEntry',
    'litCritic.refreshKnowledge',
    'litCritic.editKnowledgeEntry',
    'litCritic.resetKnowledgeOverride',
    'litCritic.deleteKnowledgeEntity',
    'litCritic.openKnowledgeReviewPanel',
    'litCritic.nextKnowledgeEntity',
    'litCritic.previousKnowledgeEntity',
    'litCritic.toggleEntityLock',
    'litCritic.keepFlaggedEntity',
    'litCritic.deleteFlaggedEntity',
    'litCritic.resetAllKnowledge',
    'litCritic.resetAllAnalysis',
    'litCritic.deleteSceneAnalysis',
    'litCritic.explainFindingQuick',
    'litCritic.explainFindingDeep',
    'litCritic.pauseLoop',
    'litCritic.resumeLoop',
] as const;

export type CommandId = typeof COMMAND_IDS[number];

// ---------------------------------------------------------------------------
// Registration function
// ---------------------------------------------------------------------------

/**
 * Register all extension commands and push their disposables to `subscriptions`.
 *
 * Returns the array of disposables so callers can also push them to
 * `context.subscriptions` directly (the function pushes them too for
 * convenience).
 */
export function registerCommands(
    subscriptions: vscode.Disposable[],
    handlers: CommandHandlers,
): vscode.Disposable[] {
    const disposables: vscode.Disposable[] = [
        vscode.commands.registerCommand('litCritic.analyze', handlers.cmdAnalyze),
        vscode.commands.registerCommand('litCritic.selectModel', handlers.cmdSelectModel),
        vscode.commands.registerCommand('litCritic.stopServer', handlers.cmdStopServer),
        // Management commands
        vscode.commands.registerCommand('litCritic.showLensFindings', handlers.cmdShowLensFindings),
        vscode.commands.registerCommand('litCritic.showSceneFindings', handlers.cmdShowSceneFindings),
        vscode.commands.registerCommand('litCritic.refreshLearning', handlers.cmdRefreshLearning),
        vscode.commands.registerCommand('litCritic.exportLearning', handlers.cmdExportLearning),
        vscode.commands.registerCommand('litCritic.resetLearning', handlers.cmdResetLearning),
        vscode.commands.registerCommand('litCritic.deleteLearningEntry', handlers.cmdDeleteLearningEntry),
        vscode.commands.registerCommand('litCritic.refreshKnowledge', handlers.cmdRefreshKnowledge),
        vscode.commands.registerCommand('litCritic.editKnowledgeEntry', handlers.cmdEditKnowledgeEntry ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.resetKnowledgeOverride', handlers.cmdResetKnowledgeOverride ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.deleteKnowledgeEntity', handlers.cmdDeleteKnowledgeEntity ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.openKnowledgeReviewPanel', handlers.cmdOpenKnowledgeReviewPanel ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.nextKnowledgeEntity', handlers.cmdNextKnowledgeEntity ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.previousKnowledgeEntity', handlers.cmdPreviousKnowledgeEntity ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.toggleEntityLock', handlers.cmdToggleEntityLock ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.keepFlaggedEntity', handlers.cmdKeepFlaggedEntity ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.deleteFlaggedEntity', handlers.cmdDeleteFlaggedEntity ?? (async () => {})),
        // Bulk-reset commands
        vscode.commands.registerCommand('litCritic.resetAllKnowledge', handlers.cmdResetAllKnowledge ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.resetAllAnalysis', handlers.cmdResetAllAnalysis ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.deleteSceneAnalysis', handlers.cmdDeleteSceneAnalysis ?? (async () => {})),
        // Explain actions — triggered by ExplainCodeActionProvider or findings tree context menu
        vscode.commands.registerCommand('litCritic.explainFindingQuick', handlers.cmdExplainFindingQuick ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.explainFindingDeep', handlers.cmdExplainFindingDeep ?? (async () => {})),
        // Loop pause/resume
        vscode.commands.registerCommand('litCritic.pauseLoop', handlers.cmdPauseLoop ?? (async () => {})),
        vscode.commands.registerCommand('litCritic.resumeLoop', handlers.cmdResumeLoop ?? (async () => {})),
    ];

    subscriptions.push(...disposables);
    return disposables;
}
