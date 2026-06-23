import { createRequire } from 'node:module';
import { getWorkspaceCodeWorkspacePath, getWorkspaceOpenerExecutable, getWorkspaceOpenerLabel, isWorkspaceExecutableAvailable, readWorkspaceViewState, syncWorkspaceOpenSurface, } from '../../core/workspace/index.js';
import { WorkspaceCliError, asErrorMessage } from './types.js';
export const WORKSPACE_OPEN_MINIMAL_PROMPT = 'Open this OpenSpec workspace.';
const CODEX_CLI_WRITABLE_ROOT_SANDBOX_ARGS = ['--sandbox', 'workspace-write'];
const require = createRequire(import.meta.url);
const spawn = require('cross-spawn');
function isCodexCliOpener(opener) {
    const openerId = opener.id;
    return opener.kind === 'agent' && (openerId === 'codex-cli' || openerId === 'codex');
}
export async function readWorkspaceOpenState(selected) {
    const viewState = await readWorkspaceViewState(selected.root);
    return {
        viewState,
        codeWorkspacePath: getWorkspaceCodeWorkspacePath(selected.root, viewState.name),
    };
}
export function buildWorkspaceOpenLaunchCommand(opener, workspaceRoot, codeWorkspacePath, attachedPaths) {
    const executable = getWorkspaceOpenerExecutable(opener);
    const openerLabel = getWorkspaceOpenerLabel(opener);
    if (opener.kind === 'editor' || opener.id === 'github-copilot') {
        return {
            executable,
            args: [codeWorkspacePath],
            cwd: workspaceRoot,
            openerLabel,
        };
    }
    return {
        executable,
        args: [
            ...(isCodexCliOpener(opener) && attachedPaths.length > 0
                ? CODEX_CLI_WRITABLE_ROOT_SANDBOX_ARGS
                : []),
            ...attachedPaths.flatMap((linkedPath) => ['--add-dir', linkedPath]),
            WORKSPACE_OPEN_MINIMAL_PROMPT,
        ],
        cwd: workspaceRoot,
        openerLabel,
    };
}
export function assertWorkspaceOpenerAvailable(opener, codeWorkspacePath, isExecutableAvailable = isWorkspaceExecutableAvailable) {
    const executable = getWorkspaceOpenerExecutable(opener);
    if (isExecutableAvailable(executable)) {
        return;
    }
    const openerLabel = getWorkspaceOpenerLabel(opener);
    const manualPath = executable === 'code'
        ? ` You can open the workspace file manually: ${codeWorkspacePath}`
        : '';
    throw new WorkspaceCliError(`${openerLabel} requires '${executable}', but '${executable}' was not found on PATH.${manualPath}`, 'workspace_opener_unavailable', {
        target: 'workspace.opener',
        fix: `Install '${executable}' or choose another opener.`,
    });
}
export async function buildWorkspaceOpenCommandForState(opener, workspaceRoot, state, resolvedContext) {
    const openSurface = await syncWorkspaceOpenSurface(workspaceRoot, state.viewState, resolvedContext);
    const openedRoots = [
        { kind: 'workspace', path: workspaceRoot },
        ...(resolvedContext
            ? [
                {
                    kind: 'initiative',
                    name: resolvedContext.initiative.id,
                    path: resolvedContext.initiative.root,
                },
            ]
            : []),
        ...openSurface.links.map((link) => ({
            kind: 'link',
            name: link.name,
            path: link.path,
        })),
    ];
    return {
        command: buildWorkspaceOpenLaunchCommand(opener, workspaceRoot, state.codeWorkspacePath, openedRoots
            .filter((root) => root.kind !== 'workspace')
            .map((root) => root.path)),
        skipped: openSurface.skipped,
        generated: openSurface.generated,
        openedRoots,
    };
}
export async function launchWorkspaceOpenCommand(command, options = {}) {
    const spawnCommand = options.spawn ?? spawn;
    await new Promise((resolve, reject) => {
        const child = spawnCommand(command.executable, command.args, {
            cwd: command.cwd,
            stdio: options.stdio ?? 'inherit',
            shell: false,
        });
        child.on('error', (error) => {
            reject(new WorkspaceCliError(`Could not launch ${command.openerLabel}: ${asErrorMessage(error)}`, 'workspace_opener_launch_failed', {
                target: 'workspace.opener',
            }));
        });
        child.on('close', (code, signal) => {
            if (code === 0) {
                resolve();
                return;
            }
            const reason = signal ? `signal ${signal}` : `exit code ${code}`;
            reject(new WorkspaceCliError(`${command.openerLabel} exited with ${reason}.`, 'workspace_opener_launch_failed', {
                target: 'workspace.opener',
            }));
        });
    });
}
//# sourceMappingURL=open.js.map