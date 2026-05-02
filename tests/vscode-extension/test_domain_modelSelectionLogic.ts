import { strict as assert } from 'assert';

import {
    buildAnalysisStartStatusMessage,
    getConfiguredAnalysisModel,
} from '../../vscode-extension/src/domain/modelSelectionLogic';

function makeConfig(overrides: {
    inspect?: any;
    values?: Record<string, string>;
} = {}) {
    const values = overrides.values || {};
    return {
        inspect<T>(_section: string): {
            globalValue?: T;
            workspaceValue?: T;
            workspaceFolderValue?: T;
        } | undefined {
            return overrides.inspect;
        },
        get<T>(section: string, defaultValue: T): T {
            if (Object.prototype.hasOwnProperty.call(values, section)) {
                return values[section] as unknown as T;
            }

            return Object.prototype.hasOwnProperty.call(values, section)
                ? (values[section] as unknown as T)
                : defaultValue;
        },
    };
}

describe('domain/modelSelectionLogic', () => {
    it('uses sonnet as default analysis model', () => {
        const config = makeConfig({ values: {} });
        assert.equal(getConfiguredAnalysisModel(config), 'sonnet');
    });

    it('returns opus when configured', () => {
        const config = makeConfig({ values: { analysisModel: 'opus' } });
        assert.equal(getConfiguredAnalysisModel(config), 'opus');
    });

    it('returns haiku when configured', () => {
        const config = makeConfig({ values: { analysisModel: 'haiku' } });
        assert.equal(getConfiguredAnalysisModel(config), 'haiku');
    });

    it('falls back to sonnet for invalid analysis model values', () => {
        const config = makeConfig({ values: { analysisModel: 'turbo' } });
        assert.equal(getConfiguredAnalysisModel(config), 'sonnet');
    });

    it('builds opus status message', () => {
        const message = buildAnalysisStartStatusMessage('opus');
        assert.equal(message, 'Running analysis (Opus)...');
    });

    it('builds sonnet status message', () => {
        const message = buildAnalysisStartStatusMessage('sonnet');
        assert.equal(message, 'Running analysis (Sonnet)...');
    });

    it('builds haiku status message', () => {
        const message = buildAnalysisStartStatusMessage('haiku');
        assert.equal(message, 'Running analysis (Haiku)...');
    });

    it('builds sonnet status message by default', () => {
        const message = buildAnalysisStartStatusMessage();
        assert.equal(message, 'Running analysis (Sonnet)...');
    });
});
