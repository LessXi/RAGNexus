export declare const CONTEXT_STORE_METADATA_DIR_NAME = ".openspec-store";
export declare const CONTEXT_STORE_METADATA_FILE_NAME = "store.yaml";
export declare const CONTEXT_STORES_DIR_NAME = "context-stores";
export declare const CONTEXT_STORE_REGISTRY_FILE_NAME = "registry.yaml";
export interface ContextStorePathOptions {
    globalDataDir?: string;
}
export interface ContextStoreGitBackendConfig {
    type: 'git';
    local_path: string;
    remote?: string;
    branch?: string;
}
export type ContextStoreBackendConfig = ContextStoreGitBackendConfig;
export interface ContextStoreRegistryEntryState {
    backend: ContextStoreBackendConfig;
}
export interface ContextStoreRegistryState {
    version: 1;
    stores: Record<string, ContextStoreRegistryEntryState>;
}
export interface ContextStoreRegistryEntry {
    id: string;
    backend: ContextStoreBackendConfig;
}
export interface ContextStoreMetadataState {
    version: 1;
    id: string;
}
export interface ResolveGitContextStoreBackendInput {
    localPath: string;
    remote?: string;
    branch?: string;
}
export declare function getContextStoresDir(options?: ContextStorePathOptions): string;
export declare function getContextStoreRegistryPath(options?: ContextStorePathOptions): string;
export declare function getDefaultContextStoreRoot(id: string, options?: ContextStorePathOptions): string;
export declare function getContextStoreMetadataDir(storeRoot: string): string;
export declare function getContextStoreMetadataPath(storeRoot: string): string;
export declare function validateContextStoreId(id: string): string;
export declare function isValidContextStoreId(id: string): boolean;
export declare function parseContextStoreRegistryState(content: string): ContextStoreRegistryState;
export declare function parseContextStoreMetadataState(content: string): ContextStoreMetadataState;
export declare function serializeContextStoreRegistryState(state: ContextStoreRegistryState): string;
export declare function serializeContextStoreMetadataState(state: ContextStoreMetadataState): string;
export declare function listContextStoreRegistryEntries(registry: ContextStoreRegistryState): ContextStoreRegistryEntry[];
export declare function isContextStoreRoot(candidateRoot: string): Promise<boolean>;
export declare function readContextStoreRegistryState(options?: ContextStorePathOptions): Promise<ContextStoreRegistryState | null>;
export declare function writeContextStoreRegistryState(state: ContextStoreRegistryState, options?: ContextStorePathOptions): Promise<void>;
export declare function updateContextStoreRegistryState(updater: (state: ContextStoreRegistryState | null) => ContextStoreRegistryState | Promise<ContextStoreRegistryState>, options?: ContextStorePathOptions): Promise<ContextStoreRegistryState>;
export declare function readContextStoreMetadataState(storeRoot: string): Promise<ContextStoreMetadataState>;
export declare function readOptionalContextStoreMetadataState(storeRoot: string): Promise<ContextStoreMetadataState | null>;
export declare function writeContextStoreMetadataState(storeRoot: string, state: ContextStoreMetadataState): Promise<void>;
export declare function resolveGitContextStoreBackendConfig(input: ResolveGitContextStoreBackendInput, cwd?: string): Promise<ContextStoreGitBackendConfig>;
//# sourceMappingURL=foundation.d.ts.map