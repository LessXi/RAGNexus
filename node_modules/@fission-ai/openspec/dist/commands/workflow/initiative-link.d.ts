import type { PlanningHome } from '../../core/planning-home.js';
import { type InitiativeLinkReference } from '../../core/collections/initiatives/index.js';
export interface ChangeCommandStatus {
    severity: 'error' | 'warning';
    code: string;
    message: string;
    target?: string;
    fix?: string;
    details?: unknown;
}
export interface InitiativeSelectorOptions {
    initiative?: string;
    store?: string;
    storePath?: string;
}
export declare const REPO_LOCAL_INITIATIVE_LINK_ERROR = "Initiative links are supported only for repo-local changes. Run this command from the repo that owns the implementation plan.";
export declare function printJson(payload: unknown): void;
export declare function statusFromError(error: unknown): ChangeCommandStatus;
export declare function assertInitiativeSelectorsHaveReference(options: InitiativeSelectorOptions): void;
export declare function assertInitiativeReference(value: string | undefined): asserts value is string;
export declare function assertRepoLocalInitiativeLinkPlanningHome(planningHome: PlanningHome): void;
export declare function formatInitiativeLink(initiative: InitiativeLinkReference): string;
export declare function sameInitiativeLink(left: InitiativeLinkReference | undefined, right: InitiativeLinkReference): boolean;
//# sourceMappingURL=initiative-link.d.ts.map