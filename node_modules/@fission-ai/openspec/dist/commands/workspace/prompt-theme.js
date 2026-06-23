import chalk from 'chalk';
export const workspacePromptTheme = {
    prefix: '',
    style: {
        answer: (text) => chalk.cyan(text),
        defaultAnswer: (text) => chalk.dim(text),
        error: (text) => chalk.red(text),
        help: (text) => chalk.dim(text),
        highlight: (text) => chalk.cyan(text),
        key: (text) => chalk.cyan(text),
        message: (text) => chalk.bold(text),
    },
};
export const workspaceSelectTheme = {
    ...workspacePromptTheme,
    icon: {
        cursor: chalk.cyan('>'),
    },
    style: {
        ...workspacePromptTheme.style,
        keysHelpTip: (keys) => chalk.dim(keys.map(([key, action]) => `${key}: ${action}`).join(' | ')),
    },
};
//# sourceMappingURL=prompt-theme.js.map