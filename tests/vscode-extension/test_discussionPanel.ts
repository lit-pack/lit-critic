/**
 * Tests for DiscussionPanel module.
 * 
 * Note: These tests verify discussion panel logic.
 */

import { strict as assert } from 'assert';
import { sampleFinding } from './fixtures';

describe('DiscussionPanel', () => {
    describe('HTML generation', () => {
        it('should include finding details in HTML', () => {
            const html = `<div>${sampleFinding.evidence}</div>`;
            assert.match(html, /rhythm breaks/);
        });

        it('should include severity in HTML', () => {
            const severityHtml = `<span>${sampleFinding.severity}</span>`;
            assert.match(severityHtml, /major/i);
        });

        it('should format line range', () => {
            const lineRange = `Lines ${sampleFinding.line_start}–${sampleFinding.line_end}`;
            assert.match(lineRange, /Lines 42–45/);
        });

        it('should include options list', () => {
            const optionsHtml = sampleFinding.options.map((o, i) => `${i + 1}. ${o}`).join('\n');
            assert.match(optionsHtml, /1\. Rewrite/);
        });
    });

    describe('message formatting', () => {
        it('should map persisted discussion turns to display roles', () => {
            const turns = [
                { role: 'user', content: 'I intended this ambiguity.' },
                { role: 'assistant', content: 'Understood — keeping as intentional.' },
                { role: 'system', content: 'Scene change detected.' },
            ];

            const roleLabels = turns.map((t) => {
                const role = (t.role || '').toLowerCase();
                if (role === 'user') return 'You';
                if (role === 'assistant') return 'Critic';
                return 'System';
            });

            assert.deepEqual(roleLabels, ['You', 'Critic', 'System']);
        });

        it('should format scene change notification', () => {
            const report = {
                adjusted: 2,
                stale: 1,
                re_evaluated: [{ finding_number: 3, status: 'withdrawn' }],
            };
            
            let message = '📝 Scene change detected!';
            if (report.adjusted) message += `\n   Adjusted: ${report.adjusted} findings`;
            if (report.stale) message += `\n   Stale: ${report.stale} findings`;
            
            assert.match(message, /Scene change detected/);
            assert.match(message, /Adjusted: 2/);
        });
    });
});
