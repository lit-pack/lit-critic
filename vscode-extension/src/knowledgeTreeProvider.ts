import * as vscode from 'vscode';

import { ApiClient } from './apiClient';
import {
    KnowledgeCategoryKey,
    KnowledgeEntityTreeItemPayload,
    KnowledgeOverrideRecord,
    KnowledgeReviewFlag,
    KnowledgeReviewResponse,
} from './types';

interface CategorySnapshot {
    key: KnowledgeCategoryKey;
    label: string;
    entities: EntitySnapshot[];
}

interface EntitySnapshot {
    payload: KnowledgeEntityTreeItemPayload;
}

type KnowledgeTreeElement =
    | CategoryGroupItem
    | EntityItem
    | EmptyStateItem;

const CATEGORY_CONFIG: Array<{ key: KnowledgeCategoryKey; label: string }> = [
    { key: 'characters', label: 'Characters' },
    { key: 'terms', label: 'Terms' },
    { key: 'threads', label: 'Threads' },
    { key: 'timeline', label: 'Timeline' },
];

export class KnowledgeTreeProvider implements vscode.TreeDataProvider<KnowledgeTreeElement> {
    private _onDidChangeTreeData = new vscode.EventEmitter<KnowledgeTreeElement | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private projectPath: string | null = null;
    private apiClient: ApiClient | null = null;
    private categories: CategorySnapshot[] = CATEGORY_CONFIG.map((config) => ({
        ...config,
        entities: [],
    }));
    private _entityItemCache = new Map<string, EntityItem>();
    private _categoryGroupItemCache = new Map<KnowledgeCategoryKey, CategoryGroupItem>();
    private _flaggedEntityKeys = new Set<string>();
    private _staleEntityKeys = new Set<string>();
    private _allEntitiesStale = false;
    private _orphanedSceneKeys: Set<string> = new Set<string>();

    setStaleEntityKeys(keys: Set<string>): void {
        this._staleEntityKeys = new Set(keys);
        this._onDidChangeTreeData.fire();
    }

    setAllEntitiesStale(value: boolean): void {
        this._allEntitiesStale = value;
        this._onDidChangeTreeData.fire();
    }

    setOrphanedSceneKeys(keys: Set<string>): void {
        this._orphanedSceneKeys = new Set(keys);
        this._onDidChangeTreeData.fire();
    }

    setApiClient(client: ApiClient): void {
        this.apiClient = client;
    }

    setProjectPath(projectPath: string): void {
        this.projectPath = projectPath;
    }

    async refresh(): Promise<void> {
        if (!this.apiClient || !this.projectPath) {
            this.clear();
            return;
        }

        try {
            const categoryPromises = CATEGORY_CONFIG.map(async (config) => {
                const review = await this.apiClient!.getKnowledgeReview(config.key, this.projectPath!);
                return { snapshot: this.toCategorySnapshot(config.key, config.label, review), review };
            });

            const results = await Promise.all(categoryPromises);

            // Seed flag/stale Sets from API response so tree state is correct on
            // startup and after DB copy without requiring a separate "Check for Changes".
            const newFlaggedKeys = new Set<string>();
            const newStaleKeys = new Set<string>();
            for (const { review } of results) {
                const cat = review.category;
                for (const entity of (review.entities ?? [])) {
                    const ek = toOptionalString((entity as Record<string, unknown>).entity_key);
                    if (!ek || !cat) { continue; }
                    if ((entity as Record<string, unknown>).flagged) {
                        newFlaggedKeys.add(`${cat}:${ek}`);
                    }
                    if ((entity as Record<string, unknown>).stale) {
                        newStaleKeys.add(`${cat}:${ek}`);
                    }
                }
            }
            this._flaggedEntityKeys = newFlaggedKeys;
            this._staleEntityKeys = newStaleKeys;
            this._allEntitiesStale = false;

            this.categories = results.map((r) => r.snapshot);
            this._onDidChangeTreeData.fire();
        } catch (err) {
            console.error('Failed to load knowledge view:', err);
            this.categories = CATEGORY_CONFIG.map((config) => ({
                ...config,
                entities: [],
            }));
            this._onDidChangeTreeData.fire();
        }
    }

    clear(): void {
        this.categories = CATEGORY_CONFIG.map((config) => ({
            ...config,
            entities: [],
        }));
        this._entityItemCache.clear();
        this._categoryGroupItemCache.clear();
        this._flaggedEntityKeys.clear();
        this._orphanedSceneKeys.clear();
        this._onDidChangeTreeData.fire();
    }

    setFlaggedEntities(flags: KnowledgeReviewFlag[]): void {
        this._flaggedEntityKeys = new Set(flags.map((f) => `${f.category}:${f.entity_key}`));
        this._onDidChangeTreeData.fire();
    }

    clearFlaggedEntities(): void {
        this._flaggedEntityKeys.clear();
        this._onDidChangeTreeData.fire();
    }

    isFlagged(category: KnowledgeCategoryKey, entityKey: string): boolean {
        return this._flaggedEntityKeys.has(`${category}:${entityKey}`);
    }

    clearEntityFlag(category: KnowledgeCategoryKey, entityKey: string): void {
        const key = `${category}:${entityKey}`;
        if (this._flaggedEntityKeys.has(key)) {
            this._flaggedEntityKeys.delete(key);
            this._onDidChangeTreeData.fire();
        }
    }

    getEntityItem(category: KnowledgeCategoryKey, entityKey: string): EntityItem | null {
        return this._entityItemCache.get(`${category}:${entityKey}`) ?? null;
    }

    getFirstEntityPayload(): KnowledgeEntityTreeItemPayload | null {
        for (const category of this.categories) {
            if (category.entities.length > 0) {
                return category.entities[0].payload;
            }
        }
        return null;
    }

    getEntityPayload(category: KnowledgeCategoryKey, entityKey: string): KnowledgeEntityTreeItemPayload | null {
        const categorySnapshot = this.categories.find((snapshot) => snapshot.key === category);
        if (!categorySnapshot) {
            return null;
        }

        const entitySnapshot = categorySnapshot.entities.find((entity) => entity.payload.entityKey === entityKey);
        return entitySnapshot?.payload ?? null;
    }

    getAdjacentEntityPayload(
        category: KnowledgeCategoryKey,
        entityKey: string,
        direction: 'next' | 'previous',
    ): KnowledgeEntityTreeItemPayload | null {
        const payloads = this.categories.flatMap((snapshot) =>
            snapshot.entities.map((entity) => entity.payload),
        );
        const currentIndex = payloads.findIndex((payload) =>
            payload.category === category && payload.entityKey === entityKey,
        );
        if (currentIndex < 0) {
            return null;
        }

        const offset = direction === 'next' ? 1 : -1;
        return payloads[currentIndex + offset] ?? null;
    }

    getTreeItem(element: KnowledgeTreeElement): vscode.TreeItem {
        return element;
    }

    getParent(element: KnowledgeTreeElement): vscode.ProviderResult<KnowledgeTreeElement> {
        if (element instanceof EntityItem) {
            return this._categoryGroupItemCache.get(element.payload.category);
        }
        return undefined;
    }

    getChildren(element?: KnowledgeTreeElement): vscode.ProviderResult<KnowledgeTreeElement[]> {
        if (!this.projectPath) {
            return [new EmptyStateItem('No entries found')];
        }

        if (!element) {
            const categoryItems = this.categories.map((snapshot) => {
                const item = new CategoryGroupItem(snapshot);
                this._categoryGroupItemCache.set(snapshot.key, item);
                return item;
            });
            return [...categoryItems];
        }

        if (element instanceof CategoryGroupItem) {
            if (element.snapshot.entities.length === 0) {
                return [new EmptyStateItem(`No ${element.snapshot.label.toLowerCase()} extracted`)];
            }
            return element.snapshot.entities.map((entity, index) => {
                // Recompute volatile flags from current state so the rendered item
                // always reflects the latest flagged/stale status, regardless of
                // whether setFlaggedEntities() was called before or after refresh().
                const sceneFilename = toOptionalString(entity.payload.entity['scene_filename']);
                const livePayload: KnowledgeEntityTreeItemPayload = {
                    ...entity.payload,
                    flagged: this.isFlagged(entity.payload.category, entity.payload.entityKey),
                    stale: this._allEntitiesStale || this._staleEntityKeys.has(`${entity.payload.category}:${entity.payload.entityKey}`),
                    orphaned: sceneFilename !== undefined && isSceneOrphaned(sceneFilename, this._orphanedSceneKeys),
                };
                const item = new EntityItem(livePayload, index);
                this._entityItemCache.set(`${livePayload.category}:${livePayload.entityKey}`, item);
                return item;
            });
        }

        return [];
    }

    private toCategorySnapshot(
        key: KnowledgeCategoryKey,
        label: string,
        review: KnowledgeReviewResponse,
    ): CategorySnapshot {
        const overrideMap = this.buildOverrideMap(review.overrides);
        const entities = Array.isArray(review.entities)
            ? review.entities
                .filter((entry): entry is Record<string, unknown> => Boolean(entry && typeof entry === 'object'))
                .map((entity, index) => this.toEntitySnapshot(key, entity, index, overrideMap))
            : [];
        return { key, label, entities };
    }

    private buildOverrideMap(overrides: KnowledgeReviewResponse['overrides']): Map<string, KnowledgeOverrideRecord[]> {
        const map = new Map<string, KnowledgeOverrideRecord[]>();
        if (!Array.isArray(overrides)) {
            return map;
        }

        for (const override of overrides) {
            const entityKey = toOptionalString(override?.entity_key);
            if (!entityKey) {
                continue;
            }
            const existing = map.get(entityKey) ?? [];
            existing.push(override);
            map.set(entityKey, existing);
        }

        return map;
    }

    private toEntitySnapshot(
        category: KnowledgeCategoryKey,
        entity: Record<string, unknown>,
        index: number,
        overrideMap: Map<string, KnowledgeOverrideRecord[]>,
    ): EntitySnapshot {
        const entityKey = getEntityKey(category, entity, index);
        const overrideFields = (overrideMap.get(entityKey) ?? [])
            .map((override) => toOptionalString(override.field_name))
            .filter((fieldName): fieldName is string => Boolean(fieldName));
        const payload: KnowledgeEntityTreeItemPayload = {
            category,
            entityKey,
            label: getEntityLabel(category, entity, index),
            entity,
            overrideFields,
            overrideCount: overrideFields.length,
            hasOverrides: overrideFields.length > 0,
            locked: Boolean(entity.entity_locked),
            flagged: this.isFlagged(category, entityKey),
            stale: this._allEntitiesStale || this._staleEntityKeys.has(`${category}:${entityKey}`),
        };
        return { payload };
    }

}

class CategoryGroupItem extends vscode.TreeItem {
    constructor(public readonly snapshot: CategorySnapshot) {
        super(snapshot.label, vscode.TreeItemCollapsibleState.Collapsed);
        this.id = `knowledge:category:${snapshot.key}`;
        this.contextValue = 'knowledgeCategory';
        this.iconPath = new vscode.ThemeIcon('symbol-class');
        this.description = `${snapshot.entities.length} items`;
    }
}

export class EntityItem extends vscode.TreeItem {
    constructor(public readonly payload: KnowledgeEntityTreeItemPayload, index: number) {
        super(payload.label, vscode.TreeItemCollapsibleState.None);
        this.id = `knowledge:entity:${payload.category}:${payload.entityKey}:${index}`;
        this.contextValue = payload.orphaned
            ? 'knowledgeEntityOrphaned'
            : payload.flagged
                ? 'knowledgeEntityFlagged'
                : payload.locked
                    ? 'knowledgeEntityLocked'
                    : payload.hasOverrides
                        ? 'knowledgeEntityOverridden'
                        : 'knowledgeEntity';
        this.iconPath = payload.orphaned
            ? new vscode.ThemeIcon('circle-slash')
            : payload.flagged
                ? new vscode.ThemeIcon('warning')
                : payload.stale
                    ? new vscode.ThemeIcon('warning')
                    : payload.locked
                        ? new vscode.ThemeIcon('lock')
                        : new vscode.ThemeIcon('symbol-property');
        // resourceUri drives FileDecoration color. Priority: orphaned > stale > flagged > locked > overridden.
        if (payload.orphaned) {
            this.resourceUri = vscode.Uri.parse(`knowledge-orphaned://${payload.category}/${encodeURIComponent(payload.entityKey)}`);
        } else if (payload.stale) {
            this.resourceUri = vscode.Uri.parse(`source-stale://${payload.category}/${encodeURIComponent(payload.entityKey)}`);
        } else if (payload.flagged) {
            this.resourceUri = vscode.Uri.parse(`knowledge-flagged://${payload.category}/${encodeURIComponent(payload.entityKey)}`);
        } else if (payload.locked) {
            this.resourceUri = vscode.Uri.parse(`knowledge-locked://${payload.category}/${encodeURIComponent(payload.entityKey)}`);
        } else if (payload.hasOverrides) {
            this.resourceUri = vscode.Uri.parse(`knowledge-overridden://${payload.category}/${encodeURIComponent(payload.entityKey)}`);
        }
        this.description = getEntityDescription(payload);
        this.tooltip = getEntityTooltip(payload);
        this.command = {
            command: 'litCritic.openKnowledgeReviewPanel',
            title: 'Review Knowledge Entry',
            arguments: [payload],
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

function getEntityLabel(category: KnowledgeCategoryKey, entity: Record<string, unknown>, index: number): string {
    const fallback = `${category.slice(0, 1).toUpperCase()}${category.slice(1)} #${index + 1}`;
    if (category === 'characters') {
        return String(entity.name ?? entity.character ?? entity.entity_key ?? fallback);
    }
    if (category === 'terms') {
        return String(entity.term ?? entity.name ?? entity.entity_key ?? fallback);
    }
    if (category === 'threads') {
        return String(entity.thread_id ?? entity.title ?? entity.entity_key ?? fallback);
    }
    return String(entity.scene_filename ?? entity.summary ?? entity.entity_key ?? fallback);
}

function getEntityKey(category: KnowledgeCategoryKey, entity: Record<string, unknown>, index: number): string {
    return toOptionalString(entity.entity_key)
        ?? (category === 'characters' ? toOptionalString(entity.name) : undefined)
        ?? (category === 'terms' ? toOptionalString(entity.term) : undefined)
        ?? (category === 'threads' ? toOptionalString(entity.thread_id) : undefined)
        ?? (category === 'timeline' ? toOptionalString(entity.scene_filename) : undefined)
        ?? `${category}:${index + 1}`;
}

function getEntityDescription(payload: KnowledgeEntityTreeItemPayload): string | undefined {
    const parts: string[] = [];
    if (payload.orphaned) { parts.push('⚠ scene not found'); }
    if (payload.stale) { parts.push('stale'); }
    if (payload.flagged) { parts.push('flagged'); }
    if (payload.locked) { parts.push('locked'); }
    if (payload.hasOverrides) { parts.push('overridden'); }
    return parts.length > 0 ? parts.join(' · ') : undefined;
}

function getEntityTooltip(payload: KnowledgeEntityTreeItemPayload): string {
    const summaryLines = getEntitySummaryLines(payload.entity)
        .map(([field, value]) => `${field}: ${value}`);
    const status = payload.orphaned
        ? 'Orphaned (⚠ scene not found)'
        : payload.hasOverrides
            ? `Author-corrected (${payload.overrideCount} override${payload.overrideCount === 1 ? '' : 's'})`
            : 'Extracted';

    return [
        `${toCategoryLabel(payload.category)}: ${payload.label}`,
        `Entity key: ${payload.entityKey}`,
        `Status: ${status}`,
        payload.hasOverrides ? `Overridden fields: ${payload.overrideFields.join(', ')}` : undefined,
        ...summaryLines,
    ].filter((line): line is string => Boolean(line)).join('\n');
}

function getEntitySummaryLines(entity: Record<string, unknown>): Array<[string, string]> {
    return Object.entries(entity)
        .filter(([key]) => key !== 'entity_key')
        .map(([key, value]) => [key, toDisplayValue(value)] as [string, string | undefined])
        .filter((entry): entry is [string, string] => Boolean(entry[1]))
        .slice(0, 4);
}

function toDisplayValue(value: unknown): string | undefined {
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed.length > 0 ? trimmed : undefined;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value);
    }
    return undefined;
}

function toCategoryLabel(category: KnowledgeCategoryKey): string {
    return CATEGORY_CONFIG.find((entry) => entry.key === category)?.label ?? category;
}

function toOptionalString(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined;
    }
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : undefined;
}

/**
 * Returns true if `sceneFilename` (basename or relative path) matches any key
 * in `orphanedKeys`. The orphaned scene key from the API is a relative path
 * like "text/she_wakes_up.md"; the entity field may store only the basename.
 */
function isSceneOrphaned(sceneFilename: string, orphanedKeys: ReadonlySet<string>): boolean {
    for (const key of orphanedKeys) {
        if (key === sceneFilename) { return true; }
        // key = "text/she_wakes_up.md", sceneFilename = "she_wakes_up.md"
        const base = key.includes('/') ? key.slice(key.lastIndexOf('/') + 1) : key;
        if (base === sceneFilename) { return true; }
    }
    return false;
}
