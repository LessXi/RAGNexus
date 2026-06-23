/**
 * New Change Command
 *
 * Creates a new change directory with optional description and schema.
 */
export interface NewChangeOptions {
    description?: string;
    goal?: string;
    areas?: string;
    schema?: string;
    initiative?: string;
    store?: string;
    storePath?: string;
    json?: boolean;
}
export declare function newChangeCommand(name: string | undefined, options: NewChangeOptions): Promise<void>;
//# sourceMappingURL=new-change.d.ts.map