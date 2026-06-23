import { getWorkspaceSkillToolIds } from '../../core/workspace/index.js';
function collectOption(value, previous) {
    return [...previous, value];
}
function addWorkspaceSelectionOptions(command) {
    return command
        .option('--workspace <name>', 'Workspace name from known local workspace views')
        .option('--json', 'Output as JSON')
        .option('--no-interactive', 'Disable prompts');
}
export function registerWorkspaceCommandWith(program, workspaceCommand) {
    const workspace = program
        .command('workspace')
        .description('Set up and inspect coordination workspaces');
    workspace
        .command('setup')
        .description('Set up a workspace and link existing repos or folders')
        .option('--name <name>', 'Workspace name')
        .option('--link <link>', 'Repo or folder link. Use <path> or <name>=<path>.', collectOption, [])
        .option('--opener <id>', 'Preferred opener: codex-cli, claude, github-copilot, or editor')
        .option('--tools <tools>', `Install OpenSpec skills for agents. Use "all", "none", or a comma-separated list of: ${getWorkspaceSkillToolIds().join(', ')}`)
        .option('--json', 'Output as JSON')
        .option('--no-interactive', 'Disable prompts')
        .action(async (options) => {
        await workspaceCommand.setup(options);
    });
    workspace
        .command('list')
        .description('List known OpenSpec workspaces')
        .option('--json', 'Output as JSON')
        .action(async (options) => {
        await workspaceCommand.list(options);
    });
    workspace
        .command('ls')
        .description('List known OpenSpec workspaces')
        .option('--json', 'Output as JSON')
        .action(async (options) => {
        await workspaceCommand.list(options);
    });
    addWorkspaceSelectionOptions(workspace
        .command('link [nameOrPath] [path]')
        .description('Link an existing repo or folder to a workspace')).action(async (nameOrPath, linkPath, options) => {
        await workspaceCommand.link(nameOrPath, linkPath, options);
    });
    addWorkspaceSelectionOptions(workspace
        .command('relink <name> <path>')
        .description('Update the local path for an existing workspace link')).action(async (linkName, linkPath, options) => {
        await workspaceCommand.relink(linkName, linkPath, options);
    });
    addWorkspaceSelectionOptions(workspace
        .command('doctor')
        .description('Check what a workspace can resolve on this machine')).action(async (options) => {
        await workspaceCommand.doctor(options);
    });
    workspace
        .command('update [name]')
        .description('Refresh workspace-local OpenSpec guidance and agent skills')
        .option('--workspace <name>', 'Workspace name from known local workspace views')
        .option('--tools <tools>', `Select agents for workspace skills. Use "all", "none", or a comma-separated list of: ${getWorkspaceSkillToolIds().join(', ')}. Global profile selects workflows; --tools selects agents.`)
        .option('--json', 'Output as JSON')
        .option('--no-interactive', 'Disable prompts')
        .action(async (name, options) => {
        await workspaceCommand.update(name, options);
    });
    workspace
        .command('open [name]')
        .description('Open a workspace in an agent or VS Code editor')
        .option('--workspace <name>', 'Workspace name from known local workspace views')
        .option('--initiative <id>', 'Open an initiative as a local workspace view')
        .option('--store <id>', 'Context store id for --initiative')
        .option('--store-path <path>', 'Existing local context store root for --initiative')
        .option('--agent <tool>', 'Use an agent for this session: codex-cli, claude, or github-copilot')
        .option('--editor', 'Open the workspace in VS Code editor mode')
        .option('--prepare-only', 'Unsupported: preview surfaces belong to a future context/query command')
        .option('--json', 'Output generated workspace view context as JSON after launch')
        .option('--change <id>', 'Unsupported: change-scoped open belongs to future workspace change planning')
        .option('--no-interactive', 'Disable prompts')
        .action(async (name, options) => {
        await workspaceCommand.open(name, options);
    });
    // Intentionally no public `workspace create` command in this slice.
}
//# sourceMappingURL=registration.js.map