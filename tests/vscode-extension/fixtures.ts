/**
 * Shared test fixtures and mocks for VS Code extension tests.
 * 
 * Provides mock implementations of:
 * - VS Code API objects
 * - HTTP responses
 * - Sample data (findings, sessions, etc.)
 */

import { EventEmitter } from 'events';

// ---------------------------------------------------------------------------
// Sample Data
// ---------------------------------------------------------------------------

export const sampleFinding = {
    number: 1,
    severity: 'major' as const,
    lens: 'prose',
    location: 'Paragraph 3',
    line_start: 42,
    line_end: 45,
    evidence: 'The rhythm breaks here with an awkward sentence structure.',
    impact: 'Disrupts reading flow and weakens tension.',
    options: [
        'Rewrite for smoother rhythm',
        'Break into two shorter sentences',
    ],
    flagged_by: ['prose'],
    ambiguity_type: null,
    stale: false,
    status: 'pending',
};

export const sampleFindings = [
    sampleFinding,
    {
        number: 2,
        severity: 'critical' as const,
        lens: 'structure',
        location: 'Scene opening',
        line_start: 1,
        line_end: 10,
        evidence: 'Scene lacks clear goal.',
        impact: 'Reader confusion about purpose.',
        options: ['Establish clear scene goal'],
        flagged_by: ['structure'],
        ambiguity_type: null,
        stale: false,
        status: 'pending',
    },
    {
        number: 3,
        severity: 'minor' as const,
        lens: 'prose',
        location: 'Paragraph 8',
        line_start: 78,
        line_end: 78,
        evidence: 'Passive voice: "was seen"',
        impact: 'Minor weakening of prose.',
        options: ['Use active voice'],
        flagged_by: ['prose'],
        ambiguity_type: null,
        stale: false,
        status: 'accepted',
    },
];

export const sampleAnalysisSummary = {
    scene_path: '/test/project/scene01.txt',
    scene_name: 'scene01.txt',
    project_path: '/test/project',
    total_findings: 3,
    current_index: 0,
    glossary_issues: [],
    counts: { critical: 1, major: 1, minor: 1 },
    lens_counts: {
        prose: { critical: 0, major: 1, minor: 1 },
        structure: { critical: 1, major: 0, minor: 0 },
    },
    model: { name: 'sonnet', id: 'claude-sonnet-4-20250514', label: 'Sonnet 4.5' },
    learning: { review_count: 0, preferences: 0, blind_spots: 0 },
    findings_status: sampleFindings.map(f => ({
        number: f.number,
        severity: f.severity,
        lens: f.lens,
        status: f.status,
        location: f.location,
        evidence: f.evidence,
        line_start: f.line_start,
        line_end: f.line_end,
    })),
};

export const sampleFindingResponse = {
    complete: false,
    finding: sampleFinding,
    index: 0,
    current: 1,
    total: 3,
    is_ambiguity: false,
};

export const sampleAdvanceResponse = {
    complete: false,
    finding: sampleFinding,
    index: 0,
    current: 1,
    total: 3,
    is_ambiguity: false,
    scene_change: null,
};

export const sampleSessionInfo = {
    active: true,
    scene_path: '/test/project/scene01.txt',
    scene_name: 'scene01.txt',
    project_path: '/test/project',
    total_findings: 3,
    current_index: 0,
    findings_status: sampleFindings.map(f => ({
        number: f.number,
        severity: f.severity,
        lens: f.lens,
        status: f.status,
        location: f.location,
        evidence: f.evidence,
        line_start: f.line_start,
        line_end: f.line_end,
    })),
};

export const sampleServerConfig = {
    api_key_configured: true,
    available_models: {
        'opus': { label: 'Opus 4.6 (deepest analysis)' },
        'sonnet': { label: 'Sonnet 4.5 (balanced, default)' },
        'haiku': { label: 'Haiku 4.5 (fast & cheap)' },
    },
    default_model: 'sonnet',
};

// ---------------------------------------------------------------------------
// Mock VS Code API
// ---------------------------------------------------------------------------

export class MockDiagnosticCollection {
    private diagnostics = new Map<string, any[]>();

    set(uri: any, diagnostics: any[]): void {
        this.diagnostics.set(uri.toString(), diagnostics);
    }

    get(uri: any): any[] | undefined {
        return this.diagnostics.get(uri.toString());
    }

    clear(): void {
        this.diagnostics.clear();
    }

    dispose(): void {
        this.clear();
    }

    // Test helper
    _getDiagnostics() {
        return this.diagnostics;
    }
}

export class MockStatusBarItem {
    text: string = '';
    tooltip: string = '';
    command: string | undefined = undefined;
    visible: boolean = false;

    show(): void {
        this.visible = true;
    }

    hide(): void {
        this.visible = false;
    }

    dispose(): void {
        this.visible = false;
    }
}

export class MockTreeItem {
    label: string;
    collapsibleState: number;
    description?: string;
    tooltip?: any;
    iconPath?: any;
    command?: any;
    contextValue?: string;
    resourceUri?: any;

    constructor(label: string, collapsibleState: number = 0) {
        this.label = label;
        this.collapsibleState = collapsibleState;
    }
}

export class MockEventEmitter<T> {
    private listeners: Array<(e: T) => void> = [];

    get event() {
        return (listener: (e: T) => void) => {
            this.listeners.push(listener);
            return {
                dispose: () => {
                    const idx = this.listeners.indexOf(listener);
                    if (idx >= 0) this.listeners.splice(idx, 1);
                },
            };
        };
    }

    fire(data: T): void {
        for (const listener of this.listeners) {
            listener(data);
        }
    }

    dispose(): void {
        this.listeners = [];
    }
}

export class MockWebviewPanel {
    webview: {
        html: string;
        onDidReceiveMessage: (handler: any) => { dispose: () => void };
        postMessage: (msg: any) => void;
        _messageHandlers: Array<(msg: any) => void>;
    };
    visible: boolean = true;
    viewColumn: number;
    private _disposeHandlers: Array<() => void> = [];

    constructor(
        public readonly viewType: string,
        public readonly title: string,
        showOptions: any,
        options: any
    ) {
        const messageHandlers: Array<(msg: any) => void> = [];
        
        this.webview = {
            html: '',
            onDidReceiveMessage: (handler: any) => {
                messageHandlers.push(handler);
                return {
                    dispose: () => {
                        const idx = messageHandlers.indexOf(handler);
                        if (idx >= 0) messageHandlers.splice(idx, 1);
                    },
                };
            },
            postMessage: (msg: any) => {
                // No-op in tests, but can be tracked
            },
            _messageHandlers: messageHandlers,
        };
        
        this.viewColumn = typeof showOptions === 'number' ? showOptions : showOptions?.viewColumn || 2;
    }

    onDidDispose(handler: () => void): { dispose: () => void } {
        this._disposeHandlers.push(handler);
        return {
            dispose: () => {
                const idx = this._disposeHandlers.indexOf(handler);
                if (idx >= 0) this._disposeHandlers.splice(idx, 1);
            },
        };
    }

    reveal(viewColumn?: number, preserveFocus?: boolean): void {
        this.visible = true;
        if (viewColumn !== undefined) {
            this.viewColumn = viewColumn;
        }
    }

    dispose(): void {
        this.visible = false;
        for (const handler of this._disposeHandlers) {
            handler();
        }
        this._disposeHandlers = [];
    }

    // Test helper to simulate receiving a message from the webview
    _simulateMessage(msg: any): void {
        for (const handler of this.webview._messageHandlers) {
            handler(msg);
        }
    }
}

/**
 * Create a fresh mock vscode instance (to avoid state leaking between tests).
 */
export function createFreshMockVscode() {
    return {
        languages: {
            createDiagnosticCollection: (name: string) => new MockDiagnosticCollection(),
            registerCodeActionsProvider: (_selector: any, _provider: any, _metadata?: any) => ({ dispose: () => {} }),
        },
    window: {
        createStatusBarItem: (alignment: number, priority: number) => new MockStatusBarItem(),
        createTreeView: (viewId: string, options: any) => ({
            dispose: () => {},
            visible: true,
            reveal: async (_item: any, _options?: any) => {},
        }),
        registerFileDecorationProvider: (provider: any) => ({
            dispose: () => {},
        }),
        setStatusBarMessage: (text: string, hideAfterTimeoutOrThenable?: any) => ({
            dispose: () => {},
        }),
        withProgress: async (options: any, task: any) => {
            return task(
                { report: (_value: any) => {} },
                {
                    isCancellationRequested: false,
                    onCancellationRequested: (_listener: any) => ({ dispose: () => {} }),
                },
            );
        },
        showInformationMessage: async (message: string, ...items: string[]) => items[0],
        showWarningMessage: async (message: string, ...items: string[]) => items[0],
        showErrorMessage: async (message: string, ...items: any[]) => {
            // Skip the { modal: true } options object the real VS Code API accepts as
            // the second argument — return the first *string* button label, just as
            // the real VS Code window API does.
            return items.find((i: any) => typeof i === 'string');
        },
        showQuickPick: async (items: any[], options?: any) => items[0],
        showInputBox: async (options?: any) => 'test input',
        showOpenDialog: async (options?: any) => [],
        createOutputChannel: (name: string) => ({
            appendLine: (text: string) => {},
            show: (preserveFocus?: boolean) => {},
            dispose: () => {},
        }),
        createWebviewPanel: (viewType: string, title: string, showOptions: any, options: any) => new MockWebviewPanel(viewType, title, showOptions, options),
        registerWebviewViewProvider: (_viewId: string, _provider: any, _options?: any) => ({ dispose: () => {} }),
        activeTextEditor: undefined,
        visibleTextEditors: [],
        showTextDocument: async (uri: any, options?: any) => ({}),
    },
    workspace: {
        getConfiguration: (section?: string) => ({
            get: (key: string, defaultValue?: any) => defaultValue,
            update: async (key: string, value: any, target?: any) => {},
        }),
        workspaceFolders: undefined,
        createFileSystemWatcher: (_globPattern: any) => ({
            onDidCreate: (_listener: any) => ({ dispose: () => {} }),
            onDidChange: (_listener: any) => ({ dispose: () => {} }),
            onDidDelete: (_listener: any) => ({ dispose: () => {} }),
            dispose: () => {},
        }),
    },
    commands: {
        registerCommand: (command: string, callback: (...args: any[]) => any) => ({
            dispose: () => {},
        }),
        executeCommand: async (command: string, ...rest: any[]) => {},
    },
    Uri: {
        file: (path: string) => ({ fsPath: path, toString: () => path }),
        parse: (value: string) => {
            const url = new URL(value);
            const path = url.pathname.startsWith('/') ? url.pathname.slice(1) : url.pathname;
            return {
                scheme: url.protocol.replace(':', ''),
                authority: url.host,
                path: `/${path}`,
                query: url.search.startsWith('?') ? url.search.slice(1) : url.search,
                toString: () => value,
            };
        },
    },
    RelativePattern: class {
        baseUri: any;
        pattern: string;
        constructor(baseUri: any, pattern: string) {
            this.baseUri = baseUri;
            this.pattern = pattern;
        }
    },
    Range: class {
        start: any;
        end: any;
        constructor(start: any, end: any) {
            this.start = start;
            this.end = end;
        }
    },
    Position: class {
        line: number;
        character: number;
        constructor(line: number, character: number) {
            this.line = line;
            this.character = character;
        }
    },
    Diagnostic: class {
        range: any;
        message: string;
        severity: number;
        source?: string;
        code?: any;
        tags?: any[];
        constructor(range: any, message: string, severity: number) {
            this.range = range;
            this.message = message;
            this.severity = severity;
        }
    },
    DiagnosticSeverity: {
        Error: 0,
        Warning: 1,
        Information: 2,
        Hint: 3,
    },
    DiagnosticTag: {
        Unnecessary: 1,
        Deprecated: 2,
    },
    TreeItem: class {
        label: string;
        collapsibleState: number;
        description?: string;
        tooltip?: any;
        iconPath?: any;
        command?: any;
        contextValue?: string;
        resourceUri?: any;
        
        constructor(label: string, collapsibleState?: number) {
            this.label = label;
            this.collapsibleState = collapsibleState || 0;
        }
    },
    TreeItemCollapsibleState: {
        None: 0,
        Collapsed: 1,
        Expanded: 2,
    },
    ViewColumn: {
        One: 1,
        Two: 2,
        Beside: -2,
    },
    StatusBarAlignment: {
        Left: 1,
        Right: 2,
    },
    ProgressLocation: {
        SourceControl: 1,
        Window: 10,
        Notification: 15,
    },
    ThemeIcon: class {
        id: string;
        color?: any;
        constructor(id: string, color?: any) {
            this.id = id;
            this.color = color;
        }
    },
    ThemeColor: class {
        id: string;
        constructor(id: string) {
            this.id = id;
        }
    },
    MarkdownString: class {
        value: string = '';
        appendMarkdown(text: string): void {
            this.value += text;
        }
    },
    ConfigurationTarget: {
        Global: 1,
        Workspace: 2,
        WorkspaceFolder: 3,
    },
    CodeActionKind: {
        Empty: { value: '' },
        QuickFix: { value: 'quickfix' },
        Refactor: { value: 'refactor' },
        RefactorExtract: { value: 'refactor.extract' },
        RefactorInline: { value: 'refactor.inline' },
        Source: { value: 'source' },
    },
    CodeAction: class {
        title: string;
        kind: any;
        command?: any;
        isPreferred?: boolean;
        constructor(title: string, kind?: any) {
            this.title = title;
            this.kind = kind;
        }
    },
        EventEmitter: MockEventEmitter,
    };
}

/**
 * MockWebviewView — mirrors MockWebviewPanel but for WebviewView (sidebar panels).
 * Used to test WebviewViewProvider implementations.
 */
export class MockWebviewView {
    webview: {
        html: string;
        options: any;
        onDidReceiveMessage: (handler: any) => { dispose: () => void };
        postMessage: (msg: any) => void;
        _messageHandlers: Array<(msg: any) => void>;
    };
    visible: boolean = true;
    private _disposeHandlers: Array<() => void> = [];

    constructor() {
        const messageHandlers: Array<(msg: any) => void> = [];

        this.webview = {
            html: '',
            options: {},
            onDidReceiveMessage: (handler: any) => {
                messageHandlers.push(handler);
                return {
                    dispose: () => {
                        const idx = messageHandlers.indexOf(handler);
                        if (idx >= 0) messageHandlers.splice(idx, 1);
                    },
                };
            },
            postMessage: (_msg: any) => {},
            _messageHandlers: messageHandlers,
        };
    }

    onDidDispose(handler: () => void): { dispose: () => void } {
        this._disposeHandlers.push(handler);
        return {
            dispose: () => {
                const idx = this._disposeHandlers.indexOf(handler);
                if (idx >= 0) this._disposeHandlers.splice(idx, 1);
            },
        };
    }

    show(_preserveFocus?: boolean): void {
        this.visible = true;
    }

    dispose(): void {
        this.visible = false;
        for (const handler of this._disposeHandlers) {
            handler();
        }
        this._disposeHandlers = [];
    }

    /** Test helper to simulate receiving a message from the webview content */
    _simulateMessage(msg: any): void {
        for (const handler of this.webview._messageHandlers) {
            handler(msg);
        }
    }
}

/** Singleton mock for backward compatibility */
export const mockVscode = createFreshMockVscode();

// ---------------------------------------------------------------------------
// Mock HTTP Responses
// ---------------------------------------------------------------------------

export class MockHttpResponse extends EventEmitter {
    statusCode: number;
    private body: string;

    constructor(statusCode: number, body: any) {
        super();
        this.statusCode = statusCode;
        this.body = typeof body === 'string' ? body : JSON.stringify(body);
    }

    simulateResponse(): void {
        setImmediate(() => {
            this.emit('data', Buffer.from(this.body));
            this.emit('end');
        });
    }
}

export class MockHttpRequest extends EventEmitter {
    private response: MockHttpResponse | null = null;
    private shouldError = false;
    private shouldTimeout = false;

    constructor(response?: MockHttpResponse, shouldError = false, shouldTimeout = false) {
        super();
        this.response = response || null;
        this.shouldError = shouldError;
        this.shouldTimeout = shouldTimeout;
    }

    write(data: any): void {
        // No-op
    }

    end(): void {
        setImmediate(() => {
            if (this.shouldError) {
                this.emit('error', new Error('Network error'));
            } else if (this.shouldTimeout) {
                this.emit('timeout');
            } else if (this.response) {
                this.emit('response', this.response);
                this.response.simulateResponse();
            }
        });
    }

    destroy(): void {
        this.removeAllListeners();
    }
}

export function createMockHttpModule(response?: MockHttpResponse, shouldError = false, shouldTimeout = false) {
    return {
        request: (options: any, callback?: any) => {
            const req = new MockHttpRequest(response, shouldError, shouldTimeout);
            if (callback) {
                req.on('response', callback);
            }
            return req;
        },
        get: (url: string | URL, options: any, callback?: any) => {
            const req = new MockHttpRequest(response, shouldError, shouldTimeout);
            if (typeof options === 'function') {
                callback = options;
            }
            if (callback) {
                req.on('response', callback);
            }
            // Auto-end for GET requests
            setImmediate(() => req.end());
            return req;
        },
    };
}

// ---------------------------------------------------------------------------
// Mock Child Process
// ---------------------------------------------------------------------------

export class MockChildProcess extends EventEmitter {
    exitCode: number | null = null;
    stdout: EventEmitter = new EventEmitter();
    stderr: EventEmitter = new EventEmitter();

    // Explicitly expose emit for TypeScript
    declare emit: (event: string | symbol, ...args: any[]) => boolean;

    kill(signal?: string): void {
        this.exitCode = 0;
        this.emit('exit', 0, signal);
    }

    simulateSuccess(output = 'Server started'): void {
        setImmediate(() => {
            this.stdout.emit('data', Buffer.from(output));
        });
    }

    simulateError(error = 'Server error'): void {
        setImmediate(() => {
            this.stderr.emit('data', Buffer.from(error));
            this.exitCode = 1;
            this.emit('exit', 1, null);
        });
    }
}

export function createMockSpawn(process: MockChildProcess) {
    return (command: string, args: string[], options: any) => {
        return process;
    };
}

/**
 * Create a smart spawn mock that handles Python detection calls separately.
 * Returns different mock processes for:
 * - py -0 (Python Launcher query) → returns version list
 * - any --version (Python version check) → returns "Python 3.13.0"
 * - actual server spawn → returns the provided serverProcess
 */
export function createSmartSpawn(serverProcess: MockChildProcess) {
    return (command: string, args: string[], options?: any) => {
        // Python Launcher query: py -0
        if (command === 'py' && args.includes('-0')) {
            const proc = new MockChildProcess();
            setImmediate(() => {
                proc.stdout.emit('data', Buffer.from('-3.13-64\n'));
                proc.emit('close', 0);
            });
            return proc;
        }
        
        // Python version check: any --version
        if (args.some((a: string) => a === '--version')) {
            const proc = new MockChildProcess();
            setImmediate(() => {
                proc.stdout.emit('data', Buffer.from('Python 3.13.0\n'));
                proc.emit('close', 0);
            });
            return proc;
        }
        
        // Actual server launch
        return serverProcess;
    };
}

/**
 * Create an HTTP mock that fails N times before succeeding.
 * Useful for testing health check retry logic.
 */
export function createStagedHealthCheck(failCount: number = 1) {
    let callCount = 0;
    return {
        get: (url: string, options: any, callback: any) => {
            if (typeof options === 'function') {
                callback = options;
            }
            callCount++;
            const res = { statusCode: callCount > failCount ? 200 : 500 };
            setTimeout(() => callback(res), 5);
            return { on: () => {}, destroy: () => {} };
        },
        request: () => ({ on: () => {}, destroy: () => {} }),
        _getCallCount: () => callCount,
    };
}

// ---------------------------------------------------------------------------
// Phase 2: Management test fixtures
// ---------------------------------------------------------------------------

export const sampleLearningData = {
    project_name: 'Test Novel',
    review_count: 3,
    preferences: [
        { id: 1, description: '[prose] Sentence fragments OK for voice' },
        { id: 2, description: '[structure] Prefer shorter scenes' },
    ],
    blind_spots: [
        { id: 3, description: '[clarity] Pronoun ambiguity in dialogue' },
    ],
    resolutions: [
        { id: 4, description: 'Finding #5 — addressed by splitting paragraph' },
    ],
    ambiguity_intentional: [
        { id: 5, description: 'Chapter 3: dream sequence imagery' },
    ],
    ambiguity_accidental: [
        { id: 6, description: 'Chapter 5: unclear referent (fixed)' },
    ],
};
