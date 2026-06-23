import { type ContextStoreGitBackendConfig, type ContextStorePathOptions, type ContextStoreRegistryState } from './foundation.js';
import { type ContextStoreDiagnostic } from './errors.js';
type PathKind = 'missing' | 'directory' | 'file' | 'other';
export interface ContextStoreInfo {
    id: string;
    root: string;
    metadataPath?: string;
}
export interface ContextStoreMutationResult {
    store: ContextStoreInfo;
    registryCommit: {
        path: string;
    };
    git: {
        isRepository: boolean;
        initialized: boolean;
    };
    createdArtifacts: string[];
}
export interface ContextStoreCleanupResult {
    store: ContextStoreInfo;
    registryCommit: {
        path: string;
        removed: boolean;
    };
    files: {
        deleted: boolean;
        deletedPath?: string;
        leftOnDisk?: string;
    };
    diagnostics: ContextStoreDiagnostic[];
}
export interface ContextStoreListResult {
    stores: ContextStoreInfo[];
}
export interface ContextStoreDoctorResult {
    stores: ContextStoreInspection[];
    diagnostics: ContextStoreDiagnostic[];
}
export interface ContextStoreInspection extends ContextStoreInfo {
    metadata: {
        present: boolean | null;
        valid: boolean | null;
        id?: string;
    };
    git: {
        isRepository: boolean | null;
    };
    diagnostics: ContextStoreDiagnostic[];
}
export interface SetupContextStoreInput {
    id?: string;
    path?: string;
    initGit?: boolean;
    allowInsideGitRepository?: boolean;
}
export interface RegisterExistingContextStoreInput {
    path?: string;
    id?: string;
}
export interface CleanupContextStoreInput extends ContextStorePathOptions {
    id: string;
}
export interface PreparedContextStoreCleanup extends ContextStoreInfo, ContextStorePathOptions {
    backend: ContextStoreGitBackendConfig;
}
export interface PreparedContextStoreSetup {
    id: string;
    root: string;
    rootKind: Extract<PathKind, 'missing' | 'directory'>;
    backend?: ContextStoreGitBackendConfig;
    registry: ContextStoreRegistryState | null;
}
export declare function prepareContextStoreSetup(input: Pick<SetupContextStoreInput, 'id' | 'path' | 'allowInsideGitRepository'>): Promise<PreparedContextStoreSetup>;
export declare function setupPreparedContextStore(prepared: PreparedContextStoreSetup, input?: Pick<SetupContextStoreInput, 'initGit'>): Promise<ContextStoreMutationResult>;
export declare function setupContextStore(input: SetupContextStoreInput): Promise<ContextStoreMutationResult>;
export declare function registerExistingContextStore(input: RegisterExistingContextStoreInput): Promise<ContextStoreMutationResult>;
export declare function prepareContextStoreCleanup(input: CleanupContextStoreInput): Promise<PreparedContextStoreCleanup>;
export declare function unregisterContextStore(input: CleanupContextStoreInput): Promise<ContextStoreCleanupResult>;
export declare function removeContextStore(target: PreparedContextStoreCleanup): Promise<ContextStoreCleanupResult>;
export declare function listContextStores(): Promise<ContextStoreListResult>;
export declare function doctorContextStores(id?: string): Promise<ContextStoreDoctorResult>;
export declare function normalizeContextStorePathForComparison(targetPath: string): string;
export {};
//# sourceMappingURL=operations.d.ts.map