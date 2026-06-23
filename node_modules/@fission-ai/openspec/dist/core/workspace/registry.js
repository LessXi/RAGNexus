import * as nodeFs from 'node:fs';
import { z } from 'zod';
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml';
import { getGlobalDataDir } from '../global-config.js';
import { FileSystemUtils } from '../../utils/file-system.js';
import { validateWorkspaceName } from './foundation.js';
import { isWorkspaceRoot, readWorkspaceViewState } from './state-io.js';
const fs = nodeFs.promises;
export const MANAGED_WORKSPACES_DIR_NAME = 'workspaces';
export const WORKSPACE_REGISTRY_FILE_NAME = 'registry.yaml';
function joinWorkspacePath(basePath, ...segments) {
    return FileSystemUtils.joinPath(basePath, ...segments);
}
async function pathIsFile(filePath) {
    try {
        return (await fs.stat(filePath)).isFile();
    }
    catch {
        return false;
    }
}
async function pathIsDirectory(dirPath) {
    try {
        return (await fs.stat(dirPath)).isDirectory();
    }
    catch {
        return false;
    }
}
function formatZodIssues(error) {
    return error.issues
        .map((issue) => {
        const location = issue.path.length > 0 ? issue.path.join('.') : 'root';
        return `${location}: ${issue.message}`;
    })
        .join('; ');
}
function parseYamlObject(content, label) {
    try {
        return parseYaml(content);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`Invalid ${label}: ${message}`);
    }
}
function assertValidMapKeys(keys, validator, label) {
    for (const key of keys) {
        try {
            validator(key);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            throw new Error(`Invalid ${label} '${key}': ${message}`);
        }
    }
}
const RegistryStateSchema = z.object({
    version: z.literal(1),
    workspaces: z.record(z.string(), z.string()),
}).strict();
export function getManagedWorkspacesDir(options = {}) {
    return joinWorkspacePath(options.globalDataDir ?? getGlobalDataDir(), MANAGED_WORKSPACES_DIR_NAME);
}
export function getManagedWorkspaceRoot(workspaceName, options = {}) {
    validateWorkspaceName(workspaceName);
    return joinWorkspacePath(getManagedWorkspacesDir(options), workspaceName);
}
export function getWorkspaceRegistryPath(options = {}) {
    return joinWorkspacePath(getManagedWorkspacesDir(options), WORKSPACE_REGISTRY_FILE_NAME);
}
export function parseWorkspaceRegistryState(content) {
    const raw = parseYamlObject(content, 'workspace registry state');
    const result = RegistryStateSchema.safeParse(raw);
    if (!result.success) {
        throw new Error(`Invalid workspace registry state: ${formatZodIssues(result.error)}`);
    }
    assertValidMapKeys(Object.keys(result.data.workspaces), validateWorkspaceName, 'workspace registry name');
    return {
        version: 1,
        workspaces: result.data.workspaces,
    };
}
export function serializeWorkspaceRegistryState(state) {
    assertValidMapKeys(Object.keys(state.workspaces), validateWorkspaceName, 'workspace registry name');
    for (const [workspaceName, workspaceRoot] of Object.entries(state.workspaces)) {
        if (typeof workspaceRoot !== 'string') {
            throw new Error(`Invalid workspace registry entry '${workspaceName}': path must be a string`);
        }
    }
    return stringifyYaml({
        version: 1,
        workspaces: state.workspaces,
    });
}
export function listWorkspaceRegistryEntries(registry) {
    return Object.entries(registry.workspaces)
        .map(([name, workspaceRoot]) => ({ name, workspaceRoot }))
        .sort((a, b) => a.name.localeCompare(b.name));
}
export async function listKnownWorkspaceEntries(options = {}) {
    const legacyRegistry = await readWorkspaceRegistryState(options);
    const workspaces = new Map(Object.entries(legacyRegistry?.workspaces ?? {}));
    for (const entry of await listManagedWorkspaceEntries(options)) {
        workspaces.set(entry.name, entry.workspaceRoot);
    }
    return [...workspaces.entries()]
        .map(([name, workspaceRoot]) => ({ name, workspaceRoot }))
        .sort((a, b) => a.name.localeCompare(b.name));
}
export async function listManagedWorkspaceEntries(options = {}) {
    const workspacesDir = getManagedWorkspacesDir(options);
    if (!(await pathIsDirectory(workspacesDir))) {
        return [];
    }
    const entries = await fs.readdir(workspacesDir, { withFileTypes: true });
    const workspaces = [];
    for (const entry of entries) {
        if (!entry.isDirectory()) {
            continue;
        }
        const workspaceRoot = FileSystemUtils.canonicalizeExistingPath(joinWorkspacePath(workspacesDir, entry.name));
        if (!(await isWorkspaceRoot(workspaceRoot))) {
            continue;
        }
        try {
            const state = await readWorkspaceViewState(workspaceRoot);
            workspaces.push({ name: state.name, workspaceRoot });
        }
        catch {
            workspaces.push({ name: entry.name, workspaceRoot });
        }
    }
    return workspaces.sort((a, b) => a.name.localeCompare(b.name));
}
export async function readWorkspaceRegistryState(options = {}) {
    const registryPath = getWorkspaceRegistryPath(options);
    if (!(await pathIsFile(registryPath))) {
        return null;
    }
    return parseWorkspaceRegistryState(await fs.readFile(registryPath, 'utf-8'));
}
export async function writeWorkspaceRegistryState(state, options = {}) {
    await FileSystemUtils.writeFile(getWorkspaceRegistryPath(options), serializeWorkspaceRegistryState(state));
}
//# sourceMappingURL=registry.js.map