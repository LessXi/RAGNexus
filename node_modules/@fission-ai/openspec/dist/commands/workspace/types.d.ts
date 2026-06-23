import type { ContextStoreSelector } from '../../core/context-store/index.js';
export type StatusSeverity = 'error' | 'warning';
export interface WorkspaceStatus {
    severity: StatusSeverity;
    code: string;
    message: string;
    target?: string;
    fix?: string;
    details?: Record<string, unknown>;
}
export interface WorkspaceLinkOutput {
    name: string;
    path: string | null;
    repo_specs_path?: string | null;
    status: WorkspaceStatus[];
}
export interface WorkspaceContextOutput {
    store: string;
    initiative: string;
    store_selector: ContextStoreSelector;
}
export interface WorkspaceOutput {
    name: string;
    root: string;
    planning_path: string;
    state_path?: string;
    context?: WorkspaceContextOutput | null;
    links: WorkspaceLinkOutput[];
    status: WorkspaceStatus[];
}
export interface WorkspaceListOutput {
    name: string;
    root: string;
    context?: WorkspaceContextOutput | null;
    links: WorkspaceLinkOutput[];
    status: WorkspaceStatus[];
}
export interface WorkspaceSetupOptions {
    name?: string;
    link?: string[];
    opener?: string;
    tools?: string;
    json?: boolean;
    noInteractive?: boolean;
    interactive?: boolean;
}
export interface WorkspaceSelectionOptions {
    workspace?: string;
    json?: boolean;
    noInteractive?: boolean;
    interactive?: boolean;
}
export type WorkspaceLinkOptions = WorkspaceSelectionOptions;
export interface WorkspaceUpdateOptions extends WorkspaceSelectionOptions {
    tools?: string;
    force?: boolean;
}
export interface WorkspaceOpenOptions extends WorkspaceSelectionOptions {
    agent?: string;
    editor?: boolean;
    prepareOnly?: boolean;
    change?: string;
    initiative?: string;
    store?: string;
    storePath?: string;
}
export interface WorkspaceListOptions {
    json?: boolean;
}
export interface SelectedWorkspace {
    name: string;
    root: string;
    status: WorkspaceStatus[];
    unregisteredCurrentWorkspace: boolean;
}
export interface WorkspaceLinkMutationPayload {
    workspace: WorkspaceOutput;
    link: {
        name: string;
        path: string;
        status: WorkspaceStatus[];
    };
    status: WorkspaceStatus[];
}
export declare class WorkspaceCliError extends Error {
    readonly status: WorkspaceStatus;
    constructor(message: string, code: string, options?: {
        target?: string;
        fix?: string;
        details?: Record<string, unknown>;
    });
}
export declare function makeStatus(severity: StatusSeverity, code: string, message: string, options?: {
    target?: string;
    fix?: string;
    details?: Record<string, unknown>;
}): WorkspaceStatus;
export declare function asErrorMessage(error: unknown): string;
export declare function asStatus(error: unknown): WorkspaceStatus;
export declare function appendStatus<T extends {
    status: WorkspaceStatus[];
}>(payload: T, status: WorkspaceStatus): T;
//# sourceMappingURL=types.d.ts.map