export interface PromptSetupLinksOptions {
    heading?: string;
    intro?: string;
    allowEmpty?: boolean;
    emptyName?: string;
    emptyShort?: string;
    emptyDescription?: string;
    finishName?: string;
    finishShort?: string;
    finishDescription?: string;
}
export declare function promptSetupLinks(options?: PromptSetupLinksOptions): Promise<Record<string, string>>;
//# sourceMappingURL=setup-prompts.d.ts.map