import type { ChangeMetadata } from './change-metadata/index.js';
import type { PlanningHome } from './planning-home.js';
export interface PlanningHomeSummary {
    kind: 'repo' | 'workspace';
    root: string;
    changesDir: string;
    defaultSchema: string;
    workspaceName?: string;
}
export interface AffectedAreasSummary {
    known: string[];
    unresolved: boolean;
    invalid: string[];
}
export interface ActionContext {
    mode: 'repo-local' | 'workspace-planning';
    sourceOfTruth: 'repo' | 'workspace-local';
    planningArtifacts: string[];
    linkedContext: Array<{
        name: string;
    }>;
    allowedEditRoots: string[];
    requiresAffectedAreaSelection: boolean;
    constraints: string[];
}
export interface ChangeStatusPolicyArtifact {
    id: string;
    status: 'done' | 'ready' | 'blocked';
}
export interface AffectedAreasInput {
    planningHome?: PlanningHome;
    metadata?: ChangeMetadata;
}
export interface ChangeNextStepsInput {
    changeName: string;
    planningHome?: PlanningHome;
    artifactStatuses: ChangeStatusPolicyArtifact[];
    affectedAreas?: AffectedAreasSummary;
    allArtifactsComplete: boolean;
}
export interface ActionContextInput {
    planningHome?: PlanningHome;
    projectRoot: string;
    artifactIds: string[];
}
export declare function summarizePlanningHome(planningHome: PlanningHome | undefined): PlanningHomeSummary | undefined;
export declare function summarizeAffectedAreas(input: AffectedAreasInput): AffectedAreasSummary | undefined;
export declare function buildActionContext(input: ActionContextInput): ActionContext;
export declare function buildNextSteps(input: ChangeNextStepsInput): string[];
//# sourceMappingURL=change-status-policy.d.ts.map