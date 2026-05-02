import { strict as assert } from 'assert';
import * as path from 'path';
import { createFreshMockVscode } from './fixtures';

declare const describe: (name: string, fn: () => void) => void;
declare const beforeEach: (fn: () => void) => void;
declare const it: (name: string, fn: () => Promise<void> | void) => void;

const proxyquire = require('proxyquire').noCallThru();

describe('KnowledgeTreeProvider', () => {
    let KnowledgeTreeProvider: any;
    let treeProvider: any;

    beforeEach(() => {
        const mockVscode = createFreshMockVscode();
        const module = proxyquire('../../vscode-extension/src/knowledgeTreeProvider', {
            vscode: mockVscode,
        });

        KnowledgeTreeProvider = module.KnowledgeTreeProvider;
        treeProvider = new KnowledgeTreeProvider();
    });

    it('shows empty state when no project path is set', () => {
        const roots = treeProvider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].label, 'No entries found');
        assert.equal(roots[0].contextValue, 'empty');
    });

    it('loads grouped knowledge categories and CANON/STYLE status', async () => {
        treeProvider.setApiClient({
            async getKnowledgeReview(category: string, projectPath: string) {
                assert.equal(projectPath, '/repo');
                switch (category) {
                case 'characters':
                    return { entities: [{ name: 'Alice', category: 'Lead' }], overrides: [] };
                case 'terms':
                    return { entities: [{ term: 'Aether', definition: 'Energy field' }], overrides: [{}] };
                case 'threads':
                    return { entities: [], overrides: [] };
                case 'timeline':
                    return { entities: [{ scene_filename: 'scene01.txt', summary: 'Opening beat' }], overrides: [] };
                default:
                    return { entities: [], overrides: [] };
                }
            },
        });
        treeProvider.setProjectPath('/repo');

        await treeProvider.refresh();

        // KnowledgeTreeProvider has 4 category groups (Characters, Terms, Threads, Timeline)
        const roots = treeProvider.getChildren();
        assert.equal(roots.length, 4);

        const charactersGroup = roots.find((item: any) => item.label === 'Characters');
        const termsGroup = roots.find((item: any) => item.label === 'Terms');
        assert.ok(charactersGroup, 'Expected Characters group');
        assert.ok(termsGroup, 'Expected Terms group');
        assert.equal(charactersGroup.description, '1 items');
        assert.equal(termsGroup.description, '1 items');
    });

    it('shows category empty state when no entities are extracted', async () => {
        treeProvider.setApiClient({
            async getKnowledgeReview() {
                return { entities: [], overrides: [] };
            },
        });
        treeProvider.setProjectPath('/repo');

        await treeProvider.refresh();

        const roots = treeProvider.getChildren();
        const threadsGroup = roots.find((item: any) => item.label === 'Threads');
        const threadChildren = treeProvider.getChildren(threadsGroup);
        assert.equal(threadChildren.length, 1);
        assert.equal(threadChildren[0].label, 'No threads extracted');
        assert.equal(threadChildren[0].contextValue, 'empty');
    });

    it('creates edit-ready entity items with override metadata and edit command', async () => {
        treeProvider.setApiClient({
            async getKnowledgeReview(category: string) {
                if (category === 'characters') {
                    return {
                        entities: [{ entity_key: 'char:alice', name: 'Alice', category: 'Lead' }],
                        overrides: [{ entity_key: 'char:alice', field_name: 'category', value: 'Protagonist' }],
                    };
                }
                return { entities: [], overrides: [] };
            },
        });
        treeProvider.setProjectPath('/repo');

        await treeProvider.refresh();

        const roots = treeProvider.getChildren();
        const charactersGroup = roots.find((item: any) => item.label === 'Characters');
        const characterItems = treeProvider.getChildren(charactersGroup);

        assert.equal(characterItems.length, 1);
        assert.equal(characterItems[0].label, 'Alice');
        assert.equal(characterItems[0].contextValue, 'knowledgeEntityOverridden');
        assert.equal(characterItems[0].iconPath?.id, 'symbol-property');
        assert.equal(characterItems[0].command?.command, 'litCritic.openKnowledgeReviewPanel');
        // Production now includes flagged, locked, stale fields on the payload
        assert.deepEqual(characterItems[0].command?.arguments?.[0], {
            category: 'characters',
            entityKey: 'char:alice',
            label: 'Alice',
            entity: { entity_key: 'char:alice', name: 'Alice', category: 'Lead' },
            overrideFields: ['category'],
            overrideCount: 1,
            hasOverrides: true,
            locked: false,
            flagged: false,
            stale: false,
            orphaned: false,
        });
        // Description is now derived from flag/stale/lock/override state
        assert.equal(characterItems[0].description, 'overridden');
        assert.ok(String(characterItems[0].tooltip).includes('Entity key: char:alice'));
        assert.ok(String(characterItems[0].tooltip).includes('Overridden fields: category'));
    });
});
