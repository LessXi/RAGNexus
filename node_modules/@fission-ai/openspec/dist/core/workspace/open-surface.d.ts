import { WorkspaceViewState } from './foundation.js';
export declare const WORKSPACE_GUIDANCE_START_MARKER = "<!-- OPENSPEC:WORKSPACE-GUIDANCE:START -->";
export declare const WORKSPACE_GUIDANCE_END_MARKER = "<!-- OPENSPEC:WORKSPACE-GUIDANCE:END -->";
export declare const WORKSPACE_OPEN_ROOT_FOLDER_LABEL = "OpenSpec workspace";
export declare const WORKSPACE_OPEN_INITIATIVE_FOLDER_LABEL = "Initiative context";
export declare const WORKSPACE_GUIDANCE_BODY = "# OpenSpec Workspace Guidance\n\nThis directory is an OpenSpec workspace: a local working view over context stores, initiatives, repos, and folders.\n\n- Use this workspace to open the local view of coordinated work.\n- Use initiatives for durable cross-team or cross-repo intent, decisions, requirements, and coordination context.\n- Use repo-local OpenSpec changes for implementation plans owned by a repo or team.\n- Use linked repos and folders to inspect context, understand ownership, and make edits in the place that owns the work.\n- Keep workspace-local files focused on local paths, opener state, agent setup, and other machine-specific view state.\n- Use OpenSpec workspace commands instead of hand-editing `.openspec-workspace/view.yaml`.\n- If this workspace contains legacy or beta workspace-level planning files, treat them as compatibility context unless the user explicitly asks to use that beta flow.";
export interface WorkspaceOpenResolvedContext {
    contextStore: {
        id: string;
        root: string;
    };
    initiative: {
        id: string;
        title: string;
        root: string;
        metadataPath: string;
        storePath: string;
    };
}
export interface WorkspaceOpenLink {
    name: string;
    path: string;
}
export interface WorkspaceSkippedOpenLink {
    name: string;
    path: string | null;
    reason: 'missing-local-path' | 'path-missing';
}
export interface WorkspaceOpenSurfaceLinks {
    links: WorkspaceOpenLink[];
    skipped: WorkspaceSkippedOpenLink[];
}
export interface WorkspaceOpenSurfaceGeneration {
    agentsPath: string;
    codeWorkspacePath: string;
}
export declare function buildWorkspaceGuidanceBlock(viewState?: WorkspaceViewState, resolvedContext?: WorkspaceOpenResolvedContext | null): string;
export declare function applyWorkspaceGuidanceBlock(existingContent: string, viewState?: WorkspaceViewState, resolvedContext?: WorkspaceOpenResolvedContext | null): string;
export declare function buildWorkspaceCodeWorkspaceContent(links: WorkspaceOpenLink[], resolvedContext?: WorkspaceOpenResolvedContext | null): string;
export declare function writeWorkspaceCodeWorkspaceFile(codeWorkspacePath: string, links: WorkspaceOpenLink[], resolvedContext?: WorkspaceOpenResolvedContext | null): Promise<void>;
export declare function resolveWorkspaceOpenLinks(viewState: WorkspaceViewState): Promise<WorkspaceOpenSurfaceLinks>;
export declare function syncWorkspaceOpenSurface(workspaceRoot: string, viewState: WorkspaceViewState, resolvedContext?: WorkspaceOpenResolvedContext | null): Promise<WorkspaceOpenSurfaceLinks & {
    generated: WorkspaceOpenSurfaceGeneration;
}>;
//# sourceMappingURL=open-surface.d.ts.map