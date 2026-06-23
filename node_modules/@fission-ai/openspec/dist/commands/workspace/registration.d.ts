import { Command } from 'commander';
import { WorkspaceLinkOptions, WorkspaceListOptions, WorkspaceOpenOptions, WorkspaceSetupOptions, WorkspaceUpdateOptions } from './types.js';
export interface WorkspaceCommandActions {
    setup(options: WorkspaceSetupOptions): Promise<void>;
    list(options: WorkspaceListOptions): Promise<void>;
    link(nameOrPath: string | undefined, linkPath: string | undefined, options: WorkspaceLinkOptions): Promise<void>;
    relink(linkNameInput: string | undefined, linkPath: string | undefined, options: WorkspaceLinkOptions): Promise<void>;
    doctor(options: WorkspaceLinkOptions): Promise<void>;
    update(positionalName: string | undefined, options: WorkspaceUpdateOptions): Promise<void>;
    open(positionalName: string | undefined, options: WorkspaceOpenOptions): Promise<void>;
}
export declare function registerWorkspaceCommandWith(program: Command, workspaceCommand: WorkspaceCommandActions): void;
//# sourceMappingURL=registration.d.ts.map