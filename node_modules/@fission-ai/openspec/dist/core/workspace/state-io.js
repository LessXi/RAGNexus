import * as nodeFs from 'node:fs';
import * as path from 'node:path';
import { FileSystemUtils } from '../../utils/file-system.js';
import { getWorkspaceChangesDir, getWorkspaceMetadataDir, getWorkspaceViewStatePath, parseWorkspaceViewState, serializeWorkspaceViewState, } from './foundation.js';
import { getWorkspaceLegacyLocalStatePath, getWorkspaceLegacySharedStatePath, parseWorkspaceLocalState, parseWorkspaceSharedState, workspaceStatePartsToViewState, } from './legacy-state.js';
const fs = nodeFs.promises;
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
function pathExistsAsFile(filePath) {
    try {
        return nodeFs.statSync(filePath).isFile();
    }
    catch {
        return false;
    }
}
function isFileNotFoundError(error) {
    return (typeof error === 'object' &&
        error !== null &&
        'code' in error &&
        error.code === 'ENOENT');
}
async function getSearchStartDirectory(startPath) {
    const resolvedStart = path.resolve(startPath);
    try {
        const stats = await fs.stat(resolvedStart);
        const searchStart = stats.isDirectory() ? resolvedStart : path.dirname(resolvedStart);
        return FileSystemUtils.canonicalizeExistingPath(searchStart);
    }
    catch {
        return resolvedStart;
    }
}
export async function isWorkspaceRoot(candidateRoot) {
    return ((await pathIsFile(getWorkspaceViewStatePath(candidateRoot))) ||
        (await pathIsFile(getWorkspaceLegacySharedStatePath(candidateRoot))));
}
export async function findWorkspaceRoot(startPath = process.cwd()) {
    let currentDir = await getSearchStartDirectory(startPath);
    while (true) {
        if (await isWorkspaceRoot(currentDir)) {
            return FileSystemUtils.canonicalizeExistingPath(currentDir);
        }
        const parentDir = path.dirname(currentDir);
        if (parentDir === currentDir) {
            return null;
        }
        currentDir = parentDir;
    }
}
export function workspaceStateFileExistsSync(workspaceRoot) {
    return (pathExistsAsFile(getWorkspaceViewStatePath(workspaceRoot)) ||
        pathExistsAsFile(getWorkspaceLegacySharedStatePath(workspaceRoot)));
}
export async function readWorkspaceViewState(workspaceRoot) {
    const viewStatePath = getWorkspaceViewStatePath(workspaceRoot);
    if (await pathIsFile(viewStatePath)) {
        return parseWorkspaceViewState(await fs.readFile(viewStatePath, 'utf-8'));
    }
    const legacySharedState = parseWorkspaceSharedState(await fs.readFile(getWorkspaceLegacySharedStatePath(workspaceRoot), 'utf-8'));
    let legacyLocalState = null;
    try {
        legacyLocalState = parseWorkspaceLocalState(await fs.readFile(getWorkspaceLegacyLocalStatePath(workspaceRoot), 'utf-8'));
    }
    catch (error) {
        if (!isFileNotFoundError(error)) {
            throw error;
        }
    }
    return workspaceStatePartsToViewState(legacySharedState, legacyLocalState);
}
export function readWorkspaceViewStateSync(workspaceRoot) {
    const viewStatePath = getWorkspaceViewStatePath(workspaceRoot);
    if (pathExistsAsFile(viewStatePath)) {
        return parseWorkspaceViewState(nodeFs.readFileSync(viewStatePath, 'utf-8'));
    }
    const legacySharedPath = getWorkspaceLegacySharedStatePath(workspaceRoot);
    if (!pathExistsAsFile(legacySharedPath)) {
        return null;
    }
    const legacySharedState = parseWorkspaceSharedState(nodeFs.readFileSync(legacySharedPath, 'utf-8'));
    const legacyLocalPath = getWorkspaceLegacyLocalStatePath(workspaceRoot);
    const legacyLocalState = pathExistsAsFile(legacyLocalPath)
        ? parseWorkspaceLocalState(nodeFs.readFileSync(legacyLocalPath, 'utf-8'))
        : null;
    return workspaceStatePartsToViewState(legacySharedState, legacyLocalState);
}
export async function readOptionalWorkspaceViewState(workspaceRoot) {
    try {
        return await readWorkspaceViewState(workspaceRoot);
    }
    catch (error) {
        if (isFileNotFoundError(error)) {
            return null;
        }
        throw error;
    }
}
export async function writeWorkspaceViewState(workspaceRoot, state) {
    const content = serializeWorkspaceViewState(state);
    await FileSystemUtils.createDirectory(getWorkspaceMetadataDir(workspaceRoot));
    await FileSystemUtils.writeFile(getWorkspaceViewStatePath(workspaceRoot), content);
}
export async function workspaceChangesDirExists(workspaceRoot) {
    return pathIsDirectory(getWorkspaceChangesDir(workspaceRoot));
}
//# sourceMappingURL=state-io.js.map