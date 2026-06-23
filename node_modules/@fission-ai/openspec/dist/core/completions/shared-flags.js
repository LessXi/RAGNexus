/**
 * Common flags used across multiple commands.
 */
export const COMMON_FLAGS = {
    json: {
        name: 'json',
        description: 'Output as JSON',
    },
    jsonValidation: {
        name: 'json',
        description: 'Output validation results as JSON',
    },
    strict: {
        name: 'strict',
        description: 'Enable strict validation mode',
    },
    noInteractive: {
        name: 'no-interactive',
        description: 'Disable interactive prompts',
    },
    type: {
        name: 'type',
        description: 'Specify item type when ambiguous',
        takesValue: true,
        values: ['change', 'spec'],
    },
};
//# sourceMappingURL=shared-flags.js.map