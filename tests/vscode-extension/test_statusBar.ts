/**
 * Real tests for StatusBar module.
 *
 * Tests the actual StatusBar class with mocked vscode API.
 * StatusBar creates two StatusBarItems:
 *   1. Primary item (priority 100): main analysis state
 *   2. Loop item (priority 99):     background loop activity + budget display
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode, MockStatusBarItem } from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('StatusBar', () => {
    let StatusBar: any;
    let mockVscode: any;
    let statusBar: any;
    /** The first item created — primary analysis state item. */
    let mockPrimaryItem: MockStatusBarItem;
    /** The second item created — background loop item. */
    let mockLoopItem: MockStatusBarItem;

    beforeEach(() => {
        // Create fresh mocks for each test
        mockVscode = createFreshMockVscode();

        // Capture the two status bar items in creation order.
        // StatusBar creates primary first (priority 100) then loop (priority 99).
        mockPrimaryItem = new MockStatusBarItem();
        mockLoopItem = new MockStatusBarItem();
        let callCount = 0;
        mockVscode.window.createStatusBarItem = () => {
            callCount++;
            return callCount === 1 ? mockPrimaryItem : mockLoopItem;
        };

        // Import the real StatusBar class with mocked vscode
        const module = proxyquire('../../vscode-extension/src/statusBar', {
            'vscode': mockVscode,
        });
        StatusBar = module.StatusBar;
    });

    afterEach(() => {
        if (statusBar) {
            statusBar.dispose();
        }
    });

    describe('constructor', () => {
        it('should create and show the status bar item', () => {
            statusBar = new StatusBar();

            assert.ok(mockPrimaryItem.visible, 'Status bar item should be visible');
        });

        it('should initialize primary item with ready state', () => {
            statusBar = new StatusBar();

            assert.match(mockPrimaryItem.text, /lit-critic/);
            assert.equal(mockPrimaryItem.command, undefined);
        });

        it('should initialize without loop activity (no spinner)', () => {
            statusBar = new StatusBar();

            assert.doesNotMatch(mockPrimaryItem.text, /sync~spin/);
            assert.match(mockPrimaryItem.text, /lit-critic/);
        });
    });

    describe('setReady()', () => {
        it('should set correct text and tooltip on primary item', () => {
            statusBar = new StatusBar();
            statusBar.setReady();

            assert.equal(mockPrimaryItem.text, '$(book) lit-critic');
            assert.equal(mockPrimaryItem.tooltip, 'lit-critic ready');
            assert.equal(mockPrimaryItem.command, undefined);
        });
    });

    describe('setAnalyzing()', () => {
        it('should show spinner with custom message on primary item', () => {
            statusBar = new StatusBar();
            statusBar.setAnalyzing('Running lenses...');

            assert.match(mockPrimaryItem.text, /\$\(sync~spin\)/);
            assert.match(mockPrimaryItem.text, /lit-critic:/);
            assert.match(mockPrimaryItem.text, /Running lenses/);
            assert.match(mockPrimaryItem.tooltip, /Running lenses/);
            assert.match(mockPrimaryItem.tooltip, /lit-critic is busy/);
            assert.equal(mockPrimaryItem.command, undefined);
        });

        it('should use default message when none provided', () => {
            statusBar = new StatusBar();
            statusBar.setAnalyzing();

            assert.match(mockPrimaryItem.text, /Analyzing/);
            assert.match(mockPrimaryItem.tooltip, /lit-critic is busy/);
        });
    });

    describe('setProgress()', () => {
        it('should display current/total format on primary item', () => {
            statusBar = new StatusBar();
            statusBar.setProgress(3, 10);

            assert.equal(mockPrimaryItem.text, '$(book) 3/10 findings');
            assert.match(mockPrimaryItem.tooltip, /3 of 10 findings reviewed/);
            assert.equal(mockPrimaryItem.command, undefined);
        });

        it('should handle different numbers correctly', () => {
            statusBar = new StatusBar();
            statusBar.setProgress(1, 1);

            assert.equal(mockPrimaryItem.text, '$(book) 1/1 findings');
        });
    });

    describe('setComplete()', () => {
        it('should show completion message on primary item', () => {
            statusBar = new StatusBar();
            statusBar.setComplete();

            assert.equal(mockPrimaryItem.text, '$(book) Review complete');
            assert.match(mockPrimaryItem.tooltip, /All findings have been reviewed/);
            assert.equal(mockPrimaryItem.command, undefined);
        });
    });

    describe('setError()', () => {
        it('should show error indicator with message on primary item', () => {
            statusBar = new StatusBar();
            const errorMsg = 'Server connection failed';
            statusBar.setError(errorMsg);

            assert.match(mockPrimaryItem.text, /\$\(error\)/);
            assert.match(mockPrimaryItem.text, /lit-critic/);
            assert.equal(mockPrimaryItem.tooltip, errorMsg);
            assert.equal(mockPrimaryItem.command, undefined);
        });
    });

    describe('command state', () => {
        it('should never set commands on primary item (all states are informational)', () => {
            statusBar = new StatusBar();

            // Test all state transitions
            statusBar.setReady();
            assert.equal(mockPrimaryItem.command, undefined);

            statusBar.setAnalyzing('test');
            assert.equal(mockPrimaryItem.command, undefined);

            statusBar.setProgress(1, 5);
            assert.equal(mockPrimaryItem.command, undefined);

            statusBar.setComplete();
            assert.equal(mockPrimaryItem.command, undefined);

            statusBar.setError('test error');
            assert.equal(mockPrimaryItem.command, undefined);
        });
    });

    describe('loop — activity indicator', () => {
        it('setLoopActivity() should show spinner on the status bar item', () => {
            statusBar = new StatusBar();
            statusBar.setLoopActivity('Extracting knowledge…');

            assert.match(mockPrimaryItem.text, /\$\(sync~spin\)/);
            assert.match(mockPrimaryItem.text, /Extracting knowledge/);
            assert.match(mockPrimaryItem.tooltip, /Extracting knowledge/);
        });

        it('setLoopActivity() should visually override the ready state', () => {
            statusBar = new StatusBar();
            statusBar.setReady();
            statusBar.setLoopActivity('Quick analysis…');

            // Single item now shows loop activity, overriding ready state
            assert.match(mockPrimaryItem.text, /sync~spin/);
            assert.match(mockPrimaryItem.text, /Quick analysis/);
        });

        it('setLoopIdle() should clear spinner and restore primary state', () => {
            statusBar = new StatusBar();
            statusBar.setLoopActivity('Extracting knowledge…');
            statusBar.setLoopIdle();

            assert.match(mockPrimaryItem.text, /book/);
            assert.doesNotMatch(mockPrimaryItem.text, /sync~spin/);
        });
    });

    describe('loop — budget display', () => {
        it('updateLoopBudget() should show cost in tooltip when non-zero', () => {
            statusBar = new StatusBar();
            statusBar.updateLoopBudget(0.005, 1200);

            // Budget is shown in tooltip (small cost in cents)
            assert.match(mockPrimaryItem.tooltip, /¢/);
            assert.match(mockPrimaryItem.tooltip, /1,200/);  // formatted tokens
        });

        it('updateLoopBudget() should show dollars in tooltip for cost >= $0.01', () => {
            statusBar = new StatusBar();
            statusBar.updateLoopBudget(0.012, 5000);

            assert.match(mockPrimaryItem.tooltip, /\$/);
            assert.doesNotMatch(mockPrimaryItem.tooltip, /¢/);
        });

        it('updateLoopBudget() should not overwrite activity spinner', () => {
            statusBar = new StatusBar();
            statusBar.setLoopActivity('Quick analysis…');
            statusBar.updateLoopBudget(0.005, 1200);

            // Spinner should still be shown while loop is active
            assert.match(mockPrimaryItem.text, /sync~spin/);
        });

        it('budget is visible in tooltip after setLoopIdle() following activity + budget_updated', () => {
            statusBar = new StatusBar();
            statusBar.setLoopActivity('Quick analysis…');
            statusBar.updateLoopBudget(0.005, 1200);
            statusBar.setLoopIdle();

            // Item returns to primary state; budget is shown in tooltip
            assert.match(mockPrimaryItem.text, /book/);
            assert.match(mockPrimaryItem.tooltip, /¢/);
        });

        it('resetLoopBudget() should clear budget from tooltip', () => {
            statusBar = new StatusBar();
            statusBar.updateLoopBudget(0.012, 3000);
            statusBar.resetLoopBudget();

            // Budget should no longer appear in tooltip
            assert.doesNotMatch(mockPrimaryItem.tooltip || '', /¢|\$[0-9]/);
            assert.doesNotMatch(mockPrimaryItem.tooltip || '', /spend/);
        });
    });

    describe('dispose()', () => {
        it('should dispose the status bar item', () => {
            statusBar = new StatusBar();
            statusBar.dispose();

            assert.equal(mockPrimaryItem.visible, false);
        });
    });
});
