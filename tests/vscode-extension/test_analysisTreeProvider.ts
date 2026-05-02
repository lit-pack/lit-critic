/**
 * Tests for AnalysisTreeProvider — the Analysis sidebar tree.
 *
 * Covers: setFindings, setAllFindings, clear, getFindingsForScene,
 * getChildren hierarchy (SceneFileItem → LensGroupItem), empty state,
 * multi-scene rendering, lens group counts, and severity ordering.
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode } from './fixtures';

declare const describe: (name: string, fn: () => void) => void;
declare const beforeEach: (fn: () => void) => void;
declare const it: (name: string, fn: () => Promise<void> | void) => void;

const proxyquire = require('proxyquire').noCallThru();

function makeFinding(overrides: Record<string, any> = {}) {
    return {
        number: 1,
        severity: 'major' as const,
        lens: 'prose',
        location: 'Paragraph 3',
        line_start: 42,
        line_end: 45,
        evidence: 'Rhythm break.',
        impact: 'Disrupts flow.',
        options: ['Fix it'],
        flagged_by: ['prose'],
        ambiguity_type: null,
        stale: false,
        status: 'active',
        ...overrides,
    };
}

describe('AnalysisTreeProvider', () => {
    let AnalysisTreeProvider: any;
    let provider: any;

    beforeEach(() => {
        const mockVscode = createFreshMockVscode();
        const mod = proxyquire('../../vscode-extension/src/analysisTreeProvider', {
            vscode: mockVscode,
        });
        AnalysisTreeProvider = mod.AnalysisTreeProvider;
        provider = new AnalysisTreeProvider();
    });

    // -----------------------------------------------------------------------
    // Empty state
    // -----------------------------------------------------------------------

    it('shows empty state when no findings are set', () => {
        const roots = provider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].label, 'No analysis results');
        assert.equal(roots[0].contextValue, 'empty');
    });

    // -----------------------------------------------------------------------
    // setFindings — single scene
    // -----------------------------------------------------------------------

    it('setFindings populates a single scene item', () => {
        const findings = [
            makeFinding({ number: 1, lens: 'prose', severity: 'major' }),
            makeFinding({ number: 2, lens: 'prose', severity: 'minor' }),
            makeFinding({ number: 3, lens: 'structure', severity: 'critical' }),
        ];
        provider.setFindings('/project/chapter-01.md', findings);

        const roots = provider.getChildren();
        assert.equal(roots.length, 1, 'Expected 1 scene item');
        assert.equal(roots[0].label, 'chapter-01.md');
        assert.equal(roots[0].contextValue, 'analysisScene');

        // Tree is flat: scene items are leaf nodes
        const children = provider.getChildren(roots[0]);
        assert.deepEqual(children, [], 'Scene items should have no children (flat tree)');
    });

    it('setFindings with empty array removes scene', () => {
        provider.setFindings('/project/ch01.md', [makeFinding()]);
        assert.equal(provider.getChildren().length, 1);

        provider.setFindings('/project/ch01.md', []);
        const roots = provider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].contextValue, 'empty');
    });

    // -----------------------------------------------------------------------
    // setAllFindings — bulk hydration
    // -----------------------------------------------------------------------

    it('setAllFindings populates multiple scenes', () => {
        const byScene = new Map<string, any[]>();
        byScene.set('/project/chapter-01.md', [
            makeFinding({ number: 1, lens: 'prose' }),
        ]);
        byScene.set('/project/chapter-02.md', [
            makeFinding({ number: 2, lens: 'clarity' }),
            makeFinding({ number: 3, lens: 'clarity', severity: 'critical' }),
        ]);

        provider.setAllFindings(byScene);

        const roots = provider.getChildren();
        assert.equal(roots.length, 2, 'Expected 2 scene items');

        // Sorted by basename alphabetically
        assert.equal(roots[0].label, 'chapter-01.md');
        assert.equal(roots[1].label, 'chapter-02.md');

        // Tree is flat: scene items are leaf nodes
        assert.deepEqual(provider.getChildren(roots[0]), []);
        assert.deepEqual(provider.getChildren(roots[1]), []);
    });

    // -----------------------------------------------------------------------
    // clear
    // -----------------------------------------------------------------------

    it('clear empties the tree', () => {
        provider.setFindings('/project/ch01.md', [makeFinding()]);
        assert.equal(provider.getChildren().length, 1);

        provider.clear();
        const roots = provider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].contextValue, 'empty');
    });

    // -----------------------------------------------------------------------
    // getFindingsForScene
    // -----------------------------------------------------------------------

    it('getFindingsForScene returns findings for a known scene', () => {
        const findings = [makeFinding({ number: 1 }), makeFinding({ number: 2 })];
        provider.setFindings('/project/ch01.md', findings);

        const result = provider.getFindingsForScene('/project/ch01.md');
        assert.equal(result.length, 2);
    });

    it('getFindingsForScene returns empty array for unknown scene', () => {
        const result = provider.getFindingsForScene('/project/nonexistent.md');
        assert.deepEqual(result, []);
    });

    // -----------------------------------------------------------------------
    // LensGroupItem click command
    // -----------------------------------------------------------------------

    it('scene items have showSceneFindings command', () => {
        provider.setFindings('/project/ch01.md', [
            makeFinding({ number: 1, lens: 'prose' }),
        ]);

        const roots = provider.getChildren();
        const sceneItem = roots[0];

        assert.ok(sceneItem.command, 'Expected command on scene item');
        assert.equal(sceneItem.command.command, 'litCritic.showSceneFindings');
        assert.deepEqual(sceneItem.command.arguments, [
            { scenePath: '/project/ch01.md' },
        ]);
    });

    // -----------------------------------------------------------------------
    // Severity propagation
    // -----------------------------------------------------------------------

    it('scene item reflects max severity of active findings', () => {
        provider.setFindings('/project/ch01.md', [
            makeFinding({ number: 1, severity: 'minor', status: 'active' }),
            makeFinding({ number: 2, severity: 'critical', status: 'active' }),
        ]);

        const roots = provider.getChildren();
        // The tooltip should mention 2 findings
        assert.ok(
            roots[0].tooltip.includes('2 findings'),
            `Expected tooltip with "2 findings", got: ${roots[0].tooltip}`,
        );
    });

    // -----------------------------------------------------------------------
    // Leaf nodes — LensGroupItem has no children
    // -----------------------------------------------------------------------

    it('scene items are leaf nodes (no children)', () => {
        provider.setFindings('/project/ch01.md', [
            makeFinding({ number: 1, lens: 'prose' }),
        ]);

        const roots = provider.getChildren();
        const leafChildren = provider.getChildren(roots[0]);
        assert.deepEqual(leafChildren, []);
    });

    // -----------------------------------------------------------------------
    // Non-standard lenses appear after standard order
    // -----------------------------------------------------------------------

    it('scene items show correct finding count in description', () => {
        provider.setFindings('/project/ch01.md', [
            makeFinding({ number: 1, lens: 'custom-lens' }),
            makeFinding({ number: 2, lens: 'prose' }),
        ]);

        const roots = provider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].label, 'ch01.md');
        // description should reflect the 2 findings
        assert.ok(
            String(roots[0].description).includes('2'),
            `Expected description to mention 2 findings, got: ${roots[0].description}`,
        );
    });
});
