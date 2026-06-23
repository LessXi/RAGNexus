import { WorkspacePreferredOpener } from '../../core/workspace/index.js';
import { WorkspaceOpenOptions } from './types.js';
export declare function promptPreferredOpener(message: string, openerChoices?: import("../../core/workspace/openers.js").WorkspaceOpenerChoice[]): Promise<WorkspacePreferredOpener>;
export declare function parseSetupOpenerOption(opener: string | undefined): WorkspacePreferredOpener | undefined;
export declare function parseWorkspaceAgentOverride(agent: string): WorkspacePreferredOpener;
export declare function getPreferredWorkspaceSkillAgentId(preferredOpener: WorkspacePreferredOpener | undefined): string | null;
export declare function resolveWorkspaceOpenOpenerOverride(options: WorkspaceOpenOptions): WorkspacePreferredOpener | undefined;
export declare function resolveWorkspaceOpenOpener(localState: {
    preferred_opener?: WorkspacePreferredOpener;
}, options: WorkspaceOpenOptions): Promise<WorkspacePreferredOpener>;
//# sourceMappingURL=opener-selection.d.ts.map