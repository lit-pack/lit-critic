/**
 * Real tests for ServerManager module.
 * 
 * Tests the actual ServerManager class with mocked dependencies.
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode, MockChildProcess, createSmartSpawn, createStagedHealthCheck } from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('ServerManager (Real)', () => {
    let ServerManager: any;
    let mockVscode: any;
    let mockChildProcess: MockChildProcess;
    let mockSpawn: any;
    let mockHttp: any;
    let mockPath: any;
    let manager: any;

    beforeEach(() => {
        mockVscode = createFreshMockVscode();
        mockChildProcess = new MockChildProcess();
        
        // Use real path module
        mockPath = require('path');
    });

    afterEach(() => {
        if (manager) {
            manager.dispose();
            manager = null;
        }
    });

    function createManager(
        repoRoot = '/test/repo',
        options?: { readyTimeoutMs?: number; readyIntervalMs?: number },
    ) {
        const module = proxyquire('../../vscode-extension/src/serverManager', {
            'vscode': mockVscode,
            'child_process': { spawn: mockSpawn },
            'http': mockHttp,
            'path': mockPath,
        });
        ServerManager = module.ServerManager;
        return new ServerManager(repoRoot, options);
    }

    describe('constructor', () => {
        it('should construct with repo root', () => {
            // For constructor tests, use simple mock that succeeds immediately
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(0); // succeed immediately
            
            manager = createManager('/test/repo');
            assert.ok(manager);
        });

        it('should expose baseUrl, port, and isRunning properties', () => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(0);
            
            manager = createManager('/test/repo');
            
            assert.equal(manager.baseUrl, 'http://127.0.0.1:8000');
            assert.equal(manager.port, 8000);
            assert.equal(manager.isRunning, false);
        });
    });

    describe('start lifecycle', () => {
        it('should spawn Python process with correct arguments', async () => {
            let spawnedCommand: string = '';
            let spawnedArgs: string[] = [];
            
            // Use smart spawn but intercept the server spawn call
            mockSpawn = (cmd: string, args: string[], options?: any) => {
                // Handle Python detection calls
                if (cmd === 'py' && args.includes('-0')) {
                    const proc = new MockChildProcess();
                    setImmediate(() => {
                        proc.stdout.emit('data', Buffer.from('-3.13-64\n'));
                        proc.emit('close', 0);
                    });
                    return proc;
                }
                if (args.some((a: string) => a === '--version')) {
                    const proc = new MockChildProcess();
                    setImmediate(() => {
                        proc.stdout.emit('data', Buffer.from('Python 3.13.0\n'));
                        proc.emit('close', 0);
                    });
                    return proc;
                }
                
                // Server spawn - capture arguments
                spawnedCommand = cmd;
                spawnedArgs = args;
                return mockChildProcess;
            };
            
            // Initial health check fails, waitForReady succeeds
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            await manager.start();
            
            assert.ok(spawnedCommand.includes('python') || spawnedCommand === 'py');
            assert.ok(spawnedArgs.some((arg: string) => arg.includes('lit-critic-server.py')));
            assert.ok(spawnedArgs.includes('--port'));
            assert.ok(spawnedArgs.includes('8000'));
        });

        it('should poll health check until 200 response', async () => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            // Fail first 2 checks, succeed on 3rd
            mockHttp = createStagedHealthCheck(2);
            
            manager = createManager('/test/repo');
            await manager.start();
            
            assert.ok(mockHttp._getCallCount() >= 3, `Expected at least 3 health checks, got ${mockHttp._getCallCount()}`);
            assert.equal(manager.isRunning, true);
        });

        it('should set isRunning to true after health check passes', async () => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            assert.equal(manager.isRunning, false);
            
            await manager.start();
            
            assert.equal(manager.isRunning, true);
        });

        it('should reuse existing server if already running', async () => {
            let spawnCalled = false;
            mockSpawn = (cmd: string, args: string[], options?: any) => {
                spawnCalled = true;
                return mockChildProcess;
            };
            
            // Initial health check succeeds immediately (server already running)
            mockHttp = createStagedHealthCheck(0);
            
            manager = createManager('/test/repo');
            await manager.start();
            
            assert.equal(spawnCalled, false, 'Should not spawn if server already running');
            assert.equal(manager.isRunning, true);
        });
    });

    describe('stop & dispose', () => {
        it('should kill process on stop', async () => {
            let killCalled = false;
            
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            await manager.start();
            
            mockChildProcess.kill = (signal?: string) => {
                killCalled = true;
                mockChildProcess.exitCode = 0;
                mockChildProcess.emit('exit', 0, signal);
            };
            
            manager.stop();
            
            assert.ok(killCalled);
            assert.equal(manager.isRunning, false);
        });

        it('should dispose resources on dispose', async () => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            await manager.start();
            
            let killCalled = false;
            mockChildProcess.kill = () => {
                killCalled = true;
                mockChildProcess.exitCode = 0;
            };
            
            manager.dispose();
            
            assert.ok(killCalled);
            assert.equal(manager.isRunning, false);
        });

        it('should fire onStopped event when process exits', (done) => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            
            manager.onStopped(() => {
                manager = null; // Prevent afterEach from disposing and calling done() again
                done();
            });
            
            manager.start().then(() => {
                // Simulate process exit
                mockChildProcess.exitCode = 0;
                mockChildProcess.emit('exit', 0, null);
            });
        });
    });

    describe('error handling', () => {
        it('should reject when process exits before becoming ready', async () => {
            // Create a process that immediately exits on spawn
            const dyingProcess = new MockChildProcess();
            
            mockSpawn = (cmd: string, args: string[], options?: any) => {
                // Handle Python detection calls normally
                if (cmd === 'py' && args.includes('-0')) {
                    const proc = new MockChildProcess();
                    setImmediate(() => {
                        proc.stdout.emit('data', Buffer.from('-3.13-64\n'));
                        proc.emit('close', 0);
                    });
                    return proc;
                }
                if (args.some((a: string) => a === '--version')) {
                    const proc = new MockChildProcess();
                    setImmediate(() => {
                        proc.stdout.emit('data', Buffer.from('Python 3.13.0\n'));
                        proc.emit('close', 0);
                    });
                    return proc;
                }
                
                // Server spawn - return process that will die immediately
                setImmediate(() => {
                    dyingProcess.exitCode = 1;
                    dyingProcess.emit('exit', 1, null);
                });
                return dyingProcess;
            };
            
            // Initial check fails
            mockHttp = {
                get: (url: string, options: any, callback: any) => {
                    if (typeof options === 'function') { callback = options; }
                    const res = { statusCode: 500 };
                    setTimeout(() => callback(res), 5);
                    return { on: () => {}, destroy: () => {} };
                },
                request: () => ({ on: () => {}, destroy: () => {} }),
            };
            
            manager = createManager('/test/repo');
            
            try {
                await manager.start();
                assert.fail('Should have rejected');
            } catch (err: any) {
                assert.match(err.message, /Server process exited with code 1 before becoming ready/);
            }
            
            manager = null; // Prevent afterEach cleanup
        }).timeout(3000);

        it('should reject on health check timeout', async () => {
            // Create a fresh process that won't have exitCode set
            const freshProcess = new MockChildProcess();
            freshProcess.kill = () => {}; // No-op - keep exitCode as null
            
            mockSpawn = createSmartSpawn(freshProcess);
            // Health check always fails
            mockHttp = {
                get: (url: string, options: any, callback: any) => {
                    if (typeof options === 'function') { callback = options; }
                    const res = { statusCode: 500 };
                    setTimeout(() => callback(res), 5);
                    return { on: () => {}, destroy: () => {} };
                },
                request: () => ({ on: () => {}, destroy: () => {} }),
            };
            
            // Use a short timeout so this test completes in ~500ms instead of ~30s.
            manager = createManager('/test/repo', { readyTimeoutMs: 500, readyIntervalMs: 50 });
            
            try {
                await manager.start();
                assert.fail('Should have rejected');
            } catch (err: any) {
                assert.match(err.message, /Server did not become ready within/);
            }
            
            manager = null; // Prevent afterEach cleanup
        }).timeout(3000);

        it('should fire onStopped on process error', (done) => {
            mockSpawn = createSmartSpawn(mockChildProcess);
            mockHttp = createStagedHealthCheck(1);
            
            manager = createManager('/test/repo');
            
            manager.onStopped(() => {
                assert.equal(manager.isRunning, false);
                manager = null; // Prevent afterEach from disposing and calling done() again
                done();
            });
            
            manager.start().then(() => {
                // Simulate process error
                mockChildProcess.emit('error', new Error('Process error'));
            });
        });
    });
});
