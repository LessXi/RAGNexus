export declare const MANAGED_WORKSPACES_DIR_NAME = "workspaces";
export declare const WORKSPACE_REGISTRY_FILE_NAME = "registry.yaml";
export interface WorkspaceRegistryState {
    version: 1;
    workspaces: Record<string, string>;
}
export interface WorkspaceRegistryEntry {
    name: string;
    workspaceRoot: string;
}
export interface WorkspacePathOptions {
    globalDataDir?: string;
}
export declare function getManagedWorkspacesDir(options?: WorkspacePathOptions): string;
export declare function getManagedWorkspaceRoot(workspaceName: string, options?: WorkspacePathOptions): string;
export declare function getWorkspaceRegistryPath(options?: WorkspacePathOptions): string;
export declare function parseWorkspaceRegistryState(content: string): WorkspaceRegistryState;
export declare function serializeWorkspaceRegistryState(state: WorkspaceRegistryState): string;
export declare function listWorkspaceRegistryEntries(registry: WorkspaceRegistryState): WorkspaceRegistryEntry[];
export declare function listKnownWorkspaceEntries(options?: WorkspacePathOptions): Promise<WorkspaceRegistryEntry[]>;
export declare function listManagedWorkspaceEntries(options?: WorkspacePathOptions): Promise<WorkspaceRegistryEntry[]>;
export declare function readWorkspaceRegistryState(options?: WorkspacePathOptions): Promise<WorkspaceRegistryState | null>;
export declare function writeWorkspaceRegistryState(state: WorkspaceRegistryState, options?: WorkspacePathOptions): Promise<void>;
//# sourceMappingURL=registry.d.ts.map