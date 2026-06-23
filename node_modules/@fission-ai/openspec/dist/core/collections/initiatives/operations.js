import * as nodeFs from 'node:fs';
import { INITIATIVE_COLLECTION_ID, INITIATIVE_FILE_NAME, parseInitiativeState, serializeInitiativeState, validateInitiativeId, } from './schema.js';
import { buildDefaultInitiativeFiles, } from './templates.js';
const fs = nodeFs.promises;
const nodeFileSystem = {
    async mkdir(dirPath, options) {
        await fs.mkdir(dirPath, options);
    },
    async writeFile(filePath, content, options) {
        await fs.writeFile(filePath, content, {
            encoding: 'utf-8',
            flag: options.flag ?? 'w',
        });
    },
    async readFile(filePath) {
        return fs.readFile(filePath, 'utf-8');
    },
    async readdir(dirPath, options) {
        return fs.readdir(dirPath, options);
    },
    async rm(dirPath, options) {
        await fs.rm(dirPath, options);
    },
};
function getCurrentDate() {
    return new Date().toISOString().split('T')[0];
}
function getFileSystem(fileSystem) {
    return fileSystem ?? nodeFileSystem;
}
function isFileNotFoundError(error) {
    return (typeof error === 'object' &&
        error !== null &&
        'code' in error &&
        error.code === 'ENOENT');
}
function isPathExistsError(error) {
    return (typeof error === 'object' &&
        error !== null &&
        'code' in error &&
        error.code === 'EEXIST');
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function assertInitiativesCollection(collection) {
    if (collection.collectionId !== INITIATIVE_COLLECTION_ID) {
        throw new Error(`Expected mounted '${INITIATIVE_COLLECTION_ID}' collection, got '${collection.collectionId}'`);
    }
}
function resolveInitiativeFilePath(collection, initiativeId, fileName) {
    return collection.resolvePath(`${initiativeId}/${fileName}`);
}
function normalizeCreateState(input) {
    return parseInitiativeState(serializeInitiativeState({
        version: 1,
        id: validateInitiativeId(input.id),
        title: input.title,
        summary: input.summary,
        status: input.status ?? 'exploring',
        created: (input.getCurrentDate ?? getCurrentDate)(),
        owners: input.owners ?? [],
        metadata: input.metadata ?? {},
    }));
}
async function writeExclusiveFile(fileSystem, filePath, content) {
    await fileSystem.writeFile(filePath, content, { flag: 'wx' });
}
async function cleanupCreatedInitiative(fileSystem, initiativeRoot, originalError, initiativeId) {
    try {
        await fileSystem.rm(initiativeRoot, { recursive: true, force: true });
    }
    catch (cleanupError) {
        throw new Error(`Failed to create initiative '${initiativeId}' and cleanup failed: ${errorMessage(originalError)}; cleanup: ${errorMessage(cleanupError)}`);
    }
    throw new Error(`Failed to create initiative '${initiativeId}': ${errorMessage(originalError)}`);
}
export async function createInitiative(input) {
    assertInitiativesCollection(input.collection);
    const state = normalizeCreateState(input);
    const fileSystem = getFileSystem(input.fileSystem);
    const initiativeRoot = input.collection.resolvePath(state.id);
    const buildTemplateFiles = input.buildTemplateFiles ?? buildDefaultInitiativeFiles;
    try {
        await fileSystem.mkdir(input.collection.resolvePath(), { recursive: true });
        await fileSystem.mkdir(initiativeRoot, { recursive: false });
    }
    catch (error) {
        if (isPathExistsError(error)) {
            throw new Error(`Initiative '${state.id}' already exists at ${initiativeRoot}`);
        }
        throw new Error(`Failed to create initiative '${state.id}': ${errorMessage(error)}`);
    }
    try {
        await writeExclusiveFile(fileSystem, resolveInitiativeFilePath(input.collection, state.id, INITIATIVE_FILE_NAME), serializeInitiativeState(state));
        for (const templateFile of buildTemplateFiles(state)) {
            await writeExclusiveFile(fileSystem, resolveInitiativeFilePath(input.collection, state.id, templateFile.fileName), templateFile.content);
        }
    }
    catch (error) {
        await cleanupCreatedInitiative(fileSystem, initiativeRoot, error, state.id);
    }
    return state;
}
export async function readInitiative(input) {
    assertInitiativesCollection(input.collection);
    const initiativeId = validateInitiativeId(input.id);
    const fileSystem = getFileSystem(input.fileSystem);
    const initiativeFilePath = resolveInitiativeFilePath(input.collection, initiativeId, INITIATIVE_FILE_NAME);
    let content;
    try {
        content = await fileSystem.readFile(initiativeFilePath);
    }
    catch (error) {
        if (isFileNotFoundError(error)) {
            return null;
        }
        throw new Error(`Invalid initiative '${initiativeId}': failed to read ${INITIATIVE_FILE_NAME}: ${errorMessage(error)}`);
    }
    let state;
    try {
        state = parseInitiativeState(content);
    }
    catch (error) {
        throw new Error(`Invalid initiative '${initiativeId}': ${errorMessage(error)}`);
    }
    if (state.id !== initiativeId) {
        throw new Error(`Invalid initiative '${initiativeId}': ${INITIATIVE_FILE_NAME} id '${state.id}' must match folder name`);
    }
    return state;
}
export async function listInitiatives(input) {
    assertInitiativesCollection(input.collection);
    const fileSystem = getFileSystem(input.fileSystem);
    let entries;
    try {
        entries = await fileSystem.readdir(input.collection.resolvePath(), { withFileTypes: true });
    }
    catch (error) {
        if (isFileNotFoundError(error)) {
            return [];
        }
        throw new Error(`Failed to list initiatives: ${errorMessage(error)}`);
    }
    const initiatives = [];
    for (const entry of entries) {
        if (!entry.isDirectory()) {
            continue;
        }
        const initiativeFilePath = resolveInitiativeFilePath(input.collection, entry.name, INITIATIVE_FILE_NAME);
        let content;
        try {
            content = await fileSystem.readFile(initiativeFilePath);
        }
        catch (error) {
            if (isFileNotFoundError(error)) {
                continue;
            }
            throw new Error(`Invalid initiative '${entry.name}': failed to read ${INITIATIVE_FILE_NAME}: ${errorMessage(error)}`);
        }
        let state;
        try {
            state = parseInitiativeState(content);
        }
        catch (error) {
            throw new Error(`Invalid initiative '${entry.name}': ${errorMessage(error)}`);
        }
        if (state.id !== entry.name) {
            throw new Error(`Invalid initiative '${entry.name}': ${INITIATIVE_FILE_NAME} id '${state.id}' must match folder name`);
        }
        initiatives.push(state);
    }
    return initiatives.sort((a, b) => a.id.localeCompare(b.id));
}
//# sourceMappingURL=operations.js.map