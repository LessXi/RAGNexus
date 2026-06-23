import { type WorkspaceContextState, type WorkspacePreferredOpener, type WorkspaceSkillState, type WorkspaceViewState } from './foundation.js';
export declare const WORKSPACE_LEGACY_SHARED_STATE_FILE_NAME = "workspace.yaml";
export declare const WORKSPACE_LEGACY_LOCAL_STATE_FILE_NAME = "local.yaml";
export declare const WORKSPACE_LEGACY_LOCAL_STATE_IGNORE_PATTERN = ".openspec-workspace/local.yaml";
export type WorkspaceLinkState = Record<string, unknown>;
export interface WorkspaceSharedState {
    version: 1;
    name: string;
    context: WorkspaceContextState | null;
    links: Record<string, WorkspaceLinkState>;
}
export interface WorkspaceLocalState {
    version: 1;
    paths: Record<string, string>;
    preferred_opener?: WorkspacePreferredOpener;
    tools?: string[];
    workspace_skills?: WorkspaceSkillState;
}
export declare function getWorkspaceLegacySharedStatePath(workspaceRoot: string): string;
export declare function getWorkspaceLegacyLocalStatePath(workspaceRoot: string): string;
export declare function workspaceViewToSharedState(state: WorkspaceViewState): WorkspaceSharedState;
export declare function workspaceViewToLocalState(state: WorkspaceViewState): WorkspaceLocalState;
export declare function workspaceStatePartsToViewState(sharedState: WorkspaceSharedState, localState: WorkspaceLocalState | null): WorkspaceViewState;
export declare function parseWorkspaceSharedState(content: string): WorkspaceSharedState;
export declare function parseWorkspaceLocalState(content: string): WorkspaceLocalState;
export declare function serializeWorkspaceSharedState(state: WorkspaceSharedState): string;
export declare function serializeWorkspaceLocalState(state: WorkspaceLocalState): string;
//# sourceMappingURL=legacy-state.d.ts.map