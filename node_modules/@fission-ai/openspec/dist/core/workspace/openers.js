import * as nodeFs from 'node:fs';
import * as path from 'node:path';
import { parseWorkspacePreferredOpenerValue, } from './foundation.js';
const fs = nodeFs;
const WORKSPACE_OPENER_CHOICE_DEFINITIONS = [
    {
        value: 'editor',
        label: 'VS Code editor',
        executable: 'code',
    },
    {
        value: 'codex-cli',
        label: 'codex-cli',
        executable: 'codex',
    },
    {
        value: 'claude',
        label: 'Claude',
        executable: 'claude',
    },
    {
        value: 'github-copilot',
        label: 'GitHub Copilot in VS Code',
        executable: 'code',
    },
];
function getPathValue(env) {
    return env.PATH ?? env.Path ?? env.path ?? '';
}
function getPathExts(env, platform) {
    if (platform !== 'win32') {
        return [''];
    }
    const pathExt = env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD';
    return pathExt
        .split(';')
        .map((extension) => extension.trim())
        .filter((extension) => extension.length > 0);
}
function isExecutableFile(candidatePath, platform) {
    try {
        const stats = fs.statSync(candidatePath);
        if (!stats.isFile()) {
            return false;
        }
        if (platform === 'win32') {
            return true;
        }
        fs.accessSync(candidatePath, fs.constants.X_OK);
        return true;
    }
    catch {
        return false;
    }
}
export function isWorkspaceExecutableAvailable(executable, options = {}) {
    const env = options.env ?? process.env;
    const platform = options.platform ?? process.platform;
    if (executable.includes('/') || executable.includes('\\')) {
        return isExecutableFile(executable, platform);
    }
    const pathEntries = getPathValue(env)
        .split(path.delimiter)
        .filter((entry) => entry.length > 0);
    const pathExts = getPathExts(env, platform);
    for (const entry of pathEntries) {
        for (const extension of pathExts) {
            const candidate = path.join(entry, executable + extension);
            if (isExecutableFile(candidate, platform)) {
                return true;
            }
        }
    }
    return false;
}
export function getWorkspaceOpenerExecutable(opener) {
    const openerId = opener.id;
    if (opener.kind === 'editor') {
        return 'code';
    }
    if (openerId === 'github-copilot') {
        return 'code';
    }
    if (openerId === 'codex-cli' || openerId === 'codex') {
        return 'codex';
    }
    return opener.id;
}
export function getWorkspaceOpenerLabel(opener) {
    const openerId = opener.id;
    if (opener.kind === 'editor') {
        return 'VS Code editor';
    }
    if (openerId === 'github-copilot') {
        return 'GitHub Copilot in VS Code';
    }
    if (openerId === 'codex-cli' || openerId === 'codex') {
        return 'codex-cli';
    }
    return 'Claude';
}
export function listWorkspaceOpenerChoices(options = {}) {
    const choices = WORKSPACE_OPENER_CHOICE_DEFINITIONS.map((definition) => {
        const available = isWorkspaceExecutableAvailable(definition.executable, options);
        return {
            value: definition.value,
            label: definition.label,
            opener: parseWorkspacePreferredOpenerValue(definition.value),
            executable: definition.executable,
            available,
            unavailableNote: available ? null : `${definition.executable} not found on PATH`,
        };
    });
    return choices.sort((a, b) => {
        if (a.available !== b.available) {
            return a.available ? -1 : 1;
        }
        return 0;
    });
}
export function getDefaultWorkspaceOpenerChoiceValue(choices) {
    return choices.find((choice) => choice.available)?.value ?? 'editor';
}
//# sourceMappingURL=openers.js.map