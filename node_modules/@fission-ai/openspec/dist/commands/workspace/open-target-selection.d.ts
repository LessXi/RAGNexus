import { type InitiativeViewReference } from '../../core/collections/initiatives/index.js';
import { type SelectedWorkspace, type WorkspaceOpenOptions, type WorkspaceStatus } from './types.js';
export type WorkspaceOpenTarget = {
    kind: 'workspace';
    selected: SelectedWorkspace;
    status: WorkspaceStatus[];
} | {
    kind: 'initiative';
    initiative: InitiativeViewReference;
    status: WorkspaceStatus[];
};
export declare function selectWorkspaceOpenTarget(workspaceName: string | undefined, options: WorkspaceOpenOptions): Promise<WorkspaceOpenTarget>;
//# sourceMappingURL=open-target-selection.d.ts.map