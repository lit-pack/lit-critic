/**
 * Real tests for DiagnosticsProvider module.
 * 
 * Tests the actual DiagnosticsProvider class with mocked vscode API.
 */

import { strict as assert } from 'assert';
import { createFreshMockVscode, MockDiagnosticCollection, sampleFindings, sampleFinding } from './fixtures';

const proxyquire = require('proxyquire').noCallThru();

describe('DiagnosticsProvider (Real)', () => {
    let DiagnosticsProvider: any;
    let mockVscode: any;
    let diagnosticsProvider: any;
    let mockCollection: MockDiagnosticCollection;

    beforeEach(() => {
        mockVscode = createFreshMockVscode();
        
        // Capture the diagnostic collection
        mockCollection = new MockDiagnosticCollection();
        mockVscode.languages.createDiagnosticCollection = () => mockCollection;

        const module = proxyquire('../../vscode-extension/src/diagnosticsProvider', {
            'vscode': mockVscode,
        });
        DiagnosticsProvider = module.DiagnosticsProvider;
    });

    afterEach(() => {
        if (diagnosticsProvider) {
            diagnosticsProvider.dispose();
        }
    });

    describe('constructor', () => {
        it('should create diagnostic collection with correct name', () => {
            let collectionName = '';
            mockVscode.languages.createDiagnosticCollection = (name: string) => {
                collectionName = name;
                return mockCollection;
            };
            
            diagnosticsProvider = new DiagnosticsProvider();
            assert.equal(collectionName, 'litCritic');
        });
    });

    describe('setScenePath', () => {
        it('should store the scene path', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            const testPath = '/test/scene.txt';
            
            diagnosticsProvider.setScenePath(testPath);
            
            assert.equal(diagnosticsProvider.scenePath, testPath);
        });
    });

    describe('updateFromFindings', () => {
        it('should create diagnostics only for pending findings', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings(sampleFindings);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            // Should have 2 diagnostics (excluding the accepted one)
            assert.ok(diagnostics);
            assert.equal(diagnostics.length, 2);
        });

        it('should map severity correctly', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFindings[0], sampleFindings[1]]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            // sampleFindings[0] is major (Warning), sampleFindings[1] is critical (Error)
            assert.equal(diagnostics[0].severity, mockVscode.DiagnosticSeverity.Warning);
            assert.equal(diagnostics[1].severity, mockVscode.DiagnosticSeverity.Error);
        });

        it('should convert 1-based line numbers to 0-based', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            const finding = { ...sampleFinding, line_start: 42, line_end: 45 };
            diagnosticsProvider.updateFromFindings([finding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.equal(diagnostics[0].range.start.line, 41); // 42 - 1
            assert.equal(diagnostics[0].range.end.line, 44);   // 45 - 1
        });

        it('should handle findings without line numbers', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            const finding = { ...sampleFinding, line_start: null, line_end: null };
            diagnosticsProvider.updateFromFindings([finding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            // Should default to line 0
            assert.equal(diagnostics[0].range.start.line, 0);
            assert.equal(diagnostics[0].range.end.line, 0);
        });

        it('should include evidence in diagnostic message', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.match(diagnostics[0].message, /rhythm breaks/);
        });

        it('should include impact in diagnostic message', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.match(diagnostics[0].message, /Disrupts reading flow/);
        });

        it('should include options in diagnostic message', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.match(diagnostics[0].message, /Rewrite for smoother rhythm/);
        });

        it('should set source as lit-critic with lens', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.equal(diagnostics[0].source, 'lit-critic (prose)');
        });

        it('should set finding number as code', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.equal(diagnostics[0].code, 1);
        });

        it('should mark stale findings with Unnecessary tag', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            const staleFinding = { ...sampleFinding, stale: true };
            diagnosticsProvider.updateFromFindings([staleFinding]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            const diagnostics = mockCollection.get(uri);
            
            assert.ok(diagnostics);
            assert.ok(diagnostics[0].tags);
            assert.ok(diagnostics[0].tags.includes(mockVscode.DiagnosticTag.Unnecessary));
        });

        it('should do nothing when scenePath is null', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            // Don't set scene path
            
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            // Collection should be empty
            assert.equal(mockCollection._getDiagnostics().size, 0);
        });
    });

    describe('removeFinding', () => {
        it('should remove specific finding by number', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            
            // Add two findings
            diagnosticsProvider.updateFromFindings([sampleFindings[0], sampleFindings[1]]);
            
            const uri = mockVscode.Uri.file('/test/scene.txt');
            let diagnostics = mockCollection.get(uri);
            assert.ok(diagnostics);
            assert.equal(diagnostics.length, 2);
            
            // Remove first finding
            diagnosticsProvider.removeFinding(sampleFindings[0].number);
            
            diagnostics = mockCollection.get(uri);
            assert.ok(diagnostics);
            assert.equal(diagnostics.length, 1);
            assert.equal(diagnostics[0].code, sampleFindings[1].number);
        });
    });

    describe('clear', () => {
        it('should clear all diagnostics and reset scene path', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            diagnosticsProvider.clear();
            
            assert.equal(diagnosticsProvider.scenePath, null);
            assert.equal(mockCollection._getDiagnostics().size, 0);
        });
    });

    describe('dispose', () => {
        it('should dispose the diagnostic collection', () => {
            diagnosticsProvider = new DiagnosticsProvider();
            diagnosticsProvider.setScenePath('/test/scene.txt');
            diagnosticsProvider.updateFromFindings([sampleFinding]);
            
            diagnosticsProvider.dispose();
            
            // After dispose, collection should be cleared
            assert.equal(mockCollection._getDiagnostics().size, 0);
        });
    });
});
