import { InitiativeResolutionError, } from '../../core/collections/initiatives/index.js';
export const REPO_LOCAL_INITIATIVE_LINK_ERROR = 'Initiative links are supported only for repo-local changes. Run this command from the repo that owns the implementation plan.';
export function printJson(payload) {
    console.log(JSON.stringify(payload, null, 2));
}
export function statusFromError(error) {
    if (error instanceof InitiativeResolutionError) {
        return {
            severity: 'error',
            code: error.code,
            message: error.message,
            ...(error.target ? { target: error.target } : {}),
            ...(error.fix ? { fix: error.fix } : {}),
            ...(error.details ? { details: error.details } : {}),
        };
    }
    return {
        severity: 'error',
        code: 'change_error',
        message: error instanceof Error ? error.message : String(error),
    };
}
export function assertInitiativeSelectorsHaveReference(options) {
    if (!options.initiative && (options.store !== undefined || options.storePath !== undefined)) {
        throw new Error('Pass --initiative when using --store or --store-path.');
    }
    if (options.initiative !== undefined && options.initiative.trim().length === 0) {
        throw new Error('Pass --initiative <id> to link a change to an initiative.');
    }
}
export function assertInitiativeReference(value) {
    if (value === undefined || value.trim().length === 0) {
        throw new Error('Pass --initiative <id> to set a change initiative link.');
    }
}
export function assertRepoLocalInitiativeLinkPlanningHome(planningHome) {
    if (planningHome.kind === 'workspace') {
        throw new Error(REPO_LOCAL_INITIATIVE_LINK_ERROR);
    }
}
export function formatInitiativeLink(initiative) {
    return `${initiative.store}/${initiative.id}`;
}
export function sameInitiativeLink(left, right) {
    return left?.store === right.store && left.id === right.id;
}
//# sourceMappingURL=initiative-link.js.map