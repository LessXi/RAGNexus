import * as nodeFs from 'node:fs';
import type { MountedCollection } from '../runtime.js';
import { type InitiativeMetadata, type InitiativeState, type InitiativeStatus } from './schema.js';
import { type InitiativeTemplateFile } from './templates.js';
export interface InitiativeDirectoryEntry {
    name: string;
    isDirectory(): boolean;
}
export interface InitiativeOperationsFileSystem {
    mkdir(dirPath: string, options: {
        recursive?: boolean;
    }): Promise<void>;
    writeFile(filePath: string, content: string, options: {
        flag?: nodeFs.OpenMode;
    }): Promise<void>;
    readFile(filePath: string): Promise<string>;
    readdir(dirPath: string, options: {
        withFileTypes: true;
    }): Promise<readonly InitiativeDirectoryEntry[]>;
    rm(dirPath: string, options: {
        recursive?: boolean;
        force?: boolean;
    }): Promise<void>;
}
export interface InitiativeOperationDependencies {
    fileSystem?: InitiativeOperationsFileSystem;
}
export interface CreateInitiativeInput extends InitiativeOperationDependencies {
    collection: MountedCollection;
    id: string;
    title: string;
    summary: string;
    status?: InitiativeStatus;
    owners?: string[];
    metadata?: InitiativeMetadata;
    getCurrentDate?: () => string;
    buildTemplateFiles?: (state: InitiativeState) => readonly InitiativeTemplateFile[];
}
export interface ListInitiativesInput extends InitiativeOperationDependencies {
    collection: MountedCollection;
}
export interface ReadInitiativeInput extends InitiativeOperationDependencies {
    collection: MountedCollection;
    id: string;
}
export declare function createInitiative(input: CreateInitiativeInput): Promise<InitiativeState>;
export declare function readInitiative(input: ReadInitiativeInput): Promise<InitiativeState | null>;
export declare function listInitiatives(input: ListInitiativesInput): Promise<InitiativeState[]>;
//# sourceMappingURL=operations.d.ts.map