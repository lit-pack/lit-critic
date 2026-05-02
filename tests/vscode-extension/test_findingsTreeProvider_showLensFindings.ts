/**
 * Tests for FindingsTreeProvider.showLensFindings — the filtered detail view
 * that shows only a specific scene+lens combination when a user clicks a
 * lens group in the Analysis tree.
 *
 * Covers: showLensFindings display, LensFilterContextItem header, finding items
 * render with correct severity/actions, empty filtered state, clear resets filter.
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode, sampleFindings } from './fixtures';

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
        evidence: 'Rhythm break in the narrative.',
        impact: 'Disrupts reading flow.',
        options: ['Fix it'],
        flagged_by: ['prose'],
        ambiguity_type: null,
        stale: false,
        status: 'active',
        ...overrides,
    };
}

describe('FindingsTreeProvider — showLensFindings', () => {
    let FindingsTreeProvider: any;
    let LensFilterContextItem: any;
    let FindingTreeItem: any;
    let provider: any;

    beforeEach(() => {
        const mockVscode = createFreshMockVscode();
        const mod = proxyquire('../../vscode-extension/src/findingsTreeProvider', {
            vscode: mockVscode,
        });
        FindingsTreeProvider = mod.FindingsTreeProvider;
        LensFilterContextItem = mod.LensFilterContextItem;
        FindingTreeItem = mod.FindingTreeItem;
        provider = new FindingsTreeProvider();
    });

    // -----------------------------------------------------------------------
    // Basic filtered display
    // -----------------------------------------------------------------------

    it('showLensFindings renders context header + finding items', () => {
        const findings = [
            makeFinding({ number: 1, lens: 'prose', severity: 'major' }),
            makeFinding({ number: 2, lens: 'prose', severity: 'minor' }),
        ];

        provider.showLensFindings(findings, '/project/chapter-01.md', 'prose');

        const roots = provider.getChildren();
        // First item is the LensFilterContextItem header
        assert.equal(roots.length, 3, 'Expected 1 header + 2 finding items');
        assert.equal(roots[0].contextValue, 'lensFilterContext');
        assert.ok(
            roots[0].label.includes('chapter-01.md'),
            `Expected header label to contain filename, got: ${roots[0].label}`,
        );
        assert.ok(
            roots[0].label.includes('Prose'),
            `Expected header label to contain lens name, got: ${roots[0].label}`,
        );
    });

    it('header has correct icon for known lens', () => {
        provider.showLensFindings(
            [makeFinding({ number: 1, lens: 'structure' })],
            '/project/ch01.md',
            'structure',
        );

        const roots = provider.getChildren();
        const header = roots[0];
        assert.equal(header.iconPath.id, 'list-tree', 'structure lens should use list-tree icon');
    });

    // -----------------------------------------------------------------------
    // Finding items in filtered mode
    // -----------------------------------------------------------------------

    it('finding items have correct contextValue based on status', () => {
        const findings = [
            makeFinding({ number: 1, status: 'active' }),
            makeFinding({ number: 2, status: 'silenced' }),
            makeFinding({ number: 3, status: 'resolved' }),
        ];

        provider.showLensFindings(findings, '/project/ch01.md', 'prose');

        const roots = provider.getChildren();
        // roots[0] is header, roots[1..3] are findings
        assert.equal(roots[1].contextValue, 'finding');
        assert.equal(roots[2].contextValue, 'finding-silenced');
        assert.equal(roots[3].contextValue, 'finding-resolved');
    });

    it('finding items show severity icons for active findings', () => {
        const findings = [
            makeFinding({ number: 1, severity: 'critical', status: 'active' }),
            makeFinding({ number: 2, severity: 'major', status: 'active' }),
            makeFinding({ number: 3, severity: 'minor', status: 'active' }),
        ];

        provider.showLensFindings(findings, '/project/ch01.md', 'prose');

        const roots = provider.getChildren();
        assert.equal(roots[1].iconPath.id, 'error', 'critical → error icon');
        assert.equal(roots[2].iconPath.id, 'warning', 'major → warning icon');
        assert.equal(roots[3].iconPath.id, 'info', 'minor → info icon');
    });

    it('finding items have navigation command when line_start is present', () => {
        const findings = [
            makeFinding({ number: 1, line_start: 10, scene_path: '/project/ch01.md' }),
        ];

        provider.showLensFindings(findings, '/project/ch01.md', 'prose');

        const roots = provider.getChildren();
        const findingItem = roots[1];
        assert.ok(findingItem.command, 'Expected navigation command');
        assert.equal(findingItem.command.command, 'litCritic.navigateToFinding');
    });

    // -----------------------------------------------------------------------
    // Empty filtered state
    // -----------------------------------------------------------------------

    it('shows empty message when no findings match the filter', () => {
        provider.showLensFindings([], '/project/ch01.md', 'prose');

        const roots = provider.getChildren();
        assert.equal(roots.length, 2, 'Expected header + empty state');
        assert.equal(roots[0].contextValue, 'lensFilterContext');
        assert.equal(roots[1].contextValue, 'empty');
        assert.equal(roots[1].label, 'No findings for this lens');
    });

    // -----------------------------------------------------------------------
    // clear resets filter mode
    // -----------------------------------------------------------------------

    it('clear removes lens filter and returns to normal mode', () => {
        provider.showLensFindings(
            [makeFinding({ number: 1, lens: 'prose' })],
            '/project/ch01.md',
            'prose',
        );

        // Verify filtered mode is active
        let roots = provider.getChildren();
        assert.equal(roots[0].contextValue, 'lensFilterContext');

        // Clear and verify back to empty unfiltered state
        provider.clear();
        roots = provider.getChildren();
        assert.equal(roots.length, 1);
        assert.equal(roots[0].contextValue, 'empty');
        assert.equal(roots[0].label, 'No analysis snapshot loaded');
    });

    // -----------------------------------------------------------------------
    // Flat structure (no lens groups in filtered mode)
    // -----------------------------------------------------------------------

    it('findings are flat in filtered mode (no lens group parents)', () => {
        const findings = [
            makeFinding({ number: 1, lens: 'prose' }),
            makeFinding({ number: 2, lens: 'prose' }),
        ];

        provider.showLensFindings(findings, '/project/ch01.md', 'prose');

        const roots = provider.getChildren();
        // In filtered mode, getParent of a finding should return undefined
        const findingItem = roots[1];
        const parent = provider.getParent(findingItem);
        assert.equal(parent, undefined, 'Findings should have no parent in filtered mode');
    });

    // -----------------------------------------------------------------------
    // Switching between filtered views
    // -----------------------------------------------------------------------

    it('calling showLensFindings again replaces the previous filter', () => {
        provider.showLensFindings(
            [makeFinding({ number: 1, lens: 'prose' })],
            '/project/ch01.md',
            'prose',
        );

        provider.showLensFindings(
            [makeFinding({ number: 2, lens: 'structure' }), makeFinding({ number: 3, lens: 'structure' })],
            '/project/ch02.md',
            'structure',
        );

        const roots = provider.getChildren();
        assert.equal(roots.length, 3, 'Expected header + 2 structure findings');
        assert.ok(roots[0].label.includes('chapter-02') || roots[0].label.includes('ch02'),
            `Expected header for ch02, got: ${roots[0].label}`);
        assert.ok(roots[0].label.includes('Structure'),
            `Expected Structure lens in header, got: ${roots[0].label}`);
    });
});
