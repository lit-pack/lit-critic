import * as vscode from 'vscode';

export interface OperationProfile {
    id: string;
    title: string;
    statusMessage?: string;
    slowThresholdMs?: number;
    progressThresholdMs?: number;
    progressLocation?: vscode.ProgressLocation;
    cancellable?: boolean;
}

interface OperationTrackerOptions {
    outputChannel?: vscode.OutputChannel;
    progressThresholdMs?: number;
    verySlowThresholdMs?: number;
    now?: () => number;
    withProgress?: typeof vscode.window.withProgress;
}

/**
 * Lightweight wrapper for timing async operations and surfacing user feedback
 * only when an operation is actually taking noticeable time.
 */
export class OperationTracker implements vscode.Disposable {
    private readonly output: vscode.OutputChannel;
    private readonly defaultProgressThresholdMs: number;
    private readonly verySlowThresholdMs: number;
    private readonly now: () => number;
    private readonly withProgress: typeof vscode.window.withProgress;

    constructor(options: OperationTrackerOptions = {}) {
        this.output = options.outputChannel || vscode.window.createOutputChannel('lit-critic');
        this.defaultProgressThresholdMs = options.progressThresholdMs ?? 400;
        this.verySlowThresholdMs = options.verySlowThresholdMs ?? 5000;
        this.now = options.now || (() => Date.now());
        this.withProgress = options.withProgress || vscode.window.withProgress.bind(vscode.window);
    }

    async run<T>(profile: OperationProfile, operation: () => Promise<T>): Promise<T> {
        const progressThresholdMs = profile.progressThresholdMs ?? this.defaultProgressThresholdMs;
        const start = this.now();

        let progressPromise: Thenable<void> | undefined;
        let resolveProgress: (() => void) | undefined;

        const progressTimer = setTimeout(() => {
            progressPromise = this.withProgress(
                {
                    location: profile.progressLocation ?? vscode.ProgressLocation.Notification,
                    title: `lit-critic: ${profile.title}`,
                    cancellable: profile.cancellable ?? false,
                },
                async () => new Promise<void>((resolve) => {
                    resolveProgress = resolve;
                }),
            );
        }, progressThresholdMs);

        const completeUi = async (): Promise<void> => {
            clearTimeout(progressTimer);

            if (resolveProgress) {
                resolveProgress();
                resolveProgress = undefined;
            }
            if (progressPromise) {
                await Promise.resolve(progressPromise).catch(() => {
                    // Best effort cleanup only.
                });
                progressPromise = undefined;
            }
        };

        try {
            const result = await operation();
            await completeUi();

            const durationMs = this.now() - start;
            this.logOperation('ok', profile.id, profile.title, durationMs, durationMs >= this.verySlowThresholdMs ? 'very-slow' : undefined);
            return result;
        } catch (error) {
            await completeUi();

            const durationMs = this.now() - start;
            const message = error instanceof Error ? error.message : String(error);
            this.logOperation('error', profile.id, profile.title, durationMs, message);
            throw error;
        }
    }

    /** Write a timestamped line directly to the lit-critic output channel. */
    log(message: string): void {
        this.output.appendLine(`[${new Date().toISOString()}] ${message}`);
    }

    dispose(): void {
        this.output.dispose();
    }

    private logOperation(status: 'ok' | 'error', id: string, title: string, durationMs: number, detail?: string): void {
        const duration = Math.round(durationMs);
        const marker = status === 'error'
            ? 'ERROR'
            : duration >= this.defaultProgressThresholdMs
                ? 'SLOW'
                : 'OK';

        const suffix = detail ? ` · ${detail}` : '';
        this.output.appendLine(
            `[${new Date().toISOString()}] ${marker} ${id} (${title}) in ${duration}ms${suffix}`,
        );
    }
}
