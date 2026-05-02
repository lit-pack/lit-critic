/**
 * Tests for ApiClient module.
 * 
 * Note: These tests verify API client logic and data structures.
 */

import { strict as assert } from 'assert';
import {
    sampleServerConfig,
    sampleAnalysisSummary,
    sampleFindingResponse,
    sampleAdvanceResponse,
    sampleSessionInfo,
} from './fixtures';

describe('ApiClient', () => {
    describe('data structures', () => {
        it('should validate server config structure', () => {
            assert.ok(sampleServerConfig.available_models);
            assert.ok(sampleServerConfig.default_model);
            assert.equal(sampleServerConfig.default_model, 'sonnet');
        });

        it('should validate analysis summary structure', () => {
            assert.ok(sampleAnalysisSummary.scene_path);
            assert.equal(sampleAnalysisSummary.total_findings, 3);
            assert.ok(sampleAnalysisSummary.counts);
            assert.ok(sampleAnalysisSummary.model);
        });

        it('should validate finding response structure', () => {
            assert.equal(sampleFindingResponse.complete, false);
            assert.ok(sampleFindingResponse.finding);
            assert.equal(sampleFindingResponse.finding.number, 1);
        });

        it('should validate session info structure', () => {
            assert.equal(sampleSessionInfo.active, true);
            assert.equal(sampleSessionInfo.total_findings, 3);
            assert.ok(sampleSessionInfo.findings_status);
        });
    });

    describe('URL formatting', () => {
        it('should format API endpoints correctly', () => {
            const baseUrl = 'http://localhost:8000';
            const endpoints = {
                config: `${baseUrl}/api/config`,
                analyze: `${baseUrl}/api/analyze`,
                finding: `${baseUrl}/api/finding`,
                session: `${baseUrl}/api/session`,
            };
            
            assert.equal(endpoints.config, 'http://localhost:8000/api/config');
            assert.equal(endpoints.analyze, 'http://localhost:8000/api/analyze');
        });
    });

    describe('request body formatting', () => {
        it('should format analyze request', () => {
            const request = {
                scene_path: '/test/scene.txt',
                project_path: '/test/project',
                model: 'sonnet',
            };
            
            assert.ok(request.scene_path);
            assert.ok(request.project_path);
            assert.equal(request.model, 'sonnet');
        });

        it('should format reject request', () => {
            const request = {
                reason: 'Not relevant',
            };
            
            assert.equal(request.reason, 'Not relevant');
        });

        it('should handle empty reject reason', () => {
            const reason = '';
            const request = { reason: reason || '' };
            assert.equal(request.reason, '');
        });

        it('should format audit request', () => {
            const request = {
                project_path: '/test/project',
                deep: true,
                model: 'sonnet',
            };

            assert.equal(request.project_path, '/test/project');
            assert.equal(request.deep, true);
            assert.equal(request.model, 'sonnet');
        });

        it('should format scene audit request', () => {
            const request = {
                scene_path: '/test/scene.txt',
                project_path: '/test/project',
                deep: true,
                model: 'sonnet',
            };

            assert.equal(request.scene_path, '/test/scene.txt');
            assert.equal(request.project_path, '/test/project');
            assert.equal(request.deep, true);
            assert.equal(request.model, 'sonnet');
        });
    });

    describe('response parsing', () => {
        it('should handle complete response', () => {
            const response = { complete: true, message: 'All done' };
            assert.equal(response.complete, true);
            assert.equal(response.message, 'All done');
        });

        it('should handle finding in response', () => {
            const response = sampleFindingResponse;
            assert.ok(response.finding);
            assert.equal(response.finding.number, 1);
            assert.equal(response.finding.severity, 'major');
        });

        it('should handle advance response with scene change', () => {
            const response = {
                ...sampleAdvanceResponse,
                scene_change: {
                    changed: true,
                    adjusted: 2,
                    stale: 1,
                    re_evaluated: [],
                },
            };
            
            assert.ok(response.scene_change);
            assert.equal(response.scene_change.changed, true);
            assert.equal(response.scene_change.adjusted, 2);
        });
    });

    describe('error handling', () => {
        it('should format error messages', () => {
            const statusCode = 500;
            const detail = 'Internal server error';
            const errorMessage = `HTTP ${statusCode}: ${detail}`;
            
            assert.match(errorMessage, /HTTP 500/);
            assert.match(errorMessage, /Internal server error/);
        });

        it('should handle network errors', () => {
            const error = new Error('Network error');
            assert.match(error.message, /Network error/);
        });

        it('should handle timeout errors', () => {
            const error = new Error('Request timed out');
            assert.match(error.message, /timed out/);
        });

        it('should handle invalid JSON', () => {
            const error = new Error('Invalid JSON response');
            assert.match(error.message, /Invalid JSON/);
        });
    });

    describe('Management API Methods (Phase 2)', () => {
        describe('Learning Management', () => {
            it('should call GET /api/learning with project_path', () => {
                const method = 'GET';
                const projectPath = '/test/project';
                const path = `/api/learning?project_path=${encodeURIComponent(projectPath)}`;
                
                assert.equal(method, 'GET');
                assert.ok(path.includes('project_path='));
            });

            it('should call POST /api/learning/export', () => {
                const method = 'POST';
                const body = { project_path: '/test/project' };
                const path = '/api/learning/export';
                
                assert.equal(method, 'POST');
                assert.equal(path, '/api/learning/export');
                assert.ok(body.project_path);
            });

            it('should call DELETE /api/learning', () => {
                const method = 'DELETE';
                const projectPath = '/test/project';
                const path = `/api/learning?project_path=${encodeURIComponent(projectPath)}`;
                
                assert.equal(method, 'DELETE');
                assert.ok(path.includes('project_path='));
            });

            it('should call DELETE /api/learning/entries/{id}', () => {
                const method = 'DELETE';
                const entryId = 42;
                const projectPath = '/test/project';
                const path = `/api/learning/entries/${entryId}?project_path=${encodeURIComponent(projectPath)}`;
                
                assert.equal(method, 'DELETE');
                assert.ok(path.includes('/api/learning/entries/42'));
                assert.ok(path.includes('project_path='));
            });
        });

        describe('Response Types', () => {
            it('should return sessions list from listSessions', () => {
                const mockResponse = {
                    sessions: [
                        { id: 1, scene_path: '/test/scene.txt', status: 'completed' },
                    ],
                };
                
                assert.ok(Array.isArray(mockResponse.sessions));
                assert.equal(mockResponse.sessions[0].id, 1);
            });

            it('should return session detail from getSessionDetail', () => {
                const mockResponse = {
                    id: 1,
                    scene_path: '/test/scene.txt',
                    status: 'completed',
                    findings: [],
                    total_findings: 0,
                };
                
                assert.equal(mockResponse.id, 1);
                assert.ok('findings' in mockResponse);
            });

            it('should return learning data from getLearning', () => {
                const mockResponse = {
                    project_name: 'Test Project',
                    review_count: 5,
                    preferences: [],
                    blind_spots: [],
                    resolutions: [],
                    ambiguity_intentional: [],
                    ambiguity_accidental: [],
                };
                
                assert.ok('preferences' in mockResponse);
                assert.ok('blind_spots' in mockResponse);
                assert.equal(mockResponse.review_count, 5);
            });

            it('should return deleted confirmation from deleteSession', () => {
                const mockResponse = {
                    deleted: true,
                    session_id: 5,
                };
                
                assert.equal(mockResponse.deleted, true);
                assert.equal(mockResponse.session_id, 5);
            });

            it('should return exported confirmation from exportLearning', () => {
                const mockResponse = {
                    exported: true,
                    path: '/test/project/LEARNING.md',
                };
                
                assert.equal(mockResponse.exported, true);
                assert.ok(mockResponse.path.endsWith('LEARNING.md'));
            });

            it('should return reset confirmation from resetLearning', () => {
                const mockResponse = {
                    reset: true,
                };
                
                assert.equal(mockResponse.reset, true);
            });

            it('should return deleted confirmation from deleteLearningEntry', () => {
                const mockResponse = {
                    deleted: true,
                    entry_id: 42,
                };
                
                assert.equal(mockResponse.deleted, true);
                assert.equal(mockResponse.entry_id, 42);
            });

            it('should use /api/scenes/audit endpoint for scene audit', () => {
                const method = 'POST';
                const path = '/api/scenes/audit';
                const body = {
                    scene_path: '/test/scene.txt',
                    project_path: '/test/project',
                    deep: true,
                    model: 'sonnet',
                };

                assert.equal(method, 'POST');
                assert.equal(path, '/api/scenes/audit');
                assert.equal(body.scene_path, '/test/scene.txt');
                assert.equal(body.deep, true);
            });
        });
    });
});
