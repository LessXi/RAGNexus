import { getContextStoreMetadataPath, readOptionalContextStoreMetadataState, resolveGitContextStoreBackendConfig, validateContextStoreId, } from './foundation.js';
import { ContextStoreError } from './errors.js';
import { resolveRegisteredContextStore, } from './registry.js';
export function createRegisteredContextStoreBinding(id) {
    const validatedId = validateContextStoreId(id);
    return {
        id: validatedId,
        selector: {
            kind: 'registry',
            id: validatedId,
        },
    };
}
export function createPathContextStoreBinding(input) {
    const id = validateContextStoreId(input.id);
    if (input.path.length === 0) {
        throw new Error('Context store binding path must not be empty.');
    }
    return {
        id,
        selector: {
            kind: 'path',
            path: input.path,
            observed_id: id,
        },
    };
}
export function normalizeContextStoreBinding(binding) {
    const id = validateContextStoreId(binding.id);
    if (binding.selector.kind === 'registry') {
        return createRegisteredContextStoreBinding(binding.selector.id);
    }
    if (binding.selector.path.length === 0) {
        throw new Error('Context store binding path must not be empty.');
    }
    return {
        id,
        selector: {
            kind: 'path',
            path: binding.selector.path,
            ...(binding.selector.observed_id
                ? { observed_id: validateContextStoreId(binding.selector.observed_id) }
                : {}),
        },
    };
}
export function sameContextStoreBinding(left, right) {
    const normalizedLeft = normalizeContextStoreBinding(left);
    const normalizedRight = normalizeContextStoreBinding(right);
    if (normalizedLeft.selector.kind !== normalizedRight.selector.kind) {
        return false;
    }
    if (normalizedLeft.selector.kind === 'registry' &&
        normalizedRight.selector.kind === 'registry') {
        return normalizedLeft.selector.id === normalizedRight.selector.id;
    }
    if (normalizedLeft.selector.kind === 'path' &&
        normalizedRight.selector.kind === 'path') {
        return normalizedLeft.selector.path === normalizedRight.selector.path;
    }
    return false;
}
export function formatContextStoreBinding(binding) {
    const normalized = normalizeContextStoreBinding(binding);
    if (normalized.selector.kind === 'registry') {
        return normalized.selector.id;
    }
    return `${normalized.id} via ${normalized.selector.path}`;
}
export function formatContextStoreBindingSelector(binding) {
    const normalized = normalizeContextStoreBinding(binding);
    return normalized.selector.kind === 'registry'
        ? `--store ${normalized.selector.id}`
        : `--store-path ${normalized.selector.path}`;
}
export function formatContextStoreSelector(selected) {
    return selected.source === 'registry'
        ? `--store ${selected.id}`
        : `--store-path ${selected.root}`;
}
export function createContextStoreBindingFromSelected(selected) {
    return selected.source === 'registry'
        ? createRegisteredContextStoreBinding(selected.id)
        : createPathContextStoreBinding({
            id: selected.id,
            path: selected.root,
        });
}
function validateSelectorConflict(options, commandName) {
    if (options.store !== undefined && options.storePath !== undefined) {
        throw new ContextStoreError('Pass either --store <id> or --store-path <path>, not both.', 'context_store_selector_conflict', {
            target: 'context_store',
            fix: `openspec ${commandName} --store <id>`,
        });
    }
}
export function requireContextStoreSelector(options, commandName) {
    validateSelectorConflict(options, commandName);
    if (options.store === undefined && options.storePath === undefined) {
        throw new ContextStoreError('Pass --store <id> or --store-path <path>.', 'context_store_required', {
            target: 'context_store',
            fix: `openspec ${commandName} --store <id>`,
        });
    }
}
export async function resolveSelectedContextStore(options, commandName, pathOptions = {}) {
    requireContextStoreSelector(options, commandName);
    if (options.store !== undefined) {
        const resolved = await resolveRegisteredContextStore({
            id: options.store,
            globalDataDir: pathOptions.globalDataDir,
        });
        return {
            id: resolved.id,
            root: resolved.storeRoot,
            source: 'registry',
        };
    }
    const storePath = options.storePath ?? '';
    let root;
    try {
        const backend = await resolveGitContextStoreBackendConfig({
            localPath: storePath,
        });
        root = backend.local_path;
    }
    catch (error) {
        throw new ContextStoreError(error instanceof Error ? error.message : String(error), 'invalid_context_store_path', {
            target: 'context_store.path',
            fix: 'Pass an existing context store root.',
        });
    }
    let metadata;
    try {
        metadata = await readOptionalContextStoreMetadataState(root);
    }
    catch (error) {
        throw new ContextStoreError(error instanceof Error ? error.message : String(error), 'invalid_context_store_metadata', {
            target: 'context_store.metadata',
            fix: `Fix ${getContextStoreMetadataPath(root)} before using this store.`,
        });
    }
    if (!metadata) {
        throw new ContextStoreError(`Context store metadata not found at ${getContextStoreMetadataPath(root)}`, 'context_store_metadata_not_found', {
            target: 'context_store.metadata',
            fix: 'Pass a context store root that contains .openspec-store/store.yaml.',
        });
    }
    return {
        id: metadata.id,
        root,
        source: 'path',
    };
}
export async function resolveContextStoreBinding(binding, options = {}) {
    const normalized = normalizeContextStoreBinding(binding);
    if (normalized.selector.kind === 'registry') {
        const registered = await resolveRegisteredContextStore({
            id: normalized.selector.id,
            globalDataDir: options.globalDataDir,
        });
        return {
            binding: normalized,
            id: registered.id,
            root: registered.storeRoot,
            source: 'registry',
            registered,
            warnings: [],
        };
    }
    const backend = await resolveGitContextStoreBackendConfig({
        localPath: normalized.selector.path,
    });
    const root = backend.local_path;
    const metadata = await readOptionalContextStoreMetadataState(root);
    if (!metadata) {
        throw new Error(`Context store metadata not found at ${getContextStoreMetadataPath(root)}`);
    }
    const warnings = [];
    const observedId = normalized.selector.observed_id ?? normalized.id;
    if (metadata.id !== observedId) {
        warnings.push({
            code: 'context_store_binding_id_changed',
            message: `Context store at ${root} now reports id '${metadata.id}' instead of '${observedId}'.`,
            target: 'metadata.id',
            fix: `Review ${getContextStoreMetadataPath(root)} or re-open the workspace with the intended context store.`,
        });
    }
    return {
        binding: normalized,
        id: metadata.id,
        root,
        source: 'path',
        warnings,
    };
}
//# sourceMappingURL=binding.js.map