import * as os from 'node:os';
import * as path from 'node:path';
import { ContextStoreError, doctorContextStores, getDefaultContextStoreRoot, listContextStores, prepareContextStoreSetup, prepareContextStoreCleanup, registerExistingContextStore, removeContextStore, setupPreparedContextStore, unregisterContextStore, validateContextStoreId, } from '../core/context-store/index.js';
import { isInteractive } from '../utils/interactive.js';
function printJson(payload) {
    console.log(JSON.stringify(payload, null, 2));
}
function asErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function appendStatus(payload, status) {
    return {
        ...payload,
        status: [...payload.status, status],
    };
}
function toStoreOutput(store) {
    return {
        id: store.id,
        root: store.root,
        ...(store.metadataPath ? { metadata_path: store.metadataPath } : {}),
    };
}
function toMutationOutput(result) {
    return {
        context_store: toStoreOutput(result.store),
        registry: {
            path: result.registryCommit.path,
            registered: true,
        },
        git: {
            is_repository: result.git.isRepository,
            initialized: result.git.initialized,
        },
        created_files: result.createdArtifacts,
        status: [],
    };
}
function toCleanupOutput(result) {
    return {
        context_store: toStoreOutput(result.store),
        registry: {
            path: result.registryCommit.path,
            removed: result.registryCommit.removed,
        },
        files: {
            deleted: result.files.deleted,
            deleted_path: result.files.deletedPath ?? null,
            left_on_disk: result.files.leftOnDisk ?? null,
        },
        status: result.diagnostics,
    };
}
function toListOutput(result) {
    return {
        context_stores: result.stores.map(toStoreOutput),
        status: [],
    };
}
function toDoctorStoreOutput(store) {
    return {
        ...toStoreOutput(store),
        metadata: store.metadata,
        git: {
            is_repository: store.git.isRepository,
        },
        status: store.diagnostics,
    };
}
function toDoctorOutput(result) {
    return {
        context_stores: result.stores.map(toDoctorStoreOutput),
        status: result.diagnostics,
    };
}
function asStatus(error) {
    if (error instanceof ContextStoreError) {
        return error.diagnostic;
    }
    const message = asErrorMessage(error);
    return {
        severity: 'error',
        code: 'context_store_error',
        message,
    };
}
function isPromptCancellationError(error) {
    return (error instanceof Error &&
        (error.name === 'ExitPromptError' || error.message.includes('force closed the prompt with SIGINT')));
}
async function shouldInitializeGit(options) {
    if (options.initGit !== undefined) {
        return options.initGit;
    }
    if (options.json || !isInteractive()) {
        return false;
    }
    const { confirm } = await import('@inquirer/prompts');
    return confirm({
        message: 'Initialize Git in this context store?',
        default: true,
    });
}
function formatPathForHuman(targetPath) {
    const home = os.homedir();
    const normalizedHome = path.resolve(home);
    const normalizedTarget = path.resolve(targetPath);
    if (normalizedTarget === normalizedHome)
        return '~';
    if (normalizedTarget.startsWith(`${normalizedHome}${path.sep}`)) {
        return `~${path.sep}${path.relative(normalizedHome, normalizedTarget)}`;
    }
    return targetPath;
}
async function promptContextStoreId() {
    const { input } = await import('@inquirer/prompts');
    return input({
        message: 'Context store name',
        required: true,
        validate(value) {
            try {
                validateContextStoreId(value);
                return true;
            }
            catch (error) {
                return asErrorMessage(error);
            }
        },
    });
}
async function promptContextStorePath(id) {
    const { input } = await import('@inquirer/prompts');
    const defaultPath = getDefaultContextStoreRoot(id);
    return input({
        message: 'Where should this context store live?',
        default: defaultPath,
        prefill: 'editable',
        required: true,
    });
}
function isSetupInsideGitRepositoryError(error) {
    return (error instanceof ContextStoreError &&
        error.diagnostic.code === 'context_store_setup_inside_git_repo');
}
async function resolveSetupInput(id, options) {
    const interactive = !options.json && isInteractive();
    if (!id && !interactive) {
        throw new ContextStoreError('Pass a context store name.', 'context_store_setup_id_required', {
            target: 'context_store.id',
            fix: 'openspec context-store setup <id> --path /path/to/context-store --json',
        });
    }
    const resolvedId = id ? validateContextStoreId(id) : await promptContextStoreId();
    const promptedPath = !id && options.path === undefined
        ? await promptContextStorePath(resolvedId)
        : undefined;
    return {
        id: resolvedId,
        path: options.path ?? promptedPath,
    };
}
async function prepareSetupInput(input, options) {
    try {
        return await prepareContextStoreSetup(input);
    }
    catch (error) {
        if (!isSetupInsideGitRepositoryError(error) || options.json || !isInteractive()) {
            throw error;
        }
        const { confirm } = await import('@inquirer/prompts');
        const shouldContinue = await confirm({
            message: `${asErrorMessage(error)}. Use this location anyway?`,
            default: false,
        });
        if (!shouldContinue) {
            throw new ContextStoreError('Context store setup cancelled.', 'context_store_setup_cancelled', {
                target: 'context_store.root',
                fix: 'Choose another path or rerun setup later.',
            });
        }
        return prepareContextStoreSetup({
            ...input,
            allowInsideGitRepository: true,
        });
    }
}
async function confirmSetup(prepared, initGit) {
    const { confirm } = await import('@inquirer/prompts');
    console.log('');
    console.log('OpenSpec will create:');
    console.log('');
    console.log(`  Context store: ${prepared.id}`);
    console.log(`  Location: ${formatPathForHuman(prepared.root)}`);
    console.log(`  Git: ${initGit ? 'initialized' : 'not initialized'}`);
    console.log('');
    const confirmed = await confirm({
        message: 'Create this context store?',
        default: true,
    });
    if (!confirmed) {
        throw new ContextStoreError('Context store setup cancelled.', 'context_store_setup_cancelled', {
            target: 'context_store.root',
            fix: 'Rerun setup when you are ready.',
        });
    }
}
async function confirmRemove(id, root, options) {
    if (options.yes)
        return;
    if (options.json || !isInteractive()) {
        throw new ContextStoreError('Pass --yes to delete context-store files non-interactively.', 'context_store_remove_confirmation_required', {
            target: 'context_store.root',
            fix: `openspec context-store remove ${id} --yes`,
        });
    }
    const { confirm } = await import('@inquirer/prompts');
    const confirmed = await confirm({
        message: `Delete local context-store folder ${formatPathForHuman(root)}?`,
        default: false,
    });
    if (!confirmed) {
        throw new ContextStoreError('Context store remove cancelled.', 'context_store_remove_cancelled', {
            target: 'context_store.root',
            fix: 'Run context-store unregister if you only want to forget the local registration.',
        });
    }
}
function printMutationHuman(title, payload) {
    if (!payload.context_store || !payload.registry || !payload.git) {
        return;
    }
    console.log(`${title}: ${payload.context_store.id}`);
    console.log(`Location: ${formatPathForHuman(payload.context_store.root)}`);
    console.log('');
    console.log(`Next: ask your agent to create an initiative in ${payload.context_store.id}.`);
}
function printCleanupHuman(title, payload) {
    if (!payload.context_store || !payload.registry || !payload.files) {
        return;
    }
    console.log(`${title}: ${payload.context_store.id}`);
    if (payload.files.deleted_path) {
        console.log(`Deleted: ${formatPathForHuman(payload.files.deleted_path)}`);
    }
    else if (payload.files.left_on_disk) {
        console.log(`Files kept at: ${formatPathForHuman(payload.files.left_on_disk)}`);
    }
    else if (!payload.files.deleted) {
        console.log(`Files were already missing: ${formatPathForHuman(payload.context_store.root)}`);
    }
    for (const status of payload.status) {
        console.log(`${status.severity === 'warning' ? 'Note' : 'Issue'}: ${status.message}`);
    }
}
function printListHuman(payload) {
    if (payload.context_stores.length === 0) {
        console.log('No context stores registered.');
        console.log('');
        console.log('Next:');
        console.log('  openspec context-store setup team-context');
        console.log('  openspec context-store register /path/to/context-store');
        return;
    }
    console.log(`OpenSpec context stores (${payload.context_stores.length})`);
    console.log('');
    console.log(`${'ID'.padEnd(16)}Location`);
    for (const store of payload.context_stores) {
        console.log(`${store.id.padEnd(16)}${store.root}`);
    }
}
function formatMetadataHuman(store) {
    if (store.metadata.valid)
        return 'ok';
    if (store.metadata.present === false)
        return 'missing';
    if (store.metadata.present === null)
        return 'unknown';
    return 'invalid';
}
function formatDoctorGitHuman(store) {
    if (store.git.is_repository === null)
        return 'unknown';
    return store.git.is_repository ? 'repository detected' : 'not detected';
}
function printDoctorHuman(payload) {
    if (payload.context_stores.length === 0) {
        console.log('No context stores registered.');
        return;
    }
    console.log('Context store doctor');
    for (const store of payload.context_stores) {
        console.log('');
        console.log(store.id);
        console.log(`  Location: ${store.root}`);
        console.log(`  Metadata: ${formatMetadataHuman(store)}`);
        console.log(`  Git: ${formatDoctorGitHuman(store)}`);
        if (store.status.length === 0) {
            console.log('  Issues: none');
            continue;
        }
        console.log('  Issues:');
        for (const status of store.status) {
            console.log(`    - ${status.message}`);
            if (status.fix) {
                console.log(`      Fix: ${status.fix}`);
            }
        }
    }
}
class ContextStoreCommand {
    async setup(id, options = {}) {
        try {
            const setupInput = await resolveSetupInput(id, options);
            const prepared = await prepareSetupInput(setupInput, options);
            const initGit = await shouldInitializeGit(options);
            if (!options.json && isInteractive()) {
                await confirmSetup(prepared, initGit);
            }
            const payload = toMutationOutput(await setupPreparedContextStore(prepared, {
                initGit,
            }));
            if (options.json) {
                printJson(payload);
                return;
            }
            printMutationHuman('Context store ready', payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_store: null, registry: null, git: null, created_files: [], status: [] }, error);
        }
    }
    async register(inputPath, options = {}) {
        try {
            const payload = toMutationOutput(await registerExistingContextStore({
                path: inputPath,
                id: options.id,
            }));
            if (options.json) {
                printJson(payload);
                return;
            }
            printMutationHuman('Context store registered', payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_store: null, registry: null, git: null, created_files: [], status: [] }, error);
        }
    }
    async unregister(id, options = {}) {
        try {
            const payload = toCleanupOutput(await unregisterContextStore({ id }));
            if (options.json) {
                printJson(payload);
                return;
            }
            printCleanupHuman('Unregistered context store', payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_store: null, registry: null, files: null, status: [] }, error);
        }
    }
    async remove(id, options = {}) {
        try {
            const target = await prepareContextStoreCleanup({ id });
            await confirmRemove(target.id, target.root, options);
            const payload = toCleanupOutput(await removeContextStore(target));
            if (options.json) {
                printJson(payload);
                return;
            }
            printCleanupHuman('Removed context store', payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_store: null, registry: null, files: null, status: [] }, error);
        }
    }
    async list(options = {}) {
        try {
            const payload = toListOutput(await listContextStores());
            if (options.json) {
                printJson(payload);
                return;
            }
            printListHuman(payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_stores: [], status: [] }, error);
        }
    }
    async doctor(id, options = {}) {
        try {
            const payload = toDoctorOutput(await doctorContextStores(id));
            if (options.json) {
                printJson(payload);
                return;
            }
            printDoctorHuman(payload);
        }
        catch (error) {
            this.handleFailure(options.json, { context_stores: [], status: [] }, error);
        }
    }
    handleFailure(json, payload, error) {
        if (!json && isPromptCancellationError(error)) {
            console.error('Cancelled.');
            process.exitCode = 130;
            return;
        }
        const status = asStatus(error);
        if (json) {
            printJson(appendStatus(payload, status));
            process.exitCode = 1;
            return;
        }
        console.error(`Error: ${status.message}`);
        if (status.fix) {
            console.error(`Fix: ${status.fix}`);
        }
        process.exitCode = 1;
    }
}
export function registerContextStoreCommand(program) {
    const contextStoreCommand = new ContextStoreCommand();
    const contextStore = program
        .command('context-store')
        .description('Set up and inspect local context stores');
    contextStore
        .command('setup [id]')
        .description('Create and register a local context store')
        .option('--path <path>', 'Context store folder path; defaults to OpenSpec managed local data')
        .option('--init-git', 'Initialize a Git repository in the context store')
        .option('--no-init-git', 'Do not initialize a Git repository')
        .option('--json', 'Output as JSON')
        .action(async (id, options) => {
        await contextStoreCommand.setup(id, options);
    });
    contextStore
        .command('register [path]')
        .description('Register an existing local context store')
        .option('--id <id>', 'Context store id; defaults to metadata or folder name')
        .option('--json', 'Output as JSON')
        .action(async (inputPath, options) => {
        await contextStoreCommand.register(inputPath, options);
    });
    contextStore
        .command('unregister <id>')
        .description('Forget a local context-store registration without deleting files')
        .option('--json', 'Output as JSON')
        .action(async (id, options) => {
        await contextStoreCommand.unregister(id, options);
    });
    contextStore
        .command('remove <id>')
        .description('Forget a local context-store registration and delete its local folder')
        .option('--yes', 'Confirm local context-store folder deletion')
        .option('--json', 'Output as JSON')
        .action(async (id, options) => {
        await contextStoreCommand.remove(id, options);
    });
    contextStore
        .command('list')
        .alias('ls')
        .description('List locally registered context stores')
        .option('--json', 'Output as JSON')
        .action(async (options) => {
        await contextStoreCommand.list(options);
    });
    contextStore
        .command('doctor [id]')
        .description('Check local context-store registration and metadata')
        .option('--json', 'Output as JSON')
        .action(async (id, options) => {
        await contextStoreCommand.doctor(id, options);
    });
}
//# sourceMappingURL=context-store.js.map