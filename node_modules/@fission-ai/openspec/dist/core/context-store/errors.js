export class ContextStoreError extends Error {
    diagnostic;
    constructor(message, code, options = {}) {
        super(message);
        this.name = 'ContextStoreError';
        this.diagnostic = {
            severity: 'error',
            code,
            message,
            ...options,
        };
    }
}
export function makeContextStoreDiagnostic(severity, code, message, options = {}) {
    return {
        severity,
        code,
        message,
        ...options,
    };
}
//# sourceMappingURL=errors.js.map