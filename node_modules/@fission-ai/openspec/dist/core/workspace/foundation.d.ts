import { type ContextStoreBinding, type ContextStoreSelector } from '../context-store/index.js';
export declare const WORKSPACE_METADATA_DIR_NAME = ".openspec-workspace";
export declare const WORKSPACE_VIEW_STATE_FILE_NAME = "view.yaml";
export declare const WORKSPACE_CHANGES_DIR_NAME = "changes";
export declare const WORKSPACE_CODE_WORKSPACE_EXTENSION = ".code-workspace";
export declare const WORKSPACE_SUPPORTED_OPENER_VALUES: readonly ["codex-cli", "claude", "github-copilot", "editor"];
export declare const WORKSPACE_AGENT_OPENER_IDS: readonly ["codex-cli", "claude", "github-copilot"];
export declare const WORKSPACE_EDITOR_OPENER_IDS: readonly ["vscode"];
export type WorkspaceSupportedOpenerValue = typeof WORKSPACE_SUPPORTED_OPENER_VALUES[number];
export type WorkspaceAgentOpenerId = typeof WORKSPACE_AGENT_OPENER_IDS[number];
export type WorkspaceEditorOpenerId = typeof WORKSPACE_EDITOR_OPENER_IDS[number];
export type WorkspacePreferredOpener = {
    kind: 'agent';
    id: WorkspaceAgentOpenerId;
} | {
    kind: 'editor';
    id: WorkspaceEditorOpenerId;
};
export interface WorkspaceContextState {
    kind: 'initiative';
    store: ContextStoreBinding;
    initiative: {
        id: string;
    };
}
export interface WorkspaceViewState {
    version: 1;
    name: string;
    context: WorkspaceContextState | null;
    links: Record<string, string | null>;
    preferred_opener?: WorkspacePreferredOpener;
    tools?: string[];
    workspace_skills?: WorkspaceSkillState;
}
export interface WorkspaceSkillState {
    selected_agents: string[];
    last_applied_profile?: 'core' | 'custom';
    last_applied_delivery?: 'both' | 'skills' | 'commands';
    last_applied_workflow_ids?: string[];
    last_applied_at?: string;
}
export declare function getWorkspaceMetadataDir(workspaceRoot: string): string;
export declare function getWorkspaceViewStatePath(workspaceRoot: string): string;
export declare function getWorkspaceChangesDir(workspaceRoot: string): string;
export declare function getWorkspaceCodeWorkspaceFileName(workspaceName: string): string;
export declare function getWorkspaceCodeWorkspacePath(workspaceRoot: string, workspaceName: string): string;
/**
 * @deprecated Managed workspaces no longer create portable ignore rules.
 * This compatibility shim remains for callers that still ask which ignore
 * patterns OpenSpec owns for workspace-local generated files.
 */
export declare function getWorkspacePortableIgnorePatterns(_workspaceName?: string): string[];
export declare function validateWorkspaceName(name: string): string;
export declare function validateWorkspaceLinkName(name: string): string;
export declare function isValidWorkspaceName(name: string): boolean;
export declare function isValidWorkspaceLinkName(name: string): boolean;
export declare function isWorkspaceAgentOpenerId(value: string): value is WorkspaceAgentOpenerId;
export declare function isWorkspaceSupportedOpenerValue(value: string): value is WorkspaceSupportedOpenerValue;
export declare function parseWorkspacePreferredOpenerValue(value: string): WorkspacePreferredOpener;
export declare function validateWorkspacePreferredOpener(opener: WorkspacePreferredOpener): WorkspacePreferredOpener;
export declare function createWorkspaceInitiativeContext(store: ContextStoreBinding, initiativeId: string): WorkspaceContextState;
export declare function getWorkspaceContextStoreId(context: WorkspaceContextState): string;
export declare function getWorkspaceContextStoreSelector(context: WorkspaceContextState): ContextStoreSelector;
export declare function getWorkspaceContextInitiativeId(context: WorkspaceContextState): string;
export declare function parseWorkspaceViewState(content: string): WorkspaceViewState;
export declare function serializeWorkspaceViewState(state: WorkspaceViewState): string;
//# sourceMappingURL=foundation.d.ts.map