export function summarizePlanningHome(planningHome) {
    if (!planningHome) {
        return undefined;
    }
    return {
        kind: planningHome.kind,
        root: planningHome.root,
        changesDir: planningHome.changesDir,
        defaultSchema: planningHome.defaultSchema,
        ...(planningHome.workspace ? { workspaceName: planningHome.workspace.name } : {}),
    };
}
export function summarizeAffectedAreas(input) {
    if (input.planningHome?.kind !== 'workspace') {
        return undefined;
    }
    const known = Array.from(new Set(input.metadata?.affected_areas ?? [])).sort((a, b) => a.localeCompare(b));
    const validAreas = new Set(input.planningHome.workspace?.links ?? []);
    const invalid = known.filter((areaName) => validAreas.size > 0 && !validAreas.has(areaName));
    return {
        known,
        unresolved: known.length === 0,
        invalid,
    };
}
export function buildActionContext(input) {
    if (input.planningHome?.kind === 'workspace') {
        return {
            mode: 'workspace-planning',
            sourceOfTruth: 'workspace-local',
            planningArtifacts: input.artifactIds,
            linkedContext: (input.planningHome.workspace?.links ?? []).map((name) => ({ name })),
            allowedEditRoots: [],
            requiresAffectedAreaSelection: true,
            constraints: [
                'Treat workspace-local planning artifacts as compatibility context for this local view.',
                'Use initiatives for durable coordination when initiative context exists.',
                'Treat linked repos and folders as context until an explicit edit root is selected.',
                'Do not make implementation edits without an explicit allowed edit root.',
            ],
        };
    }
    return {
        mode: 'repo-local',
        sourceOfTruth: 'repo',
        planningArtifacts: input.artifactIds,
        linkedContext: [],
        allowedEditRoots: [input.projectRoot],
        requiresAffectedAreaSelection: false,
        constraints: ['Repo-local change artifacts and implementation edits are scoped to this project.'],
    };
}
export function buildNextSteps(input) {
    const readyArtifact = input.artifactStatuses.find((artifact) => artifact.status === 'ready');
    const steps = [];
    if (readyArtifact) {
        steps.push(`Run openspec instructions ${readyArtifact.id} --change "${input.changeName}" --json before writing that artifact.`);
    }
    else if (input.allArtifactsComplete) {
        steps.push('All planning artifacts are complete; review tasks before implementation.');
    }
    if (input.planningHome?.kind === 'workspace') {
        if (input.affectedAreas?.unresolved) {
            steps.push('Identify affected areas in change metadata or coordination tasks as planning continues.');
        }
        steps.push('Select an affected area and allowed edit root before implementation edits.');
    }
    return steps;
}
//# sourceMappingURL=change-status-policy.js.map