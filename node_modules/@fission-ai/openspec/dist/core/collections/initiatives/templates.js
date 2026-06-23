import { INITIATIVE_DECISIONS_FILE_NAME, INITIATIVE_DESIGN_FILE_NAME, INITIATIVE_MARKDOWN_FILE_NAMES, INITIATIVE_QUESTIONS_FILE_NAME, INITIATIVE_REQUIREMENTS_FILE_NAME, INITIATIVE_TASKS_FILE_NAME, } from './schema.js';
function withTrailingNewline(content) {
    return content.endsWith('\n') ? content : `${content}\n`;
}
export function buildInitiativeRequirementsTemplate(state) {
    return withTrailingNewline(`# Requirements

## Product Intent

${state.summary}

## Accepted Requirements

- TBD

## Out Of Scope

- TBD
`);
}
export function buildInitiativeDesignTemplate(state) {
    return withTrailingNewline(`# Design

## Context

${state.summary}

## Approach

TBD

## Affected Areas

- TBD

## Dependencies

- TBD

## Risks

- TBD
`);
}
export function buildInitiativeDecisionsTemplate(state) {
    return withTrailingNewline(`# Decisions

## Accepted Decisions

### ${state.created}: ${state.title}

- Decision: TBD
- Why: TBD
- Implications: TBD
`);
}
export function buildInitiativeQuestionsTemplate() {
    return withTrailingNewline(`# Questions

## Open Questions

- TBD

## Resolved Questions

- TBD
`);
}
export function buildInitiativeTasksTemplate() {
    return withTrailingNewline(`# Tasks

## Coordination Tasks

- [ ] TBD
`);
}
export function buildDefaultInitiativeFiles(state) {
    const templates = {
        [INITIATIVE_REQUIREMENTS_FILE_NAME]: buildInitiativeRequirementsTemplate(state),
        [INITIATIVE_DESIGN_FILE_NAME]: buildInitiativeDesignTemplate(state),
        [INITIATIVE_DECISIONS_FILE_NAME]: buildInitiativeDecisionsTemplate(state),
        [INITIATIVE_QUESTIONS_FILE_NAME]: buildInitiativeQuestionsTemplate(),
        [INITIATIVE_TASKS_FILE_NAME]: buildInitiativeTasksTemplate(),
    };
    return INITIATIVE_MARKDOWN_FILE_NAMES.map((fileName) => ({
        fileName,
        content: templates[fileName],
    }));
}
//# sourceMappingURL=templates.js.map