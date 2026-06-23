import { type WorkspaceRegistryEntry } from '../../core/workspace/index.js';
import { SelectedWorkspace, WorkspaceSelectionOptions } from './types.js';
export declare function selectedWorkspaceFromEntry(entry: WorkspaceRegistryEntry): SelectedWorkspace;
export declare function selectedWorkspaceFromRoot(currentWorkspaceRoot: string, entries: WorkspaceRegistryEntry[]): Promise<SelectedWorkspace>;
export declare function selectWorkspaceForCommand(options: WorkspaceSelectionOptions, commandName: string, selectionOptions?: {
    preferPositionalName?: boolean;
}): Promise<SelectedWorkspace>;
//# sourceMappingURL=selection.d.ts.map