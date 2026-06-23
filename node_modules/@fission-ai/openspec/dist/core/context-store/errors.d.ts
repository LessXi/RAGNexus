export type ContextStoreDiagnosticSeverity = 'error' | 'warning';
export interface ContextStoreDiagnostic {
    severity: ContextStoreDiagnosticSeverity;
    code: string;
    message: string;
    target?: string;
    fix?: string;
}
export declare class ContextStoreError extends Error {
    readonly diagnostic: ContextStoreDiagnostic;
    constructor(message: string, code: string, options?: {
        target?: string;
        fix?: string;
    });
}
export declare function makeContextStoreDiagnostic(severity: ContextStoreDiagnosticSeverity, code: string, message: string, options?: {
    target?: string;
    fix?: string;
}): ContextStoreDiagnostic;
//# sourceMappingURL=errors.d.ts.map