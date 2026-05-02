import { Finding } from '../types';

export function getDiscussionPanelHtml(
    finding: Finding,
    current: number,
    total: number,
    readOnlyNotice?: string,
): string {
    const severityColor: Record<string, string> = {
        'critical': '#f44336',
        'major': '#ff9800',
        'minor': '#2196f3',
    };
    const color = severityColor[finding.severity] || '#ff9800';

    const formatLineRange = (f: Pick<Finding, 'line_start' | 'line_end' | 'location'>): string => (
        f.line_start !== null
            ? f.line_end !== null && f.line_end !== f.line_start
                ? `Lines ${f.line_start}–${f.line_end}`
                : `Line ${f.line_start}`
            : f.location
    );

    const lineRange = formatLineRange(finding);

    const optionsHtml = finding.options.length > 0
        ? `<div class="options"><strong>Suggestions:</strong><ol>${finding.options.map(o => `<li>${escapeHtml(o)}</li>`).join('')}</ol></div>`
        : '';

    const statusLabel = (finding.status || 'pending').toLowerCase();
    const statusHtml = `<span class="status-badge status-${escapeHtml(statusLabel)}">${escapeHtml(statusLabel)}</span>`;

    const noticeHtml = readOnlyNotice
        ? `<div class="session-notice">${escapeHtml(readOnlyNotice)}</div>`
        : '';

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
:root {
    --bg: var(--vscode-editor-background);
    --fg: var(--vscode-editor-foreground);
    --border: var(--vscode-panel-border);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--fg);
    background: var(--bg);
    padding: 12px;
}

/* Finding header */
.finding-header {
    border-left: 4px solid ${color};
    padding: 8px 12px;
    margin-bottom: 12px;
    background: var(--vscode-textBlockQuote-background);
    border-radius: 2px;
    overflow-y: auto;
}
.finding-header .meta {
    font-size: 0.85em;
    opacity: 0.8;
    margin-bottom: 4px;
}
.finding-header .status-badge {
    display: inline-block;
    margin-left: 6px;
    padding: 1px 6px;
    border-radius: 10px;
    border: 1px solid var(--border);
    text-transform: uppercase;
    font-size: 0.78em;
    letter-spacing: 0.04em;
    opacity: 0.95;
}
.finding-header .status-pending { opacity: 0.7; }
.finding-header .status-accepted {
    color: var(--vscode-testing-iconPassed, #4caf50);
    border-color: var(--vscode-testing-iconPassed, #4caf50);
}
.finding-header .status-rejected {
    color: var(--vscode-errorForeground, #f44336);
    border-color: var(--vscode-errorForeground, #f44336);
}
.finding-header .status-withdrawn {
    color: var(--vscode-disabledForeground, #9e9e9e);
    border-color: var(--vscode-disabledForeground, #9e9e9e);
}
.finding-header .status-revised {
    color: var(--vscode-editorInfo-foreground, #2196f3);
    border-color: var(--vscode-editorInfo-foreground, #2196f3);
}
.finding-header .status-escalated {
    color: var(--vscode-editorWarning-foreground, #ff9800);
    border-color: var(--vscode-editorWarning-foreground, #ff9800);
}
.finding-header .severity {
    color: ${color};
    font-weight: bold;
    text-transform: uppercase;
}
.finding-header .evidence {
    margin: 8px 0;
    line-height: 1.5;
}
.finding-header .impact {
    font-style: italic;
    opacity: 0.9;
    margin-top: 6px;
}
.options { margin-top: 8px; }
.options ol { padding-left: 20px; margin-top: 4px; }
.options li { margin-bottom: 2px; }

.session-notice {
    border: 1px solid var(--vscode-editorInfo-foreground);
    background: color-mix(in srgb, var(--vscode-editorInfo-foreground) 12%, transparent);
    color: var(--vscode-editorInfo-foreground);
    border-radius: 4px;
    padding: 8px 10px;
    margin-bottom: 8px;
    font-size: 0.9em;
}

.progress {
    font-size: 0.85em;
    opacity: 0.7;
    text-align: center;
    margin-top: 12px;
}
</style>
</head>
<body>
${noticeHtml}
<div class="finding-header">
    <div class="meta">
        Finding <strong>${current}/${total}</strong> •
        <span class="severity">${escapeHtml(finding.severity)}</span> •
        ${escapeHtml(finding.lens)} •
        ${escapeHtml(lineRange)}
        ${statusHtml}
    </div>
    <div class="evidence">${escapeHtml(finding.evidence)}</div>
    ${finding.impact ? `<div class="impact">${escapeHtml(finding.impact)}</div>` : ''}
    ${optionsHtml}
</div>

<div class="progress">Finding ${current} of ${total}</div>
</body>
</html>`;
}

/** Escape HTML entities for safe insertion. */
export function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
