/**
 * Set Change Command
 *
 * Mutates checked-in repo-local change metadata.
 */
export interface SetChangeOptions {
    initiative?: string;
    store?: string;
    storePath?: string;
    json?: boolean;
}
export declare function setChangeCommand(name: string | undefined, options: SetChangeOptions): Promise<void>;
//# sourceMappingURL=set-change.d.ts.map