import { type ContextStoreBackendConfig, type ContextStoreGitBackendConfig, type ContextStorePathOptions, type ContextStoreRegistryEntry, type ContextStoreRegistryState } from './foundation.js';
export interface RegisterContextStoreInput extends ContextStorePathOptions {
    id: string;
    localPath: string;
    remote?: string;
    branch?: string;
    cwd?: string;
}
export interface ResolveRegisteredContextStoreInput extends ContextStorePathOptions {
    id: string;
}
export interface GetRegisteredContextStoreInput extends ResolveRegisteredContextStoreInput {
    expectedBackend?: ContextStoreGitBackendConfig;
}
export interface UnregisterContextStoreInput extends ContextStorePathOptions {
    id: string;
    expectedBackend?: ContextStoreGitBackendConfig;
    beforeCommit?: (entry: RegisteredContextStoreEntry) => Promise<void>;
}
export type ListRegisteredContextStoresOptions = ContextStorePathOptions;
export interface RegisteredContextStoreEntry extends ContextStoreRegistryEntry {
    storeRoot: string;
}
export interface ResolvedContextStore {
    id: string;
    storeRoot: string;
    backend: ContextStoreGitBackendConfig;
}
export interface ContextStoreRegistrationCommit extends ResolvedContextStore {
    metadataCreated: boolean;
}
export interface CommitContextStoreRegistrationInput extends ContextStorePathOptions {
    id: string;
    backend: ContextStoreGitBackendConfig;
    writeMetadataIfMissing: boolean;
}
export declare function getStoreRootForBackend(backend: ContextStoreBackendConfig): string;
export declare function assertNoRegisteredStoreConflict(registry: ContextStoreRegistryState | null, id: string, backend: ContextStoreGitBackendConfig): void;
export declare function commitContextStoreRegistration(input: CommitContextStoreRegistrationInput): Promise<ContextStoreRegistrationCommit>;
export declare function registerContextStore(input: RegisterContextStoreInput): Promise<ResolvedContextStore>;
export declare function listRegisteredContextStores(options?: ListRegisteredContextStoresOptions): Promise<RegisteredContextStoreEntry[]>;
export declare function getRegisteredContextStore(input: GetRegisteredContextStoreInput): Promise<RegisteredContextStoreEntry>;
export declare function unregisterContextStoreRegistration(input: UnregisterContextStoreInput): Promise<RegisteredContextStoreEntry>;
export declare function resolveRegisteredContextStore(input: ResolveRegisteredContextStoreInput): Promise<ResolvedContextStore>;
//# sourceMappingURL=registry.d.ts.map