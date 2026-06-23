import { type WorkspaceViewState } from './foundation.js';
export declare function isWorkspaceRoot(candidateRoot: string): Promise<boolean>;
export declare function findWorkspaceRoot(startPath?: string): Promise<string | null>;
export declare function workspaceStateFileExistsSync(workspaceRoot: string): boolean;
export declare function readWorkspaceViewState(workspaceRoot: string): Promise<WorkspaceViewState>;
export declare function readWorkspaceViewStateSync(workspaceRoot: string): WorkspaceViewState | null;
export declare function readOptionalWorkspaceViewState(workspaceRoot: string): Promise<WorkspaceViewState | null>;
export declare function writeWorkspaceViewState(workspaceRoot: string, state: WorkspaceViewState): Promise<void>;
export declare function workspaceChangesDirExists(workspaceRoot: string): Promise<boolean>;
//# sourceMappingURL=state-io.d.ts.map