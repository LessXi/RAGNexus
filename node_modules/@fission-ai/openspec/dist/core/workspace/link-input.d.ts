export interface WorkspaceParsedLinkInput {
    name?: string;
    pathInput: string;
}
export interface WorkspaceLinkInputParseOptions {
    cwd?: string;
}
export declare function parseWorkspaceSetupLinkInput(value: string, options?: WorkspaceLinkInputParseOptions): Promise<WorkspaceParsedLinkInput>;
//# sourceMappingURL=link-input.d.ts.map