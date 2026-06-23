import { z } from 'zod';
export declare const INITIATIVE_COLLECTION_ID = "initiatives";
export declare const INITIATIVE_FILE_NAME = "initiative.yaml";
export declare const INITIATIVE_REQUIREMENTS_FILE_NAME = "requirements.md";
export declare const INITIATIVE_DESIGN_FILE_NAME = "design.md";
export declare const INITIATIVE_DECISIONS_FILE_NAME = "decisions.md";
export declare const INITIATIVE_QUESTIONS_FILE_NAME = "questions.md";
export declare const INITIATIVE_TASKS_FILE_NAME = "tasks.md";
export declare const INITIATIVE_MARKDOWN_FILE_NAMES: readonly ["requirements.md", "design.md", "decisions.md", "questions.md", "tasks.md"];
export declare const INITIATIVE_FILE_NAMES: readonly ["initiative.yaml", "requirements.md", "design.md", "decisions.md", "questions.md", "tasks.md"];
export type InitiativeMarkdownFileName = typeof INITIATIVE_MARKDOWN_FILE_NAMES[number];
export type InitiativeFileName = typeof INITIATIVE_FILE_NAMES[number];
export declare const INITIATIVE_STATUSES: readonly ["exploring", "active", "complete", "archived"];
export type InitiativeStatus = typeof INITIATIVE_STATUSES[number];
export type InitiativeMetadataValue = string | number | boolean | null | InitiativeMetadataValue[] | {
    [key: string]: InitiativeMetadataValue;
};
export type InitiativeMetadata = Record<string, InitiativeMetadataValue>;
declare const InitiativeStateSchema: z.ZodObject<{
    version: z.ZodLiteral<1>;
    id: z.ZodString;
    title: z.ZodString;
    summary: z.ZodString;
    status: z.ZodEnum<{
        complete: "complete";
        active: "active";
        exploring: "exploring";
        archived: "archived";
    }>;
    created: z.ZodString;
    owners: z.ZodDefault<z.ZodArray<z.ZodString>>;
    metadata: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodType<InitiativeMetadataValue, unknown, z.core.$ZodTypeInternals<InitiativeMetadataValue, unknown>>>>;
}, z.core.$strict>;
export type InitiativeStateInput = z.input<typeof InitiativeStateSchema>;
export type InitiativeState = z.output<typeof InitiativeStateSchema>;
export declare function validateInitiativeId(id: string): string;
export declare function isValidInitiativeId(id: string): boolean;
export declare function parseInitiativeState(content: string): InitiativeState;
export declare function serializeInitiativeState(state: InitiativeStateInput): string;
export {};
//# sourceMappingURL=schema.d.ts.map