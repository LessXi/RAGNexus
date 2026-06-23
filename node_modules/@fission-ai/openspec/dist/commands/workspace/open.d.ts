import { spawn as nodeSpawn } from 'node:child_process';
import { WorkspacePreferredOpener, WorkspaceViewState, WorkspaceOpenResolvedContext, WorkspaceOpenSurfaceGeneration, WorkspaceSkippedOpenLink } from '../../core/workspace/index.js';
import { SelectedWorkspace } from './types.js';
export declare const WORKSPACE_OPEN_MINIMAL_PROMPT = "Open this OpenSpec workspace.";
export interface WorkspaceOpenState {
    viewState: WorkspaceViewState;
    codeWorkspacePath: string;
}
export interface WorkspaceOpenLaunchCommand {
    executable: string;
    args: string[];
    cwd: string;
    openerLabel: string;
}
export type WorkspaceOpenedRoot = {
    kind: 'workspace' | 'initiative' | 'link';
    name?: string;
    path: string;
};
export interface WorkspaceOpenCommandBuildResult {
    command: WorkspaceOpenLaunchCommand;
    skipped: WorkspaceSkippedOpenLink[];
    generated: WorkspaceOpenSurfaceGeneration;
    openedRoots: WorkspaceOpenedRoot[];
}
export type WorkspaceOpenSpawn = typeof nodeSpawn;
export interface WorkspaceOpenLaunchOptions {
    spawn?: WorkspaceOpenSpawn;
    isExecutableAvailable?: (executable: string) => boolean;
    stdio?: 'inherit' | 'ignore';
}
export declare function readWorkspaceOpenState(selected: SelectedWorkspace): Promise<WorkspaceOpenState>;
export declare function buildWorkspaceOpenLaunchCommand(opener: WorkspacePreferredOpener, workspaceRoot: string, codeWorkspacePath: string, attachedPaths: string[]): WorkspaceOpenLaunchCommand;
export declare function assertWorkspaceOpenerAvailable(opener: WorkspacePreferredOpener, codeWorkspacePath: string, isExecutableAvailable?: (executable: string) => boolean): void;
export declare function buildWorkspaceOpenCommandForState(opener: WorkspacePreferredOpener, workspaceRoot: string, state: WorkspaceOpenState, resolvedContext?: WorkspaceOpenResolvedContext | null): Promise<WorkspaceOpenCommandBuildResult>;
export declare function launchWorkspaceOpenCommand(command: WorkspaceOpenLaunchCommand, options?: WorkspaceOpenLaunchOptions): Promise<void>;
//# sourceMappingURL=open.d.ts.map