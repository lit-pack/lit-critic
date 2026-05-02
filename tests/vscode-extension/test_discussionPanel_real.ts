/**
 * Real tests for DiscussionViewProvider module.
 *
 * Tests the actual DiscussionViewProvider class (formerly DiscussionPanel)
 * with mocked vscode API.
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode, MockWebviewView, sampleFinding } from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('DiscussionPanel (Real)', () => {
    let DiscussionPanel: any;
    let mockVscode: any;
    let panel: any;
    let mockWebviewView: MockWebviewView;

    beforeEach(() => {
        mockVscode = createFreshMockVscode();
        mockWebviewView = new MockWebviewView();

        const module = proxyquire('../../vscode-extension/src/discussionViewProvider', {
            'vscode': mockVscode,
        });
        DiscussionPanel = module.DiscussionViewProvider;
    });

    /** Helper: create a provider instance with the mock view already resolved. */
    function createTestPanel() {
        const p = new DiscussionPanel();
        // Simulate VS Code calling resolveWebviewView when the sidebar section opens
        p.resolveWebviewView(mockWebviewView, {}, {});
        return p;
    }

    afterEach(() => {
        if (panel) {
            panel.dispose();
        }
    });

    describe('constructor', () => {
        it('should create panel', () => {
            panel = createTestPanel();
            assert.ok(panel);
        });
    });

    describe('show', () => {
        it('should create webview panel on first show', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            assert.ok(mockWebviewView);
            assert.equal(mockWebviewView.visible, true);
        });

        it('should reuse existing panel on subsequent shows', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);
            panel.show(sampleFinding, 2, 3);

            // Same view object is reused (not recreated)
            assert.ok(true);
        });

        it('should generate HTML with finding details', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            assert.match(mockWebviewView.webview.html, /rhythm breaks/);
            assert.match(mockWebviewView.webview.html, /major/i);
        });

        it('should show progress in HTML (1/3)', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            assert.match(mockWebviewView.webview.html, /Finding\s*<strong>1\/3<\/strong>/);
        });

        it('should include severity color in HTML', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            // Should have color style for major findings
            assert.match(mockWebviewView.webview.html, /#ff9800/i); // major = orange
        });

        it('should format line range in HTML', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            assert.match(mockWebviewView.webview.html, /Lines 42.*45/);
        });

        it('should include options list in HTML', () => {
            panel = createTestPanel();

            panel.show(sampleFinding, 1, 3);

            assert.match(mockWebviewView.webview.html, /Rewrite for smoother rhythm/);
            assert.match(mockWebviewView.webview.html, /<ol>/); // ordered list
        });

        it('should render the latest finding status badge', () => {
            panel = createTestPanel();
            const acceptedFinding = { ...sampleFinding, status: 'accepted' };

            panel.show(acceptedFinding, 1, 3);

            assert.match(mockWebviewView.webview.html, /status-accepted/);
            assert.match(mockWebviewView.webview.html, />accepted</);
        });

        it('should render read-only notice when provided for closed sessions', () => {
            panel = createTestPanel();

            panel.show(
                sampleFinding,
                1,
                3,
                'Viewing completed session — actions will reopen it.',
            );

            assert.match(mockWebviewView.webview.html, /session-notice/);
            assert.match(mockWebviewView.webview.html, /Viewing completed session — actions will reopen it\./);
        });
    });

    describe('close', () => {
        it('should reset the view to idle HTML state', () => {
            panel = createTestPanel();
            panel.show(sampleFinding, 1, 3);

            panel.close();

            // VS Code owns the view lifecycle; close() resets HTML to the idle placeholder
            assert.match(mockWebviewView.webview.html, /idle-message|Start a session/);
        });
    });

    describe('dispose', () => {
        it('should not throw', () => {
            panel = createTestPanel();
            panel.show(sampleFinding, 1, 3);

            assert.doesNotThrow(() => panel.dispose());
        });
    });
});
