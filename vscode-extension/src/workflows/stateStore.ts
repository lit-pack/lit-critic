import { Finding } from '../types';

export interface RuntimeStateStore {
    allFindings: Finding[];
    currentFindingIndex: number;
    totalFindings: number;
    indexChangeDismissed: boolean;
}

export function createRuntimeStateStore(): RuntimeStateStore {
    return {
        allFindings: [],
        currentFindingIndex: 0,
        totalFindings: 0,
        indexChangeDismissed: false,
    };
}
