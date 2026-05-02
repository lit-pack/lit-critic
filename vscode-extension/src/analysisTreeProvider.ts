/**
 * Analysis Tree Provider — sidebar view showing current findings by scene.
 *
 * Tree structure (flat):
 *   chapter-01.md   5 findings
 *   chapter-02.md   2 findings
 *
 * SceneFileItem shows filename and total finding count.
 * Clicking a SceneFileItem fires `litCritic.showSceneFindings` to populate
 * the Findings tree with all findings for that scene.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { Finding } from './types';

const TREE_COUNT_URI_SCHEME = 'lit-critic-count';

const SEVERITY_COLORS: Record<string, string> = {
    critical: 'charts.red',
    major: 'charts.yellow',
    minor: 'charts.blue',
};

function getNormalizedSeverity(severity?: string): string {
    return (severity || '').toLowerCase();
}

function getNormalizedStatus(status?: string): string {
    return (status || 'active').toLowerCase();
}

function isActiveStatus(status?: string): boolean {
    const normalized = getNormalizedStatus(status);
    return normalized === 'active' || normalized === 'pending' ||
        normalized === 'escalated' || normalized === 'discussed' || normalized === 'revised';
}

function getMaxActiveSeverity(findings: Finding[]): string {
    const active = findings.filter((f) => isActiveStatus(f.status));
    if (active.some((f) => getNormalizedSeverity(f.severity) === 'critical')) {
        return 'critical';
    }
    if (active.some((f) => getNormalizedSeverity(f.severity) === 'major')) {
        return 'major';
    }
    return 'minor';
}

type AnalysisTreeElement = SceneFileItem | EmptyStateItem;

export class AnalysisTreeProvider implements vscode.TreeDataProvider<AnalysisTreeElement> {
    private _onDidChangeTreeData = new vscode.EventEmitter<AnalysisTreeElement | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private findingsByScene: Map<string, Finding[]> = new Map();
    private sceneItems: SceneFileItem[] = [];
    private cacheDirty = true;

    constructor() {}

    /**
     * Set or replace findings for a single scene.
     */
    setFindings(scenePath: string, findings: Finding[]): void {
        if (findings.length === 0) {
            this.findingsByScene.delete(scenePath);
        } else {
            this.findingsByScene.set(scenePath, findings);
        }
        this.cacheDirty = true;
        this._onDidChangeTreeData.fire();
    }

    /**
     * Replace all findings at once (used for bulk hydration on startup).
     */
    setAllFindings(findingsByScene: Map<string, Finding[]>): void {
        this.findingsByScene = new Map(findingsByScene);
        this.cacheDirty = true;
        this._onDidChangeTreeData.fire();
    }

    /**
     * Clear all findings from the tree.
     */
    clear(): void {
        this.findingsByScene.clear();
        this.cacheDirty = true;
        this._onDidChangeTreeData.fire();
    }

    /**
     * Get findings for a specific scene (used by command handlers to filter for Findings tree).
     */
    getFindingsForScene(scenePath: string): Finding[] {
        return this.findingsByScene.get(scenePath) ?? [];
    }

    getTreeItem(element: AnalysisTreeElement): vscode.TreeItem {
        return element;
    }

    getChildren(element?: AnalysisTreeElement): AnalysisTreeElement[] {
        this.ensureCache();

        if (!element) {
            if (this.sceneItems.length === 0) {
                return [new EmptyStateItem('No analysis results')];
            }
            return this.sceneItems;
        }

        return [];
    }

    private ensureCache(): void {
        if (!this.cacheDirty) {
            return;
        }
        this.rebuildCache();
    }

    private rebuildCache(): void {
        const sceneItems: SceneFileItem[] = [];

        const sortedScenes = Array.from(this.findingsByScene.keys()).sort((a, b) =>
            path.basename(a).localeCompare(path.basename(b)),
        );

        for (const scenePath of sortedScenes) {
            const findings = this.findingsByScene.get(scenePath)!;
            if (findings.length === 0) {
                continue;
            }

            const totalCount = findings.length;
            const maxSeverity = getMaxActiveSeverity(findings);
            sceneItems.push(new SceneFileItem(scenePath, totalCount, maxSeverity));
        }

        this.sceneItems = sceneItems;
        this.cacheDirty = false;
    }
}

/**
 * Tree item representing a scene file (leaf node).
 * Clicking fires `litCritic.showSceneFindings` to populate the Findings tree
 * with all findings for this scene.
 */
class SceneFileItem extends vscode.TreeItem {
    readonly scenePath: string;

    constructor(scenePath: string, totalCount: number, maxSeverity: string) {
        const fileName = path.basename(scenePath);
        super(fileName, vscode.TreeItemCollapsibleState.None);
        this.scenePath = scenePath;
        this.contextValue = 'analysisScene';
        this.iconPath = new vscode.ThemeIcon('file-submodule');
        this.id = `analysis-scene:${scenePath}`;

        this.description = `${totalCount} finding${totalCount === 1 ? '' : 's'}`;
        this.tooltip = `${fileName} — ${totalCount} finding${totalCount === 1 ? '' : 's'}`;

        const severityColor = SEVERITY_COLORS[getNormalizedSeverity(maxSeverity)] || 'charts.blue';
        this.resourceUri = vscode.Uri.parse(
            `${TREE_COUNT_URI_SCHEME}://analysis-scene/${encodeURIComponent(fileName)}?count=${totalCount}&severity=${encodeURIComponent(severityColor)}`,
        );

        this.command = {
            command: 'litCritic.showSceneFindings',
            title: 'Show all findings for this scene',
            arguments: [{ scenePath }],
        };
    }
}

class EmptyStateItem extends vscode.TreeItem {
    constructor(label: string) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'empty';
        this.iconPath = new vscode.ThemeIcon('info');
    }
}
