import { KnowledgeReviewPanelFieldState, KnowledgeReviewPanelState } from '../types';

function escapeHtml(value: unknown): string {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderValue(value: unknown, emptyLabel = 'Not set'): string {
    if (value === null || value === undefined || value === '') {
        return `<em>${escapeHtml(emptyLabel)}</em>`;
    }

    return escapeHtml(value);
}

/** Returns the CSS class name for a given stateColor value. */
function stateColorClass(stateColor: KnowledgeReviewPanelFieldState['stateColor']): string {
    if (!stateColor) { return ''; }
    return ` state-${stateColor}`;
}

function renderNavigatorItem(field: KnowledgeReviewPanelFieldState, selectedFieldName?: string): string {
    const selectedClass = selectedFieldName === field.fieldName ? ' selected' : '';
    const overrideClass = field.hasOverride ? ' has-override' : '';
    const colorClass = stateColorClass(field.stateColor);
    const fieldName = escapeHtml(field.fieldName);

    return [
        `<button type="button" class="field-nav-item${selectedClass}${overrideClass}" onclick="selectField('${fieldName}')">`,
        '<div class="field-nav-main">',
        `<div class="field-title${colorClass}">${escapeHtml(field.fieldLabel)}</div>`,
        `<div class="field-preview">${renderValue(field.effectiveValue)}</div>`,
        '</div>',
        '<div class="field-badges">',
        field.hasOverride ? '<span class="badge badge-override">overridden</span>' : '',
        field.stateColor === 'locked' ? '<span class="badge badge-locked">locked</span>' : '',
        field.isDirty ? '<span class="badge">dirty</span>' : '',
        '</div>',
        '</button>',
    ].join('');
}

function renderSelectedField(field: KnowledgeReviewPanelFieldState): string {
    const fieldName = escapeHtml(field.fieldName);
    const overrideClass = field.hasOverride ? ' has-override' : '';
    const colorClass = stateColorClass(field.stateColor);
    // If the field is dirty we re-enter edit mode so the textarea stays visible after a re-render.
    const editingClass = field.isDirty ? ' editing' : '';

    // Review section — shown by default, hidden when .editing is active.
    const reviewBody = field.hasOverride
        ? [
            '<div class="value-row">',
            '<span class="value-row-label">Extracted</span>',
            `<div class="value-row-content">${renderValue(field.extractedValue)}</div>`,
            '</div>',
            '<div class="value-row override-active">',
            '<span class="value-row-label">Override</span>',
            `<div class="value-row-content">${renderValue(field.overrideValue)}</div>`,
            '</div>',
        ].join('')
        : `<div class="value-block">${renderValue(field.extractedValue)}</div>`;

    const reviewActions = [
        '<div class="review-actions">',
        '<button type="button" class="icon-button" onclick="toggleEditMode()">&#9998; Edit</button>',
        field.hasOverride ? `<button type="button" class="secondary" onclick="resetField('${fieldName}')">Reset</button>` : '',
        '</div>',
    ].join('');

    // Edit section — hidden by default, shown when .editing is active.
    const editBody = [
        '<div class="value-row">',
        '<span class="value-row-label">Extracted</span>',
        `<div class="value-row-content">${renderValue(field.extractedValue)}</div>`,
        '</div>',
        '<label class="editor-label" for="knowledge-review-draft">Override draft</label>',
        `<textarea id="knowledge-review-draft" data-field-name="${fieldName}" data-effective-value="${escapeHtml(field.effectiveValue)}" oninput="handleDraftChange(event)">${escapeHtml(field.draftValue)}</textarea>`,
        '<div class="field-actions">',
        `<button type="button" class="primary" onclick="saveField('${fieldName}')"${field.isDirty ? '' : ' disabled'}>Save</button>`,
        `<button type="button" class="secondary" onclick="cancelEdit()">Cancel</button>`,
        '</div>',
    ].join('');

    return [
        `<section class="field-card selected-field-card${overrideClass}${editingClass}">`,
        '<div class="field-header">',
        '<div>',
        `<div class="field-title${colorClass}">${escapeHtml(field.fieldLabel)}</div>`,
        `<div class="field-subtitle">Override for <strong>${escapeHtml(field.fieldName)}</strong></div>`,
        '</div>',
        '<div class="field-badges">',
        field.hasOverride ? '<span class="badge badge-override">overridden</span>' : '',
        field.stateColor === 'locked' ? '<span class="badge badge-locked">locked</span>' : '',
        field.isDirty ? '<span class="badge">dirty</span>' : '',
        '</div>',
        '</div>',
        `<div class="review-section">${reviewBody}${reviewActions}</div>`,
        `<div class="edit-section">${editBody}</div>`,
        '</section>',
    ].join('');
}

/**
 * Renders the entity-level state pills in priority order: stale → flagged → locked → overridden.
 * Returns an HTML string of zero or more pill spans.
 */
function renderStatePills(state: KnowledgeReviewPanelState): string {
    const pills: string[] = [];
    if (state.stale) {
        pills.push('<span class="state-pill state-pill-stale" title="Source inputs are stale — run Refresh Knowledge">stale</span>');
    }
    if (state.flagged) {
        pills.push('<span class="state-pill state-pill-flagged" title="Flagged for review by the reconciliation pass">flagged</span>');
    }
    if (state.locked) {
        pills.push('<span class="state-pill state-pill-locked" title="Locked — protected from LLM updates">locked</span>');
    }
    if (state.hasOverrides) {
        pills.push('<span class="state-pill state-pill-overridden" title="Has author overrides applied">overridden</span>');
    }
    return pills.join('');
}

/**
 * Returns the CSS class for the top-bar accent border based on the highest-priority active state.
 * Priority: stale → flagged → locked → overridden → none
 */
function topBarAccentClass(state: KnowledgeReviewPanelState): string {
    if (state.stale) { return ' accent-stale'; }
    if (state.flagged) { return ' accent-flagged'; }
    if (state.locked) { return ' accent-locked'; }
    if (state.hasOverrides) { return ' accent-overridden'; }
    return '';
}

function renderPanelMarkup(state: KnowledgeReviewPanelState): string {
    const selectedField = state.fields.find((field) => field.fieldName === state.selectedFieldName) ?? state.fields[0];
    const fieldNavigatorMarkup = state.fields.length > 0
        ? state.fields.map((field) => renderNavigatorItem(field, selectedField?.fieldName)).join('')
        : '<section class="field-card"><div class="field-title">No editable fields available.</div></section>';
    const detailMarkup = selectedField
        ? renderSelectedField(selectedField)
        : '<section class="field-card"><div class="field-title">No editable fields available.</div></section>';

    const pills = renderStatePills(state);
    const accentClass = topBarAccentClass(state);

    return [
        `<div class="top-bar${accentClass}">`,
        '<div class="top-bar-identity">',
        `<span class="entity-label">${escapeHtml(state.entityLabel)}</span>`,
        `<span class="top-bar-meta">${escapeHtml(state.categoryLabel)} &middot; ${escapeHtml(state.entityKey)}</span>`,
        '</div>',
        pills ? `<div class="top-bar-pills">${pills}</div>` : '',
        '</div>',
        '<div class="panel-layout">',
        '<aside class="field-nav">',
        '<div class="field-nav-heading">Fields</div>',
        `<div class="fields">${fieldNavigatorMarkup}</div>`,
        '</aside>',
        `<section class="field-detail">${detailMarkup}</section>`,
        '</div>',
    ].join('');
}

export function getKnowledgeReviewPanelHtml(initialState: KnowledgeReviewPanelState): string {
    const initialStateJson = JSON.stringify(initialState)
        .replace(/</g, '\\u003c')
        .replace(/<\//g, '<\\/');
    const initialMarkup = renderPanelMarkup(initialState);

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>lit-critic - Knowledge Review</title>
<style>
:root {
    --bg: var(--vscode-editor-background);
    --fg: var(--vscode-editor-foreground);
    --muted: var(--vscode-descriptionForeground);
    --border: var(--vscode-panel-border);
    --input-bg: var(--vscode-input-background);
    --input-fg: var(--vscode-input-foreground);
    --input-border: var(--vscode-input-border);
    --button-bg: var(--vscode-button-background);
    --button-fg: var(--vscode-button-foreground);
    --button-hover: var(--vscode-button-hoverBackground);
    --button-secondary-bg: var(--vscode-button-secondaryBackground);
    --button-secondary-fg: var(--vscode-button-secondaryForeground);
    --color-stale: var(--vscode-litCritic-staleForeground);
    --color-flagged: var(--vscode-litCritic-flaggedForReviewForeground);
    --color-locked: var(--vscode-litCritic-authorOverrideForeground);
    --color-overridden: var(--vscode-litCritic-overriddenForeground);
}

* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 12px;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--fg);
    background: var(--bg);
}

/* ── Top bar ─────────────────────────────────────────────────────────────── */

.top-bar {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 10px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 12px;
    justify-content: space-between;
    border-left-width: 3px;
}

/* Accent left-border colors by highest-priority state */
.top-bar.accent-stale    { border-left-color: var(--color-stale); }
.top-bar.accent-flagged  { border-left-color: var(--color-flagged); }
.top-bar.accent-locked   { border-left-color: var(--color-locked); }
.top-bar.accent-overridden { border-left-color: var(--color-overridden); }

.top-bar-identity {
    display: flex;
    flex-direction: column;
    min-width: 0;
}

.entity-label {
    font-weight: 600;
    font-size: 1.05em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.top-bar-meta {
    color: var(--muted);
    font-size: 0.85em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ── State pills ─────────────────────────────────────────────────────────── */

.top-bar-pills {
    display: flex;
    gap: 5px;
    flex-shrink: 0;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.state-pill {
    border-radius: 999px;
    padding: 1px 8px;
    font-size: 0.78em;
    font-weight: 500;
    border: 1px solid;
    cursor: default;
}

.state-pill-stale {
    color: var(--color-stale);
    border-color: var(--color-stale);
}

.state-pill-flagged {
    color: var(--color-flagged);
    border-color: var(--color-flagged);
}

.state-pill-locked {
    color: var(--color-locked);
    border-color: var(--color-locked);
}

.state-pill-overridden {
    color: var(--color-overridden);
    border-color: var(--color-overridden);
}

/* ── Layout ──────────────────────────────────────────────────────────────── */

.panel-layout {
    display: grid;
    gap: 12px;
    grid-template-columns: minmax(180px, 220px) minmax(0, 1fr);
    align-items: start;
}

.field-nav,
.field-card {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
}

.field-nav {
    max-height: calc(100vh - 160px);
    overflow-y: auto;
}

.field-nav-heading {
    font-size: 0.78em;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
}

.fields {
    display: grid;
    gap: 5px;
}

.field-nav-item {
    width: 100%;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    color: inherit;
    padding: 5px 8px;
    text-align: left;
    display: flex;
    justify-content: space-between;
    gap: 6px;
    align-items: flex-start;
}

.field-nav-item.selected,
.selected-field-card {
    border-color: var(--vscode-focusBorder);
}

.field-nav-main {
    min-width: 0;
    flex: 1;
    overflow: hidden;
}

.field-preview {
    margin-top: 2px;
    color: var(--muted);
    font-size: 0.88em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.field-subtitle {
    margin-top: 4px;
    color: var(--muted);
    font-size: 0.9em;
}

.field-header {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
}

.field-title {
    font-weight: 600;
}

/* ── Per-field state colors ──────────────────────────────────────────────── */

.field-title.state-stale     { color: var(--color-stale); }
.field-title.state-flagged   { color: var(--color-flagged); }
.field-title.state-locked    { color: var(--color-locked); }
.field-title.state-overridden { color: var(--color-overridden); }

/* ── Badges ──────────────────────────────────────────────────────────────── */

.field-badges {
    display: flex;
    gap: 6px;
}

.badge {
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 1px 6px;
    font-size: 0.78em;
    color: var(--muted);
}

.badge-override {
    color: var(--color-overridden);
    border-color: var(--color-overridden);
}

.badge-locked {
    color: var(--color-locked);
    border-color: var(--color-locked);
}

/* ── Review / edit sections ──────────────────────────────────────────────── */

.review-section,
.edit-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

/* edit-section hidden by default; review-section hidden when card has .editing */
.selected-field-card .edit-section { display: none; }
.selected-field-card.editing .review-section { display: none; }
.selected-field-card.editing .edit-section { display: flex; }

.value-block {
    border: 1px dashed var(--border);
    border-radius: 4px;
    padding: 8px;
    min-height: 40px;
}

.value-row {
    display: flex;
    gap: 8px;
    align-items: baseline;
}

.value-row-label {
    flex-shrink: 0;
    color: var(--muted);
    font-size: 0.78em;
    text-transform: uppercase;
    width: 64px;
}

.value-row-content {
    flex: 1;
    min-width: 0;
}

.override-active .value-row-content {
    font-weight: 500;
}

.review-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 2px;
}

.icon-button {
    background: transparent;
    border: 1px solid var(--border);
    color: inherit;
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    font: inherit;
    font-size: 0.9em;
}

.icon-button:hover {
    border-color: var(--vscode-focusBorder);
}

.editor-label {
    display: block;
    color: var(--muted);
    font-size: 0.9em;
}

textarea {
    width: 100%;
    min-height: 88px;
    resize: vertical;
    padding: 8px;
    border-radius: 4px;
    border: 1px solid var(--input-border);
    background: var(--input-bg);
    color: var(--input-fg);
    font: inherit;
}

.field-actions,
.nav-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

button {
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font: inherit;
}

button.primary {
    background: var(--button-bg);
    color: var(--button-fg);
}

button.primary:hover:enabled {
    background: var(--button-hover);
}

button.secondary {
    background: var(--button-secondary-bg);
    color: var(--button-secondary-fg);
}

button:disabled {
    cursor: default;
    opacity: 0.6;
}

@media (max-width: 500px) {
    .panel-layout {
        grid-template-columns: 1fr;
    }
}
</style>
</head>
<body>
    <div id="app">${initialMarkup}</div>
    <script>
        const vscode = typeof acquireVsCodeApi === 'function' ? acquireVsCodeApi() : null;
        const initialState = ${initialStateJson};
        window.__LIT_CRITIC_KNOWLEDGE_REVIEW_INITIAL_STATE__ = initialState;

        function send(message) {
            if (vscode) {
                vscode.postMessage(message);
            }
        }

        function handleDraftChange(event) {
            const target = event && event.target ? event.target : null;
            const fieldName = target ? target.getAttribute('data-field-name') : undefined;

            if (!fieldName) {
                return;
            }

            const value = target.value || '';
            const effectiveValue = target.getAttribute('data-effective-value') || '';
            const isDirty = value !== effectiveValue;
            const saveButton = document.querySelector('button.primary[onclick^="saveField"]');
            if (saveButton) {
                saveButton.disabled = !isDirty;
            }

            send({ type: 'change-field', fieldName, value });
        }

        function getDraftValue(fieldName) {
            const selector = 'textarea[data-field-name="' + String(fieldName).replace(/"/g, '\\\\"') + '"]';
            const field = document.querySelector(selector);
            return field ? field.value : '';
        }

        function saveField(fieldName) {
            send({ type: 'save-field', fieldName, value: getDraftValue(fieldName) });
        }

        function resetField(fieldName) {
            send({ type: 'reset-field', fieldName });
        }

        function selectField(fieldName) {
            send({ type: 'select-field', fieldName });
        }

        function toggleEditMode() {
            const card = document.querySelector('.selected-field-card');
            if (card) { card.classList.toggle('editing'); }
        }

        function cancelEdit() {
            const card = document.querySelector('.selected-field-card');
            if (card) { card.classList.remove('editing'); }
            const textarea = document.getElementById('knowledge-review-draft');
            if (textarea) {
                const effectiveValue = textarea.getAttribute('data-effective-value') || '';
                textarea.value = effectiveValue;
                const saveButton = document.querySelector('button.primary[onclick^="saveField"]');
                if (saveButton) { saveButton.disabled = true; }
                const fieldName = textarea.getAttribute('data-field-name') || '';
                send({ type: 'change-field', fieldName, value: effectiveValue });
            }
        }

        window.send = send;
        window.handleDraftChange = handleDraftChange;
        window.saveField = saveField;
        window.resetField = resetField;
        window.selectField = selectField;
        window.toggleEditMode = toggleEditMode;
        window.cancelEdit = cancelEdit;
    </script>
</body>
</html>`;
}
