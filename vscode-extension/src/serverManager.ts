/**
 * Server Manager — spawns and manages the FastAPI backend process.
 *
 * Lifecycle:
 *   1. On activation, spawn `python lit-critic-server.py --port <port>`
 *   2. Health-check loop until the server responds
 *   3. On deactivation (or stop command), kill the process
 */

import * as vscode from 'vscode';
import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as http from 'http';

export class ServerManager implements vscode.Disposable {
    private process: ChildProcess | null = null;
    private outputChannel: vscode.OutputChannel;
    private _isRunning = false;
    private _port: number;
    private _repoRoot: string;
    /** Captures startup-time process failures even if `this.process` is nulled by exit handlers. */
    private _startupExitCode: number | null = null;
    private _startupExitSignal: NodeJS.Signals | null = null;
    private _startupError: Error | null = null;
    /** Configurable ready-wait timeout (ms). Override in tests for fast failure. */
    private _readyTimeoutMs: number;
    /** Configurable health-check poll interval (ms). Override in tests for fast polling. */
    private _readyIntervalMs: number;

    /** Fired when the server becomes ready (health check passed). */
    readonly onReady: vscode.Event<void>;
    private _onReadyEmitter = new vscode.EventEmitter<void>();

    /** Fired when the server stops (process exit or kill). */
    readonly onStopped: vscode.Event<void>;
    private _onStoppedEmitter = new vscode.EventEmitter<void>();

    constructor(
        repoRoot: string,
        options?: { readyTimeoutMs?: number; readyIntervalMs?: number },
    ) {
        this._repoRoot = repoRoot;
        this.outputChannel = vscode.window.createOutputChannel('lit-critic Server');
        this.onReady = this._onReadyEmitter.event;
        this.onStopped = this._onStoppedEmitter.event;

        const config = vscode.workspace.getConfiguration('litCritic');
        this._port = config.get<number>('serverPort', 8000);

        this._readyTimeoutMs = options?.readyTimeoutMs ?? 120000;
        this._readyIntervalMs = options?.readyIntervalMs ?? 500;
    }

    get isRunning(): boolean {
        return this._isRunning;
    }

    get port(): number {
        return this._port;
    }

    get baseUrl(): string {
        return `http://127.0.0.1:${this._port}`;
    }

    get repoRoot(): string {
        return this._repoRoot;
    }

    /**
     * Start the backend server. Resolves when the health check passes.
     * If the server is already running (externally or from a prior start), reuses it.
     */
    async start(onStage?: (stage: 'checking' | 'launching' | 'waiting' | 'ready') => void): Promise<void> {
        // Reset startup failure markers for this start attempt.
        this._startupExitCode = null;
        this._startupExitSignal = null;
        this._startupError = null;

        onStage?.('checking');

        // Check if something is already listening on the port
        if (await this.healthCheck()) {
            this._isRunning = true;
            this.outputChannel.appendLine(`Server already running on port ${this._port}`);
            onStage?.('ready');
            this._onReadyEmitter.fire();
            return;
        }

        const config = vscode.workspace.getConfiguration('litCritic');
        this._port = config.get<number>('serverPort', 8000);

        // Find suitable Python interpreter
        const pythonPath = await this.findPython();
        
        if (!pythonPath) {
            const message = 'No suitable Python found (requires >= 3.10). ' +
                           'Please install Python 3.10+ or configure ' +
                           '"litCritic.pythonPath" in settings.';
            vscode.window.showErrorMessage(message);
            this.outputChannel.appendLine(`ERROR: ${message}`);
            throw new Error(message);
        }

        const scriptPath = path.join(this._repoRoot, 'lit-critic-server.py');

        // Split pythonPath to handle cases like "py -3"
        const pythonParts = pythonPath.split(' ');
        const pythonCmd = pythonParts[0];
        const pythonArgs = pythonParts.slice(1).concat([scriptPath, '--port', String(this._port)]);

        this.outputChannel.appendLine(`Using Python: ${pythonPath}`);
        this.outputChannel.appendLine(`Starting server: ${pythonCmd} ${pythonArgs.join(' ')}`);
        this.outputChannel.show(true);
        onStage?.('launching');

        this.process = spawn(pythonCmd, pythonArgs, {
            cwd: this._repoRoot,
            // PYTHONUNBUFFERED=1 forces Python to flush stdout immediately instead
            // of block-buffering it when piped, so print() output appears in the
            // output channel without delay.
            env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONUTF8: '1' },
            stdio: ['ignore', 'pipe', 'pipe'],
        });

        this.process.stdout?.on('data', (data: Buffer) => {
            this.outputChannel.appendLine(data.toString().trimEnd());
        });

        this.process.stderr?.on('data', (data: Buffer) => {
            this.outputChannel.appendLine(data.toString().trimEnd());
        });

        this.process.on('error', (err) => {
            this.outputChannel.appendLine(`Server process error: ${err.message}`);
            this._startupError = err;
            this._isRunning = false;
            this._onStoppedEmitter.fire();
        });

        this.process.on('exit', (code, signal) => {
            this.outputChannel.appendLine(
                `Server process exited (code=${code}, signal=${signal})`
            );
            this._startupExitCode = code;
            this._startupExitSignal = signal;
            this._isRunning = false;
            this.process = null;
            this._onStoppedEmitter.fire();
        });

        // Wait for the server to become ready
        onStage?.('waiting');
        await this.waitForReady(this._readyTimeoutMs, this._readyIntervalMs);
        onStage?.('ready');
    }

    /**
     * Stop the backend server.
     */
    stop(): void {
        if (this.process) {
            this.outputChannel.appendLine('Stopping server...');
            this.process.kill('SIGTERM');
            // Force kill after 5 seconds
            setTimeout(() => {
                if (this.process) {
                    this.process.kill('SIGKILL');
                    this.process = null;
                }
            }, 5000);
        }
        this._isRunning = false;
    }

    dispose(): void {
        this.stop();
        this._onReadyEmitter.dispose();
        this._onStoppedEmitter.dispose();
        this.outputChannel.dispose();
    }

    /**
     * Single health check — GET /api/config.
     */
    private healthCheck(): Promise<boolean> {
        return new Promise((resolve) => {
            const req = http.get(`${this.baseUrl}/api/config`, { timeout: 2000 }, (res) => {
                resolve(res.statusCode === 200);
            });
            req.on('error', () => resolve(false));
            req.on('timeout', () => {
                req.destroy();
                resolve(false);
            });
        });
    }

    /**
     * Find a suitable Python interpreter.
     * Tries configured path first, then auto-detects platform-specific candidates.
     */
    private async findPython(): Promise<string | null> {
        const config = vscode.workspace.getConfiguration('litCritic');
        const configuredPath = config.get<string>('pythonPath');
        
        // If user configured a specific path (not default 'python'), verify and use it
        if (configuredPath && configuredPath !== 'python') {
            this.outputChannel.appendLine(`Checking configured Python: ${configuredPath}`);
            if (await this.verifyPythonVersion(configuredPath)) {
                return configuredPath;
            } else {
                this.outputChannel.appendLine(`WARNING: Configured Python at "${configuredPath}" is not valid or < 3.10`);
                vscode.window.showWarningMessage(
                    `Configured Python "${configuredPath}" is not suitable (requires >= 3.10). Trying auto-detection...`
                );
            }
        }
        
        // Auto-detect based on platform
        const candidates = await this.getPythonCandidates();
        this.outputChannel.appendLine(`Auto-detecting Python from candidates: ${candidates.join(', ')}`);
        
        for (const cmd of candidates) {
            this.outputChannel.appendLine(`Trying: ${cmd}`);
            if (await this.verifyPythonVersion(cmd)) {
                this.outputChannel.appendLine(`✓ Found suitable Python: ${cmd}`);
                return cmd;
            }
        }
        
        this.outputChannel.appendLine('✗ No suitable Python found');
        return null;
    }

    /**
     * Get platform-specific Python command candidates.
     * On Windows, queries Python Launcher to find installed versions and prioritizes highest suitable version.
     */
    private async getPythonCandidates(): Promise<string[]> {
        const isWindows = process.platform === 'win32';
        
        if (isWindows) {
            // Query Python Launcher for installed versions
            const launcherVersions = await this.queryPythonLauncher();
            
            if (launcherVersions.length > 0) {
                this.outputChannel.appendLine(`Found Python versions via launcher: ${launcherVersions.join(', ')}`);
                // Return specific version commands first, then fallbacks
                return [...launcherVersions, 'python3', 'python'];
            }
            
            // Fallback if launcher query fails
            return ['python3', 'python'];
        } else {
            // On macOS/Linux, python3 is standard
            return ['python3', 'python'];
        }
    }

    /**
     * Query Windows Python Launcher to find installed Python versions >= 3.10.
     * Returns commands like ["py -3.13", "py -3.12", "py -3.10"] sorted highest first.
     */
    private async queryPythonLauncher(): Promise<string[]> {
        return new Promise((resolve) => {
            try {
                const proc = spawn('py', ['-0'], {
                    timeout: 2000,
                    shell: false
                });
                
                let output = '';
                proc.stdout?.on('data', (data: Buffer) => {
                    output += data.toString();
                });
                proc.stderr?.on('data', (data: Buffer) => {
                    output += data.toString();
                });
                
                proc.on('close', (code) => {
                    if (code !== 0) {
                        resolve([]);
                        return;
                    }
                    
                    // Parse output like:
                    // -3.8-64 *
                    // -3.13-64
                    const versions: Array<{major: number, minor: number}> = [];
                    const lines = output.split('\n');
                    
                    for (const line of lines) {
                        const match = line.match(/-(\d+)\.(\d+)/);
                        if (match) {
                            const major = parseInt(match[1]);
                            const minor = parseInt(match[2]);
                            
                            // Only include Python 3.x versions >= 3.10
                            if (major === 3 && minor >= 10) {
                                versions.push({ major, minor });
                            }
                        }
                    }
                    
                    // Sort by version (highest first)
                    versions.sort((a, b) => {
                        if (a.major !== b.major) return b.major - a.major;
                        return b.minor - a.minor;
                    });
                    
                    // Convert to py commands
                    const commands = versions.map(v => `py -${v.major}.${v.minor}`);
                    resolve(commands);
                });
                
                proc.on('error', () => {
                    resolve([]);
                });
            } catch (error) {
                resolve([]);
            }
        });
    }

    /**
     * Verify that a Python command exists and meets version requirements (>= 3.10).
     * Command can include arguments (e.g., "py -3").
     */
    private async verifyPythonVersion(command: string): Promise<boolean> {
        return new Promise((resolve) => {
            try {
                // Split command to handle cases like "py -3"
                const parts = command.split(' ');
                const cmd = parts[0];
                const args = parts.slice(1).concat(['--version']);
                
                const proc = spawn(cmd, args, { 
                    timeout: 3000,
                    shell: false
                });
                
                let output = '';
                proc.stdout?.on('data', (data: Buffer) => {
                    output += data.toString();
                });
                proc.stderr?.on('data', (data: Buffer) => {
                    output += data.toString();
                });
                
                proc.on('close', (code) => {
                    if (code !== 0) {
                        resolve(false);
                        return;
                    }
                    
                    // Parse version (e.g., "Python 3.13.0")
                    const match = output.match(/Python (\d+)\.(\d+)/);
                    if (match) {
                        const major = parseInt(match[1]);
                        const minor = parseInt(match[2]);
                        const suitable = major === 3 && minor >= 10;
                        if (!suitable) {
                            this.outputChannel.appendLine(`  Version ${major}.${minor} (requires >= 3.10)`);
                        }
                        resolve(suitable);
                    } else {
                        resolve(false);
                    }
                });
                
                proc.on('error', () => {
                    resolve(false);
                });
            } catch (error) {
                resolve(false);
            }
        });
    }

    /**
     * Poll until the server is ready, or timeout.
     */
    private async waitForReady(timeoutMs = 30000, intervalMs = 500): Promise<void> {
        const start = Date.now();

        while (Date.now() - start < timeoutMs) {
            if (this._startupError) {
                throw new Error(
                    `Server process error before becoming ready: ${this._startupError.message}`
                );
            }

            if (await this.healthCheck()) {
                this._isRunning = true;
                this.outputChannel.appendLine('Server is ready.');
                this._onReadyEmitter.fire();
                return;
            }

            // Check if process died. Use startup markers so we can still detect
            // this even if exit handlers already nulled `this.process`.
            if (this._startupExitCode !== null || this._startupExitSignal !== null) {
                if (this._startupExitCode !== null) {
                    throw new Error(
                        `Server process exited with code ${this._startupExitCode} before becoming ready.`
                    );
                }
                throw new Error(
                    `Server process exited with signal ${this._startupExitSignal} before becoming ready.`
                );
            }

            // Fallback check while process object still exists and has an exitCode.
            if (this.process?.exitCode !== null && this.process?.exitCode !== undefined) {
                throw new Error(
                    `Server process exited with code ${this.process.exitCode} before becoming ready.`
                );
            }

            await new Promise((r) => setTimeout(r, intervalMs));
        }

        throw new Error(`Server did not become ready within ${timeoutMs / 1000}s.`);
    }
}
