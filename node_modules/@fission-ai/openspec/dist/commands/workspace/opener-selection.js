import { getDefaultWorkspaceOpenerChoiceValue, getWorkspaceSkillToolIds, listWorkspaceOpenerChoices, parseWorkspacePreferredOpenerValue, } from '../../core/workspace/index.js';
import { isInteractive, resolveNoInteractive } from '../../utils/interactive.js';
import { WorkspaceCliError, asErrorMessage } from './types.js';
import { workspaceSelectTheme } from './prompt-theme.js';
function formatOpenerChoiceName(choice) {
    return choice.unavailableNote ? `${choice.label} (${choice.unavailableNote})` : choice.label;
}
export async function promptPreferredOpener(message, openerChoices = listWorkspaceOpenerChoices()) {
    const { select } = await import('@inquirer/prompts');
    const selectedValue = await select({
        message,
        default: getDefaultWorkspaceOpenerChoiceValue(openerChoices),
        choices: openerChoices.map((choice) => ({
            name: formatOpenerChoiceName(choice),
            short: choice.label,
            value: choice.value,
            description: choice.unavailableNote ?? `Use ${choice.label}`,
        })),
        theme: workspaceSelectTheme,
    });
    return parseWorkspacePreferredOpenerValue(selectedValue);
}
export function parseSetupOpenerOption(opener) {
    if (!opener) {
        return undefined;
    }
    try {
        return parseWorkspacePreferredOpenerValue(opener);
    }
    catch (error) {
        throw new WorkspaceCliError(asErrorMessage(error), 'unsupported_workspace_opener', {
            target: 'workspace.opener',
            fix: 'Use --opener codex-cli, --opener claude, --opener github-copilot, or --opener editor.',
        });
    }
}
export function parseWorkspaceAgentOverride(agent) {
    let opener = null;
    try {
        opener = parseWorkspacePreferredOpenerValue(agent);
    }
    catch {
        opener = null;
    }
    if (!opener || opener.kind !== 'agent') {
        throw new WorkspaceCliError(`Unsupported workspace agent '${agent}'. Supported agents: codex-cli, claude, github-copilot.`, 'unsupported_workspace_agent', {
            target: 'workspace.opener',
            fix: 'Use --agent codex-cli, --agent claude, or --agent github-copilot.',
        });
    }
    return opener;
}
export function getPreferredWorkspaceSkillAgentId(preferredOpener) {
    if (!preferredOpener || preferredOpener.kind !== 'agent') {
        return null;
    }
    const toolId = preferredOpener.id === 'codex-cli' ? 'codex' : preferredOpener.id;
    return getWorkspaceSkillToolIds().includes(toolId) ? toolId : null;
}
export function resolveWorkspaceOpenOpenerOverride(options) {
    if (options.agent && options.editor) {
        throw new WorkspaceCliError('workspace open accepts either --agent <tool> or --editor, not both.', 'workspace_opener_conflict', {
            target: 'workspace.opener',
            fix: 'Choose one opener override.',
        });
    }
    if (options.agent) {
        return parseWorkspaceAgentOverride(options.agent);
    }
    if (options.editor) {
        return parseWorkspacePreferredOpenerValue('editor');
    }
    return undefined;
}
export async function resolveWorkspaceOpenOpener(localState, options) {
    const override = resolveWorkspaceOpenOpenerOverride(options);
    if (override) {
        return override;
    }
    if (localState.preferred_opener) {
        return localState.preferred_opener;
    }
    if (!resolveNoInteractive(options) && isInteractive(options)) {
        const openerChoices = listWorkspaceOpenerChoices().filter((choice) => choice.available);
        if (openerChoices.length === 0) {
            throw new WorkspaceCliError('No supported workspace opener is available on PATH.', 'workspace_no_available_openers', {
                target: 'workspace.opener',
                fix: "Install VS Code ('code'), codex-cli ('codex'), or Claude ('claude'), then retry.",
            });
        }
        return promptPreferredOpener('Open with:', openerChoices);
    }
    throw new WorkspaceCliError('This workspace does not have a preferred opener yet.', 'workspace_opener_unset', {
        target: 'workspace.opener',
        fix: 'Pass --agent <tool> or --editor, or run workspace setup interactively to choose a default opener.',
    });
}
//# sourceMappingURL=opener-selection.js.map