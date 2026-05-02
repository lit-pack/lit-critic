/**
 * Tests for the refreshScenes wiring (Task 1/2 of scene-file-rename-support-plan).
 *
 * Verifies:
 * (a) ApiClient.refreshScenes() calls POST /api/scenes/refresh with the project path.
 * (b) A sceneExtensions config change is reflected in the config sync payload.
 *
 * Note: the extension-level wiring (onDidChangeConfiguration calling refreshScenes,
 * litCritic.refreshScenes command calling refreshScenes) is exercised by the
 * existing Extension (Real) suite in test_extension_real.ts.
 */

import { strict as assert } from 'assert';
import { EventEmitter } from 'events';

// ---------------------------------------------------------------------------
// Minimal HTTP mock helpers (same approach as test_apiClient_real.ts)
// ---------------------------------------------------------------------------

class MockHttpResponse extends EventEmitter {
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

class MockHttpRequest extends EventEmitter {
    private response: MockHttpResponse | null;
    capturedOptions: any = null;
    capturedBody: string = '';

    constructor(response: MockHttpResponse | null) {
        super();
        this.response = response;
    }
    write(data: any): void { this.capturedBody += String(data); }
    end(): void {
        setImmediate(() => {
            if (this.response) {
                this.emit('response', this.response);
                this.response.simulateResponse();
            }
        });
    }
    destroy(): void { this.removeAllListeners(); }
}

function makeHttpModule(responseBody: any, statusCode = 200) {
    let lastRequest: MockHttpRequest;
    const mod = {
        request: (options: any, callback?: any) => {
            const res = new MockHttpResponse(statusCode, responseBody);
            lastRequest = new MockHttpRequest(res);
            lastRequest.capturedOptions = options;
            if (callback) { lastRequest.on('response', callback); }
            return lastRequest;
        },
        _getLastRequest: () => lastRequest,
    };
    return mod;
}

const proxyquire = require('proxyquire').noCallThru();

function loadApiClient(httpMod: any) {
    const mod = proxyquire('../../vscode-extension/src/apiClient', {
        'http': httpMod,
    });
    return new mod.ApiClient('http://localhost:9876');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ApiClient — refreshScenes', () => {
    it('calls POST /api/scenes/refresh with project_path in body', async () => {
        const httpMod = makeHttpModule({ scene_total: 3, scene_updated: 2 });
        const client = loadApiClient(httpMod);

        const result = await client.refreshScenes('/my/project');

        const req = httpMod._getLastRequest();
        assert.equal(req.capturedOptions.method, 'POST');
        assert.ok(
            req.capturedOptions.path.includes('/api/scenes/refresh'),
            `Expected path to include /api/scenes/refresh, got: ${req.capturedOptions.path}`,
        );
        const body = JSON.parse(req.capturedBody);
        assert.equal(body.project_path, '/my/project');
        assert.equal(result.scene_total, 3);
        assert.equal(result.scene_updated, 2);
    });
});

describe('sceneDiscoveryConfig — syncSceneDiscoverySettingsToServer', () => {
    it('sends configured sceneFolder and sceneExtensions to POST /api/config', async () => {
        const updateConfigCalls: any[] = [];
        const mockApiClient = {
            updateConfig: async (payload: any) => {
                updateConfigCalls.push(payload);
                return { scene_folder: payload.scene_folder, scene_extensions: payload.scene_extensions, default_scene_folder: 'text', default_scene_extensions: ['txt'] };
            },
        };

        const mockVscode = {
            workspace: {
                getConfiguration: (_section?: string) => ({
                    get: (key: string, defaultValue?: any) => {
                        if (key === 'sceneFolder') { return 'inputs'; }
                        if (key === 'sceneExtensions') { return ['md', 'txt']; }
                        return defaultValue;
                    },
                    inspect: (_key: string) => ({ defaultValue: undefined, globalValue: undefined, workspaceValue: undefined, workspaceFolderValue: undefined }),
                }),
            },
        };

        const mod = proxyquire('../../vscode-extension/src/bootstrap/sceneDiscoveryConfig', {
            'vscode': mockVscode,
        });

        await mod.syncSceneDiscoverySettingsToServer(mockApiClient);

        assert.ok(updateConfigCalls.length > 0, 'Expected updateConfig to be called');
        const call = updateConfigCalls[0];
        assert.equal(call.scene_folder, 'inputs');
        assert.deepEqual(call.scene_extensions, ['md', 'txt']);
    });
});
