import { type AIToolOption } from '../config.js';
import { type Delivery, type Profile } from '../global-config.js';
import type { WorkspaceSkillState } from './foundation.js';
export interface WorkspaceSkillAgentResult {
    tool_id: string;
    name: string;
    skills_path: string;
    workflow_ids: string[];
}
export interface WorkspaceSkillRemovedResult extends WorkspaceSkillAgentResult {
    reason: 'agent_unselected' | 'workflow_unselected';
}
export interface WorkspaceSkillSkippedResult {
    tool_id?: string;
    name?: string;
    reason: string;
    message: string;
}
export interface WorkspaceSkillFailedResult {
    tool_id: string;
    name: string;
    error: string;
}
export interface WorkspaceSkillInstallationReport {
    profile: Profile;
    delivery: Delivery;
    workflow_ids: string[];
    selected_agents: string[];
    skills_only: true;
    delivery_notice: string | null;
    generated: WorkspaceSkillAgentResult[];
    added: WorkspaceSkillAgentResult[];
    refreshed: WorkspaceSkillAgentResult[];
    removed: WorkspaceSkillRemovedResult[];
    skipped: WorkspaceSkillSkippedResult[];
    failed: WorkspaceSkillFailedResult[];
}
type WorkspaceSkillCapableTool = AIToolOption & {
    skillsDir: string;
};
export declare function getCurrentWorkspaceSkillProfileSelection(): {
    profile: Profile;
    delivery: Delivery;
    workflow_ids: string[];
};
export declare function hasWorkspaceSkillProfileDrift(state: {
    workspace_skills?: WorkspaceSkillState;
} | null | undefined): boolean;
export declare function getWorkspaceSkillCapableTools(): WorkspaceSkillCapableTool[];
export declare function getWorkspaceSkillToolIds(): string[];
export declare function parseWorkspaceSkillToolsValue(rawTools: string): string[];
export declare function createWorkspaceSkillSkippedReport(reason: string, message: string): WorkspaceSkillInstallationReport;
export declare function getWorkspaceSkillDirectory(workspaceRoot: string, toolId: string): string;
export declare function generateWorkspaceAgentSkills(workspaceRoot: string, selectedAgentIds: string[]): Promise<WorkspaceSkillInstallationReport>;
export declare function updateWorkspaceAgentSkills(workspaceRoot: string, selectedAgentIds: string[], previousSkillState?: WorkspaceSkillState): Promise<WorkspaceSkillInstallationReport>;
export {};
//# sourceMappingURL=skills.d.ts.map