/**
 * Real tests for ApiClient module.
 * 
 * Tests the actual ApiClient class with mocked http module.
 */

import { strict as assert } from 'assert';
import { 
    createFreshMockVscode, 
    MockHttpResponse, 
    MockHttpRequest,
    sampleAnalysisSummary,
    sampleServerConfig,
} from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('ApiClient (Real)', () => {
    let ApiClient: any;
    let mockHttp: any;
    let client: any;

    beforeEach(() => {
        // Default mock http module
        mockHttp = {
            request: (options: any, callback?: any) => {
                const req = new MockHttpRequest();
                return req;
            },
        };
    });

    afterEach(() => {
        client = null;
    });

    function createClient() {
        const module = proxyquire('../../vscode-extension/src/apiClient', {
            'http': mockHttp,
        });
        ApiClient = module.ApiClient;
        client = new ApiClient('http://localhost:8000');
        return client;
    }

    describe('constructor', () => {
        it('should construct with base URL', () => {
            client = createClient();
            assert.ok(client);
        });

        it('should format request options correctly', () => {
            let capturedOptions: any;
            
            mockHttp.request = (options: any, callback?: any) => {
                capturedOptions = options;
                const req = new MockHttpRequest(new MockHttpResponse(200, {}));
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            client.getConfig();
            
            assert.equal(capturedOptions.hostname, 'localhost');
            assert.equal(capturedOptions.port, '8000');
            assert.ok(capturedOptions.path);
        });
    });

    describe('GET endpoints', () => {
        it('should make GET request to /api/config', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                assert.equal(options.method, 'GET');
                assert.equal(options.path, '/api/config');
                
                const req = new MockHttpRequest(new MockHttpResponse(200, sampleServerConfig));
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            const result = await client.getConfig();
            
            assert.ok(result.available_models);
            assert.equal(result.default_model, 'sonnet');
        });
    });

    describe('POST endpoints', () => {
        it('should send POST with JSON body to /api/analyze', async () => {
            let capturedBody: any;
            
            mockHttp.request = (options: any, callback?: any) => {
                assert.equal(options.method, 'POST');
                assert.equal(options.path, '/api/analyze');
                assert.equal(options.headers['Content-Type'], 'application/json');
                
                const req = new MockHttpRequest(new MockHttpResponse(200, sampleAnalysisSummary));
                const originalWrite = req.write.bind(req);
                req.write = (data: any) => {
                    capturedBody = JSON.parse(data);
                    originalWrite(data);
                };
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            await client.analyze('/test/scene.txt', '/test/project');
            
            assert.equal(capturedBody.scene_path, '/test/scene.txt');
            assert.equal(capturedBody.project_path, '/test/project');
            assert.equal(capturedBody.model, undefined);
        });

    });


    describe('error handling', () => {
        it('should reject on HTTP 500 error', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                const req = new MockHttpRequest(new MockHttpResponse(500, { 
                    detail: 'Internal server error' 
                }));
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            
            await assert.rejects(
                () => client.getConfig(),
                /HTTP 500: Internal server error/
            );
        });

        it('should reject on HTTP 422 with formatted validation errors', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                const req = new MockHttpRequest(new MockHttpResponse(422, { 
                    detail: [
                        { loc: ['body', 'scene_path'], msg: 'field required' },
                        { loc: ['body', 'project_path'], msg: 'field required' },
                    ]
                }));
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            
            await assert.rejects(
                () => client.analyze('', ''),
                /Validation error:.*scene_path.*project_path/
            );
        });

        it('should reject on network error', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                const req = new MockHttpRequest(undefined, true); // shouldError = true
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            
            await assert.rejects(
                () => client.getConfig(),
                /Network error/
            );
        });

        it('should reject on timeout', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                const req = new MockHttpRequest(undefined, false, true); // shouldTimeout = true
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            
            await assert.rejects(
                () => client.getConfig(),
                /Request timed out/
            );
        });

        it('should reject on invalid JSON response', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                // Return a response with invalid JSON
                const response = new MockHttpResponse(200, '');
                // Override body to be invalid JSON
                (response as any).body = 'not json {{{';
                
                const req = new MockHttpRequest(response);
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            
            await assert.rejects(
                () => client.getConfig(),
                /Invalid JSON response/
            );
        });
    });

    describe('SSE streaming', () => {
        it('should parse SSE events from streamAnalysisProgress', (done) => {
            const events: any[] = [];
            
            mockHttp.request = (options: any, callback?: any) => {
                assert.equal(options.method, 'GET');
                assert.equal(options.path, '/api/analyze/progress');
                
                const req = new MockHttpRequest();
                
                setImmediate(() => {
                    const res = new MockHttpResponse(200, '');
                    if (callback) {
                        callback(res);
                    }
                    
                    setTimeout(() => {
                        res.emit('data', Buffer.from('data: {"type":"status","message":"Starting analysis"}\n\n'));
                        res.emit('data', Buffer.from('data: {"type":"lens_complete","lens":"prose"}\n\n'));
                        res.emit('data', Buffer.from('data: {"type":"done"}\n\n'));
                        res.emit('end');
                    }, 10);
                });
                
                return req;
            };
            
            client = createClient();
            
            client.streamAnalysisProgress(
                (event: any) => events.push(event),
                () => {
                    assert.equal(events.length, 3);
                    assert.equal(events[0].type, 'status');
                    assert.equal(events[1].type, 'lens_complete');
                    assert.equal(events[2].type, 'done');
                    done();
                },
                (err: Error) => done(err)
            );
        });
    });

    describe('Management API methods', () => {
        it('should call GET /api/learning with project_path', async () => {
            mockHttp.request = (options: any, callback?: any) => {
                assert.equal(options.method, 'GET');
                assert.ok(options.path.includes('/api/learning'));
                assert.ok(options.path.includes('project_path='));
                
                const req = new MockHttpRequest(new MockHttpResponse(200, {
                    project_name: 'Test',
                    review_count: 0,
                    preferences: [],
                    blind_spots: [],
                    resolutions: [],
                    ambiguity_intentional: [],
                    ambiguity_accidental: [],
                }));
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            const result = await client.getLearning('/test/project');
            
            assert.ok(result.project_name);
            assert.ok(Array.isArray(result.preferences));
        });

        it('should call POST /api/learning/export with body', async () => {
            let capturedBody: any;
            
            mockHttp.request = (options: any, callback?: any) => {
                assert.equal(options.method, 'POST');
                assert.equal(options.path, '/api/learning/export');
                
                const req = new MockHttpRequest(new MockHttpResponse(200, {
                    exported: true,
                    path: '/test/project/LEARNING.md',
                }));
                const originalWrite = req.write.bind(req);
                req.write = (data: any) => {
                    capturedBody = JSON.parse(data);
                    originalWrite(data);
                };
                if (callback) {
                    req.on('response', callback);
                }
                return req;
            };
            
            client = createClient();
            const result = await client.exportLearning('/test/project');
            
            assert.equal(capturedBody.project_path, '/test/project');
            assert.equal(result.exported, true);
            assert.ok(result.path.endsWith('LEARNING.md'));
        });
    });
});
