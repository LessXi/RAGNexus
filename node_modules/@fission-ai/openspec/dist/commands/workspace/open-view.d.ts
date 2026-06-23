import { InitiativeViewReference } from '../../core/collections/initiatives/index.js';
import { type ContextStoreBinding } from '../../core/context-store/index.js';
import { WorkspaceContextState, WorkspacePreferredOpener } from '../../core/workspace/index.js';
import { type WorkspaceOpenCommandBuildResult } from './open.js';
import { SelectedWorkspace, WorkspaceOpenOptions, WorkspaceStatus } from './types.js';
export interface PreparedWorkspaceOpen extends WorkspaceOpenCommandBuildResult {
    selected: SelectedWorkspace;
    opener: WorkspacePreferredOpener;
    initiative: InitiativeViewReference | null;
    workspaceContext: WorkspaceContextState | null;
    warnings: WorkspaceStatus[];
}
export interface WorkspaceOpenJsonPayload {
    schema_version: 1;
    workspace: {
        name: string;
        root: string;
    };
    context: {
        context_store: {
            id: string;
            root: string;
            selector?: ContextStoreBinding['selector'];
        };
        initiative: {
            id: string;
            title: string;
            root: string;
            metadata_path: string;
            store_path: string;
        };
    } | null;
    generated_files: {
        agents: string;
        code_workspace: string;
    };
    opened_roots: PreparedWorkspaceOpen['openedRoots'];
    skipped_roots: Array<{
        kind: 'link';
        name: string;
        path: string | null;
        reason: PreparedWorkspaceOpen['skipped'][number]['reason'];
    }>;
    advisory_edit_boundaries: {
        allowed_edit_roots: string[];
        coordination_roots: string[];
        enforcement: 'advisory';
    };
    opener: PreparedWorkspaceOpen['opener'] & {
        label: string;
    };
    launch: {
        attempted: true;
        status: 'succeeded';
    };
    warnings: WorkspaceStatus[];
    status: WorkspaceStatus[];
}
export declare function assertWorkspaceOpenSupportedOptions(options: WorkspaceOpenOptions): void;
export declare function prepareWorkspaceOpen(positionalName: string | undefined, options: WorkspaceOpenOptions): Promise<PreparedWorkspaceOpen>;
export declare function buildWorkspaceOpenJsonPayload(prepared: PreparedWorkspaceOpen): WorkspaceOpenJsonPayload;
//# sourceMappingURL=open-view.d.ts.map