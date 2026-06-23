import { ArtifactGraph } from './graph.js';
import { type ActionContext, type AffectedAreasSummary, type PlanningHomeSummary } from '../change-status-policy.js';
import type { PlanningHome } from '../planning-home.js';
import type { ChangeMetadata, InitiativeLink } from '../change-metadata/index.js';
import type { CompletedSet } from './types.js';
/**
 * Error thrown when loading a template fails.
 */
export declare class TemplateLoadError extends Error {
    readonly templatePath: string;
    constructor(message: string, templatePath: string);
}
/**
 * Change context containing graph, completion state, and metadata.
 */
export interface ChangeContext {
    /** The artifact dependency graph */
    graph: ArtifactGraph;
    /** Set of completed artifact IDs */
    completed: CompletedSet;
    /** Schema name being used */
    schemaName: string;
    /** Change name */
    changeName: string;
    /** Path to the change directory */
    changeDir: string;
    /** Project root directory */
    projectRoot: string;
    /** Resolved planning home for this change */
    planningHome?: PlanningHome;
    /** Parsed change metadata, when present */
    metadata?: ChangeMetadata;
    /** Stored initiative link, when this change is linked to shared context */
    initiative?: InitiativeLink;
}
export interface LoadChangeContextOptions {
    changeDir?: string;
    planningHome?: PlanningHome;
}
/**
 * Enriched instructions for creating an artifact.
 */
export interface ArtifactInstructions {
    /** Change name */
    changeName: string;
    /** Artifact ID */
    artifactId: string;
    /** Schema name */
    schemaName: string;
    /** Full path to change directory */
    changeDir: string;
    /** Resolved planning home for this change */
    planningHome?: PlanningHomeSummary;
    /** Stored initiative link, when this change is linked to shared context */
    initiative?: InitiativeLink;
    /** Output path pattern (e.g., "proposal.md") */
    outputPath: string;
    /** Absolute output path or glob pattern resolved under the change directory */
    resolvedOutputPath: string;
    /** Existing concrete output files for this artifact */
    existingOutputPaths: string[];
    /** Artifact description */
    description: string;
    /** Guidance on how to create this artifact (from schema instruction field) */
    instruction: string | undefined;
    /** Project context from config (constraints/background for AI, not to be included in output) */
    context: string | undefined;
    /** Artifact-specific rules from config (constraints for AI, not to be included in output) */
    rules: string[] | undefined;
    /** Template content (structure to follow - this IS the output format) */
    template: string;
    /** Dependencies with completion status and paths */
    dependencies: DependencyInfo[];
    /** Artifacts that become available after completing this one */
    unlocks: string[];
}
/**
 * Dependency information including path and description.
 */
export interface DependencyInfo {
    /** Artifact ID */
    id: string;
    /** Whether the dependency is completed */
    done: boolean;
    /** Relative output path of the dependency (e.g., "proposal.md") */
    path: string;
    /** Description of the dependency artifact */
    description: string;
}
/**
 * Status of a single artifact in the workflow.
 */
export interface ArtifactStatus {
    /** Artifact ID */
    id: string;
    /** Output path pattern */
    outputPath: string;
    /** Status: done, ready, or blocked */
    status: 'done' | 'ready' | 'blocked';
    /** Missing dependencies (only for blocked) */
    missingDeps?: string[];
}
/**
 * Formatted change status.
 */
export interface ChangeStatus {
    /** Change name */
    changeName: string;
    /** Schema name */
    schemaName: string;
    /** Resolved planning home for this change */
    planningHome?: PlanningHomeSummary;
    /** Stored initiative link, when this change is linked to shared context */
    initiative?: InitiativeLink;
    /** Full path to the change root */
    changeRoot: string;
    /** Absolute artifact path details keyed by artifact ID */
    artifactPaths: Record<string, ArtifactPathSummary>;
    /** Workspace affected-area summary, when available */
    affectedAreas?: AffectedAreasSummary;
    /** Plain-language next steps for users and agents */
    nextSteps: string[];
    /** Machine-readable action constraints for agents */
    actionContext: ActionContext;
    /** Whether all artifacts are complete */
    isComplete: boolean;
    /** Artifact IDs required before apply phase (from schema's apply.requires) */
    applyRequires: string[];
    /** Status of each artifact */
    artifacts: ArtifactStatus[];
}
export interface ArtifactPathSummary {
    outputPath: string;
    resolvedOutputPath: string;
    existingOutputPaths: string[];
}
/**
 * Loads a template from a schema's templates directory.
 *
 * @param schemaName - Schema name (e.g., "spec-driven")
 * @param templatePath - Relative path within the templates directory (e.g., "proposal.md")
 * @param projectRoot - Optional project root for project-local schema resolution
 * @returns The template content
 * @throws TemplateLoadError if the template cannot be loaded
 */
export declare function loadTemplate(schemaName: string, templatePath: string, projectRoot?: string): string;
/**
 * Loads change context combining graph and completion state.
 *
 * Schema resolution order:
 * 1. Explicit schemaName parameter (if provided)
 * 2. Schema from .openspec.yaml metadata (if exists in change directory)
 * 3. Default 'spec-driven'
 *
 * @param projectRoot - Project root directory
 * @param changeName - Change name
 * @param schemaName - Optional schema name override. If not provided, auto-detected from metadata.
 * @returns Change context with graph, completed set, and metadata
 */
export declare function loadChangeContext(projectRoot: string, changeName: string, schemaName?: string, options?: LoadChangeContextOptions): ChangeContext;
/**
 * Generates enriched instructions for creating an artifact.
 *
 * Instruction injection order:
 * 1. <context> - Project context from config (if present)
 * 2. <rules> - Artifact-specific rules from config (if present)
 * 3. <template> - Schema's template content
 *
 * @param context - Change context
 * @param artifactId - Artifact ID to generate instructions for
 * @param projectRoot - Project root directory (for reading config)
 * @returns Enriched artifact instructions
 * @throws Error if artifact not found
 */
export declare function generateInstructions(context: ChangeContext, artifactId: string, projectRoot?: string): ArtifactInstructions;
/**
 * Formats the status of all artifacts in a change.
 *
 * @param context - Change context
 * @returns Formatted change status
 */
export declare function formatChangeStatus(context: ChangeContext): ChangeStatus;
//# sourceMappingURL=instruction-loader.d.ts.map