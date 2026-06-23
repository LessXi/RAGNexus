export class WorkspaceCliError extends Error {
    status;
    constructor(message, code, options = {}) {
        super(message);
        this.status = {
            severity: 'error',
            code,
            message,
            ...options,
        };
    }
}
export function makeStatus(severity, code, message, options = {}) {
    return {
        severity,
        code,
        message,
        ...options,
    };
}
export function asErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
export function asStatus(error) {
    if (error instanceof WorkspaceCliError) {
        return error.status;
    }
    return makeStatus('error', 'workspace_error', asErrorMessage(error));
}
export function appendStatus(payload, status) {
    return {
        ...payload,
        status: [...payload.status, status],
    };
}
//# sourceMappingURL=types.js.map