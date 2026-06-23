import { WorkspacePreferredOpener, WorkspaceSupportedOpenerValue } from './foundation.js';
export interface WorkspaceOpenerChoice {
    value: WorkspaceSupportedOpenerValue;
    label: string;
    opener: WorkspacePreferredOpener;
    executable: string;
    available: boolean;
    unavailableNote: string | null;
}
export declare function isWorkspaceExecutableAvailable(executable: string, options?: {
    env?: NodeJS.ProcessEnv;
    platform?: NodeJS.Platform;
}): boolean;
export declare function getWorkspaceOpenerExecutable(opener: WorkspacePreferredOpener): string;
export declare function getWorkspaceOpenerLabel(opener: WorkspacePreferredOpener): string;
export declare function listWorkspaceOpenerChoices(options?: {
    env?: NodeJS.ProcessEnv;
    platform?: NodeJS.Platform;
}): WorkspaceOpenerChoice[];
export declare function getDefaultWorkspaceOpenerChoiceValue(choices: WorkspaceOpenerChoice[]): WorkspaceSupportedOpenerValue;
//# sourceMappingURL=openers.d.ts.map