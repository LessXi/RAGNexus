import { type InitiativeMarkdownFileName, type InitiativeState } from './schema.js';
export interface InitiativeTemplateFile {
    fileName: InitiativeMarkdownFileName;
    content: string;
}
export declare function buildInitiativeRequirementsTemplate(state: InitiativeState): string;
export declare function buildInitiativeDesignTemplate(state: InitiativeState): string;
export declare function buildInitiativeDecisionsTemplate(state: InitiativeState): string;
export declare function buildInitiativeQuestionsTemplate(): string;
export declare function buildInitiativeTasksTemplate(): string;
export declare function buildDefaultInitiativeFiles(state: InitiativeState): InitiativeTemplateFile[];
//# sourceMappingURL=templates.d.ts.map