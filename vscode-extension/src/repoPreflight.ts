import * as fs from 'fs';
import * as path from 'path';

export const REPO_MARKER = 'lit-critic-server.py';

export interface RepoPathValidationResult {
    ok: boolean;
    reason_code: 'empty' | 'not_found' | 'not_directory' | 'missing_marker' | 'unknown_error' | '';
    message: string;
    path?: string;
}

export function validateRepoPath(rawPath: string | undefined): RepoPathValidationResult {
    const candidate = (rawPath || '').trim();
    if (!candidate) {
        return {
            ok: false,
            reason_code: 'empty',
            message: 'Repository path is empty.',
        };
    }

    try {
        const normalized = path.resolve(candidate);
        if (!fs.existsSync(normalized)) {
            return {
                ok: false,
                reason_code: 'not_found',
                message: `Repository path was not found: ${normalized}`,
                path: normalized,
            };
        }

        const stat = fs.statSync(normalized);
        if (!stat.isDirectory()) {
            return {
                ok: false,
                reason_code: 'not_directory',
                message: `Repository path is not a directory: ${normalized}`,
                path: normalized,
            };
        }

        const marker = path.join(normalized, REPO_MARKER);
        if (!fs.existsSync(marker)) {
            return {
                ok: false,
                reason_code: 'missing_marker',
                message: `Directory does not contain ${REPO_MARKER}: ${normalized}`,
                path: normalized,
            };
        }

        return {
            ok: true,
            reason_code: '',
            message: 'Repository path is valid.',
            path: normalized,
        };
    } catch (err) {
        return {
            ok: false,
            reason_code: 'unknown_error',
            message: `Unexpected error while validating repository path: ${String(err)}`,
            path: candidate,
        };
    }
}
