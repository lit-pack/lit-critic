/**
 * Findings Tree View — sidebar panel showing all findings in a navigable tree.
 *
 * Tree structure:
 *   ▼ Prose (3 findings)
 *       ⚠️ #1 Major — Rhythm break at L042-L045    [active]
 *       🔇 #3 Minor — Passive voice at L078         [silenced]
 *   ▼ Structure (2 findings)
 *       🔴 #2 Critical — Missing scene goal          [active]
 *
 * Click navigates to the line in the editor.
 * Right-click on active findings shows silence actions (silence this / silence pattern).
 */

import * as vscode from 'vscode';
import { AnalysisSnapshot, Finding } from './types';

const FINDING_URI_SCHEME = 'lit-critic-finding';
const TREE_COUNT_URI_SCHEME = 'lit-critic-count';

const LENS_ICONS: Record<string, string> = {
    prose: 'whole-word',
    structure: 'list-tree',
    logic: 'lightbulb',
    clarity: 'eye',
    continuity: 'git-compare',
    dialogue: 'comment-discussion',
};

const RESOLVED_COLOR_ID = 'gitDecoration.ignoredResourceForeground';

interface StatusVisual {
    priority: number;
}

const STATUS_VISUALS: Record<string, StatusVisual> = {
    // New model states
    'active':    { priority: 0 },
    'silenced':  { priority: 1 },
    'resolved':  { priority: 2 },
    // Legacy interactive states (backward compat with old sessions)
    'pending':   { priority: 0 },
    'escalated': { priority: 1 },
    'discussed': { priority: 2 },
    'revised':   { priority: 2 },
    'accepted':  { priority: 3 },
    'rejected':  { priority: 3 },
    'withdrawn': { priority: 3 },
    'conceded':  { priority: 3 },
};

const DEFAULT_STATUS_VISUAL: StatusVisual = {
    priority: 0,
};

const SEVERITY_COLORS: Record<string, string> = {
    'critical': 'charts.red',
    'major': 'charts.yellow',
    'minor': 'charts.blue',
};

const SEVERITY_PRIORITY: Record<string, number> = {
    'critical': 0,
    'major': 1,
    'minor': 2,
};

function getNormalizedStatus(status?: string): string {
    return (status || 'active').toLowerCase();
}

function getStatusVisual(status?: string): StatusVisual {
    return STATUS_VISUALS[getNormalizedStatus(status)] || DEFAULT_STATUS_VISUAL;
}

function getNormalizedSeverity(severity?: string): string {
    return (severity || '').toLowerCase();
}

function isActiveStatus(status?: string): boolean {
    const normalized = getNormalizedStatus(status);
    // New model: active; legacy compat: pending and in-progress interactive statuses
    return normalized === 'active' || normalized === 'pending' ||
        normalized === 'escalated' || normalized === 'discussed' || normalized === 'revised';
}

function getSeverityColorId(severity?: string): string {
    return SEVERITY_COLORS[getNormalizedSeverity(severity)] || 'charts.blue';
}

function getLabelColorForFinding(status?: string, severity?: string): string | undefined {
    if (!isActiveStatus(status)) {
        return RESOLVED_COLOR_ID;
    }

    const normalizedSeverity = getNormalizedSeverity(severity);
    if (normalizedSeverity === 'critical') {
        return 'charts.red';
    }
    if (normalizedSeverity === 'major') {
        return 'charts.yellow';
    }

    return undefined;
}

function getResolvedIcon(status?: string): vscode.ThemeIcon {
    const dimColor = new vscode.ThemeColor(RESOLVED_COLOR_ID);
    const resolvedStatus = getNormalizedStatus(status);
    const iconByStatus: Record<string, string> = {
        // New model
        silenced: 'mute',
        resolved: 'check',
        // Legacy interactive statuses
        accepted: 'pass',
        rejected: 'close',
        withdrawn: 'dash',
        conceded: 'check',
    };
    const iconId = iconByStatus[resolvedStatus] || 'circle-outline';
    return new vscode.ThemeIcon(iconId, dimColor);
}

function getActiveIcon(severity?: string): vscode.ThemeIcon {
    const normalizedSeverity = getNormalizedSeverity(severity);
    const iconBySeverity: Record<string, string> = {
        critical: 'error',
        major: 'warning',
        minor: 'info',
    };
    const iconId = iconBySeverity[normalizedSeverity] || 'info';
    return new vscode.ThemeIcon(iconId, new vscode.ThemeColor(getSeverityColorId(severity)));
}

function getFindingIcon(finding: Finding): vscode.ThemeIcon {
    if (!isActiveStatus(finding.status)) {
        return getResolvedIcon(finding.status);
    }
    return getActiveIcon(finding.severity);
}

function getFindingOriginValue(finding: Finding): string {
    const origin = (finding as Finding & { origin?: string }).origin;
    return (origin || 'llm').toLowerCase();
}

function getFindingOriginLabel(finding: Finding): string {
    const origin = getFindingOriginValue(finding);
    if (origin === 'deterministic') {
        return 'Deterministic';
    }
    if (origin === 'llm') {
        return 'LLM';
    }
    return origin.charAt(0).toUpperCase() + origin.slice(1);
}

function buildFindingUri(finding: Finding): vscode.Uri {
    const status = encodeURIComponent(getNormalizedStatus(finding.status));
    const severity = encodeURIComponent(getNormalizedSeverity(finding.severity) || 'minor');
    return vscode.Uri.parse(
        `${FINDING_URI_SCHEME}://f/${finding.number}?status=${status}&severity=${severity}`,
    );
}

function getMaxActiveSeverity(findings: Finding[]): string {
    const activeFindings = findings.filter((finding) => isActiveStatus(finding.status));
    if (activeFindings.some((finding) => getNormalizedSeverity(finding.severity) === 'critical')) {
        return 'critical';
    }
    if (activeFindings.some((finding) => getNormalizedSeverity(finding.severity) === 'major')) {
        return 'major';
    }
    return 'minor';
}

function buildLensUri(lens: string, activeCount: number, total: number, maxSeverity: string): vscode.Uri {
    const encodedLens = encodeURIComponent(lens);
    const encodedSeverity = encodeURIComponent(getNormalizedSeverity(maxSeverity) || 'minor');
    return vscode.Uri.parse(
        `${FINDING_URI_SCHEME}://lens/${encodedLens}?active=${activeCount}&total=${total}&maxSeverity=${encodedSeverity}`,
    );
}

function toThemeColor(colorId?: string): vscode.ThemeColor | undefined {
    return colorId ? new vscode.ThemeColor(colorId) : undefined;
}

export class FindingsDecorationProvider implements vscode.FileDecorationProvider {
    private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri | vscode.Uri[] | undefined>();
    readonly onDidChangeFileDecorations = this._onDidChange.event;

    fireChange(): void {
        this._onDidChange.fire(undefined);
    }

    provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
        if (uri.scheme === TREE_COUNT_URI_SCHEME) {
            const params = new URLSearchParams(uri.query);
            return this.decorateCount(params);
        }

        if (uri.scheme !== FINDING_URI_SCHEME) {
            return undefined;
        }

        const params = new URLSearchParams(uri.query);

        if (uri.authority === 'f') {
            return this.decorateFinding(params);
        }

        if (uri.authority === 'lens') {
            return this.decorateLens(params);
        }

        return undefined;
    }

    private decorateFinding(params: URLSearchParams): vscode.FileDecoration | undefined {
        const status = getNormalizedStatus(params.get('status') || 'active');
        const severity = getNormalizedSeverity(params.get('severity') || 'minor');
        const labelColorId = getLabelColorForFinding(status, severity);
        const color = toThemeColor(labelColorId);

        if (status === 'active' || status === 'pending') {
            return {
                color,
                tooltip: 'Active',
            };
        }

        const badges: Record<string, string> = {
            // New model
            silenced: 'S',
            resolved: '✓',
            // Legacy
            escalated: '!!',
            discussed: 'D',
            revised: 'R',
            accepted: '✓',
            rejected: '✗',
            withdrawn: 'W',
            conceded: 'C',
        };

        const tooltips: Record<string, string> = {
            // New model
            silenced: 'Silenced',
            resolved: 'Resolved',
            // Legacy
            escalated: 'Escalated',
            discussed: 'Discussed',
            revised: 'Revised',
            accepted: 'Accepted',
            rejected: 'Rejected',
            withdrawn: 'Withdrawn',
            conceded: 'Conceded',
        };

        return {
            badge: badges[status],
            color,
            tooltip: tooltips[status] || status,
        };
    }

    private decorateLens(params: URLSearchParams): vscode.FileDecoration | undefined {
        const active = Number.parseInt(params.get('active') || '0', 10);
        const total = Number.parseInt(params.get('total') || '0', 10);
        const maxSeverity = getNormalizedSeverity(params.get('maxSeverity') || 'minor');
        const colorId = active > 0 ? getSeverityColorId(maxSeverity) : undefined;

        return {
            badge: String(Math.max(0, total)),
            color: toThemeColor(colorId),
            tooltip: `${Math.max(0, total)} finding${total === 1 ? '' : 's'} (${Math.max(0, active)} active)`,
        };
    }

    private decorateCount(params: URLSearchParams): vscode.FileDecoration | undefined {
        const count = Number.parseInt(params.get('count') || '0', 10);
        return {
            badge: String(Math.max(0, count)),
            tooltip: `${Math.max(0, count)} total`,
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

/**
 * Header item shown at the top of the findings tree when displaying a
 * filtered lens view (scene + lens combination from the Analysis tree).
 */
export class LensFilterContextItem extends vscode.TreeItem {
    constructor(scenePath: string, lens: string) {
        const fileName = scenePath.replace(/\\/g, '/').split('/').pop() || scenePath;
        const lensLabel = lens.charAt(0).toUpperCase() + lens.slice(1);
        super(`${fileName} · ${lensLabel}`, vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'lensFilterContext';
        this.iconPath = new vscode.ThemeIcon(LENS_ICONS[lens.toLowerCase()] || 'symbol-namespace');
        this.tooltip = `Filtered view: ${lens} findings for ${fileName}`;
    }
}

/**
 * Header item displayed at the top of the findings tree showing the source snapshot.
 */
export class SnapshotContextItem extends vscode.TreeItem {
    readonly snapshotId: number;

    constructor(snapshot: AnalysisSnapshot) {
        const depthLabel = snapshot.depth_mode === 'quick' ? 'Quick' : 'Deep';
        const sceneCount = snapshot.scene_paths.length;
        const scenesLabel = sceneCount === 1 ? '1 scene' : `${sceneCount} scenes`;
        const label = `Snapshot #${snapshot.id} · ${depthLabel} · ${scenesLabel}`;
        super(label, vscode.TreeItemCollapsibleState.None);
        this.snapshotId = snapshot.id;
        this.contextValue = 'snapshotContext';
        this.iconPath = new vscode.ThemeIcon('pin');
        this.tooltip = new vscode.MarkdownString(
            `**Analysis Snapshot #${snapshot.id}**\n\n` +
            `Depth: ${depthLabel}  \nScenes: ${scenesLabel}  \n` +
            `Active findings: ${snapshot.active_count}  \nSilenced: ${snapshot.silenced_count}  \n` +
            `Created: ${snapshot.created_at}`,
        );
    }
}

type FindingsTreeNode = FindingTreeItem | LensGroupItem | EmptyStateItem | SnapshotContextItem | LensFilterContextItem;

export class FindingsTreeProvider implements vscode.TreeDataProvider<FindingsTreeNode> {
    private _onDidChangeTreeData = new vscode.EventEmitter<FindingTreeItem | LensGroupItem | undefined | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private findings: Finding[] = [];
    private scenePath: string | null = null;
    private snapshotContext: AnalysisSnapshot | null = null;
    private cacheDirty = true;
    private lensItems: LensGroupItem[] = [];
    private findingItemsByLens: Map<string, FindingTreeItem[]> = new Map();
    private findingItemsByNumber: Map<number, FindingTreeItem> = new Map();

    /** When set, the tree shows only findings for a specific scene+lens (filtered detail view). */
    private lensFilter: { scenePath: string; lens: string } | null = null;

    constructor(private readonly decorationProvider?: FindingsDecorationProvider) {}

    private notifyTreeChanged(): void {
        this.cacheDirty = true;
        this._onDidChangeTreeData.fire();
        this.decorationProvider?.fireChange();
    }

    /**
     * Update the findings list and refresh the tree.
     * scenePath is used as the fallback navigation target when a finding lacks its own scene_path.
     * @param _currentIndex Deprecated — ignored in the new model. Present for backward compat.
     */
    setFindings(findings: Finding[], scenePath?: string, _currentIndex?: number): void {
        this.findings = findings;
        this.scenePath = scenePath ?? null;
        this.notifyTreeChanged();
    }

    /**
     * @deprecated No-op in the new model. Finding navigation is driven by SSE events.
     * Kept for backward compat with the legacy session workflow controller.
     */
    setCurrentIndex(_index: number): void {
        // No-op: the new model does not track a "current finding index"
    }

    /**
     * @deprecated Returns undefined in the new model.
     * Kept for backward compat with the legacy workbench presenter.
     */
    getCurrentFindingItem(): FindingTreeItem | undefined {
        return undefined;
    }

    /**
     * Update the findings from an analysis snapshot (new model primary path).
     * Sets both the snapshot context header and the findings list in one call.
     */
    setFromSnapshot(snapshot: AnalysisSnapshot): void {
        this.snapshotContext = snapshot;
        this.findings = snapshot.findings;
        this.scenePath = snapshot.scene_paths[0] ?? null;
        this.notifyTreeChanged();
    }

    /**
     * Update a single finding in the list (e.g., after a silence action changes its status).
     */
    updateFinding(finding: Finding): void {
        const idx = this.findings.findIndex(f => f.number === finding.number);
        if (idx >= 0) {
            this.findings[idx] = finding;
            this.notifyTreeChanged();
        }
    }

    /**
     * Set the snapshot context header at the top of the findings tree.
     * Pass null to clear it (shows empty state when no findings are loaded).
     */
    setSnapshotContext(snapshot: AnalysisSnapshot | null): void {
        this.snapshotContext = snapshot;
        this.notifyTreeChanged();
    }

    /**
     * Look up a single finding by its number.
     * Returns undefined if the finding is not in the current list.
     */
    getFinding(number: number): Finding | undefined {
        return this.findings.find(f => f.number === number);
    }

    /**
     * Return all currently loaded findings (read-only copy).
     */
    getAllFindings(): Finding[] {
        return [...this.findings];
    }

    /**
     * Display a filtered view: only the given findings for a specific scene+lens.
     * Shows a LensFilterContextItem header followed by flat FindingTreeItem nodes
     * (no lens groups). Clears snapshot/session context headers.
     */
    showLensFindings(findings: Finding[], scenePath: string, lens: string): void {
        this.findings = findings;
        this.scenePath = scenePath;
        this.snapshotContext = null;
        this.lensFilter = { scenePath, lens };
        this.notifyTreeChanged();
    }

    /**
     * Clear all findings and context headers.
     */
    clear(): void {
        this.findings = [];
        this.scenePath = null;
        this.snapshotContext = null;
        this.lensFilter = null;
        this.notifyTreeChanged();
    }

    getTreeItem(element: FindingTreeItem | LensGroupItem): vscode.TreeItem {
        return element;
    }

    getParent(element: FindingsTreeNode): LensGroupItem | undefined {
        if (element instanceof SnapshotContextItem
            || element instanceof EmptyStateItem || element instanceof LensFilterContextItem) {
            return undefined;
        }
        this.ensureCache();
        if (element instanceof LensGroupItem) {
            return undefined;
        }
        // In filtered mode, findings are flat (no parent lens group)
        if (this.lensFilter) {
            return undefined;
        }
        // FindingTreeItem — return its parent LensGroupItem
        const lens = element.finding.lens.toLowerCase();
        return this.lensItems.find((item) => item.lens === lens);
    }

    getChildren(element?: FindingsTreeNode): FindingsTreeNode[] {
        this.ensureCache();

        if (!element) {
            // Filtered lens mode — flat list with context header
            if (this.lensFilter) {
                const header = new LensFilterContextItem(this.lensFilter.scenePath, this.lensFilter.lens);
                const allItems = this.findingItemsByLens.get(this.lensFilter.lens.toLowerCase())
                    || Array.from(this.findingItemsByNumber.values());
                if (allItems.length === 0) {
                    return [header, new EmptyStateItem('No findings for this lens')];
                }
                return [header, ...allItems];
            }

            // Root level — build context header + lens groups
            const header = this.snapshotContext ? new SnapshotContextItem(this.snapshotContext) : null;

            if (this.lensItems.length === 0) {
                if (!header) {
                    return [new EmptyStateItem('No analysis snapshot loaded')];
                }
                return [header, new EmptyStateItem('No findings in this snapshot')];
            }
            return header ? [header, ...this.lensItems] : this.lensItems;
        }

        if (element instanceof LensGroupItem) {
            // Lens group — show findings for that lens
            return this.findingItemsByLens.get(element.lens) || [];
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
        const groups = new Map<string, Finding[]>();

        for (const finding of this.findings) {
            const lens = finding.lens.toLowerCase();
            if (!groups.has(lens)) {
                groups.set(lens, []);
            }
            groups.get(lens)!.push(finding);
        }

        // Order: prose, structure, logic, clarity, continuity, dialogue
        const order = ['prose', 'structure', 'logic', 'clarity', 'continuity', 'dialogue'];
        const lensItems: LensGroupItem[] = [];
        const findingItemsByLens = new Map<string, FindingTreeItem[]>();
        const findingItemsByNumber = new Map<number, FindingTreeItem>();

        const createLensAndFindings = (lens: string, findings: Finding[]): void => {
            if (!findings || findings.length === 0) {
                return;
            }

            const activeCount = findings.filter((finding) => isActiveStatus(finding.status)).length;
            const maxSeverity = getMaxActiveSeverity(findings);
            lensItems.push(new LensGroupItem(lens, findings.length, activeCount, maxSeverity));

            const findingItems = findings
                .slice()
                .sort((a, b) => {
                    const statusPriority =
                        getStatusVisual(a.status).priority - getStatusVisual(b.status).priority;
                    if (statusPriority !== 0) {
                        return statusPriority;
                    }

                    const severityPriority =
                        (SEVERITY_PRIORITY[getNormalizedSeverity(a.severity)] ?? Number.MAX_SAFE_INTEGER) -
                        (SEVERITY_PRIORITY[getNormalizedSeverity(b.severity)] ?? Number.MAX_SAFE_INTEGER);
                    if (severityPriority !== 0) {
                        return severityPriority;
                    }

                    return a.number - b.number;
                })
                .map((finding) => {
                    const item = new FindingTreeItem(finding, this.scenePath);
                    findingItemsByNumber.set(finding.number, item);
                    return item;
                });

            findingItemsByLens.set(lens, findingItems);
        };

        for (const lens of order) {
            const findings = groups.get(lens);
            createLensAndFindings(lens, findings || []);
        }

        // Any remaining lenses not in the standard order
        for (const [lens, findings] of groups) {
            if (!order.includes(lens) && findings.length > 0) {
                createLensAndFindings(lens, findings);
            }
        }

        this.lensItems = lensItems;
        this.findingItemsByLens = findingItemsByLens;
        this.findingItemsByNumber = findingItemsByNumber;
        this.cacheDirty = false;
    }
}

/**
 * Tree item representing a lens group (parent node).
 */
export class LensGroupItem extends vscode.TreeItem {
    readonly lens: string;

    constructor(lens: string, count: number, activeCount: number, maxSeverity: string) {
        const label = `${lens.charAt(0).toUpperCase() + lens.slice(1)}`;
        super(label, vscode.TreeItemCollapsibleState.Expanded);
        this.lens = lens;
        this.iconPath = new vscode.ThemeIcon(LENS_ICONS[lens] || 'symbol-namespace');
        this.contextValue = 'lensGroup';
        this.resourceUri = buildLensUri(lens, activeCount, count, maxSeverity);
        this.id = `lens:${lens}`;
    }
}

/**
 * Tree item representing a single finding (leaf node).
 *
 * Clicking a finding navigates to its line in the editor.
 * Right-click context menu (via contextValue) offers silence actions for active findings.
 *
 * contextValue values:
 *   - 'finding'          — active finding (can be silenced)
 *   - 'finding-silenced' — silenced finding (rule can be managed)
 *   - 'finding-resolved' — resolved finding (text changed; read-only)
 */
export class FindingTreeItem extends vscode.TreeItem {
    readonly finding: Finding;

    constructor(finding: Finding, scenePath: string | null) {
        const lineRange = finding.line_start !== null
            ? finding.line_end !== null && finding.line_end !== finding.line_start
                ? `L${finding.line_start}-L${finding.line_end}`
                : `L${finding.line_start}`
            : '';

        const originLabel = getFindingOriginLabel(finding);
        const label = `#${finding.number}${lineRange ? ` ${lineRange}` : ''} · ${originLabel}`;
        super(label, vscode.TreeItemCollapsibleState.None);

        this.finding = finding;
        this.description = finding.evidence.slice(0, 60) || finding.location;
        this.tooltip = this.buildTooltip(finding);
        this.iconPath = getFindingIcon(finding);
        this.resourceUri = buildFindingUri(finding);
        this.id = `finding:${finding.number}`;

        // contextValue drives which context menu items are shown
        const status = getNormalizedStatus(finding.status);
        if (status === 'silenced') {
            this.contextValue = 'finding-silenced';
        } else if (status === 'resolved') {
            this.contextValue = 'finding-resolved';
        } else {
            this.contextValue = 'finding';
        }

        // Click navigates to the finding's line in the editor
        const targetPath = finding.scene_path ?? scenePath;
        if (targetPath && finding.line_start !== null) {
            this.command = {
                command: 'litCritic.navigateToFinding',
                title: 'Navigate to finding',
                arguments: [finding],
            };
        }
    }

    private buildTooltip(finding: Finding): vscode.MarkdownString {
        const status = getNormalizedStatus(finding.status);
        const originLabel = getFindingOriginLabel(finding);
        const md = new vscode.MarkdownString();
        md.appendMarkdown(`**#${finding.number} — ${finding.severity.toUpperCase()}** (${finding.lens})\n\n`);
        md.appendMarkdown(`**Origin:** ${originLabel}\n\n`);
        md.appendMarkdown(`**Status:** ${status}\n\n`);
        md.appendMarkdown(`${finding.evidence}\n\n`);
        if (finding.impact) {
            md.appendMarkdown(`**Impact:** ${finding.impact}\n\n`);
        }
        if (finding.options && finding.options.length > 0) {
            md.appendMarkdown('**Suggestions:**\n');
            for (const opt of finding.options) {
                md.appendMarkdown(`- ${opt}\n`);
            }
        }
        return md;
    }
}
