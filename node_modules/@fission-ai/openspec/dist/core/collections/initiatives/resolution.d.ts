import { formatContextStoreSelector, type ContextStoreSelectorOptions, type ContextStoreSelectorSource, type SelectedContextStore } from '../../context-store/index.js';
import { type InitiativeState } from './schema.js';
export interface InitiativeSelectorOptions extends ContextStoreSelectorOptions {
    json?: boolean;
}
export type { ContextStoreSelectorSource, SelectedContextStore };
export { formatContextStoreSelector };
export interface InitiativeResolutionMatch {
    context_store: {
        id: string;
        root: string;
    };
    initiative: {
        id: string;
        title: string;
        root: string;
    };
}
export interface InitiativeResolutionDetails extends Record<string, unknown> {
    matches?: InitiativeResolutionMatch[];
}
export declare class InitiativeResolutionError extends Error {
    readonly code: string;
    readonly target?: string;
    readonly fix?: string;
    readonly details?: InitiativeResolutionDetails;
    constructor(message: string, code: string, options?: {
        target?: string;
        fix?: string;
        details?: InitiativeResolutionDetails;
    });
}
export interface InitiativeViewReference {
    store: string;
    storeSource: ContextStoreSelectorSource;
    storeRoot: string;
    id: string;
    title: string;
    summary: string;
    created: string;
    root: string;
    storePath: string;
    metadataPath: string;
}
export interface ListedInitiativeReference extends InitiativeViewReference {
    status: InitiativeState['status'];
    owners: InitiativeState['owners'];
    metadata: InitiativeState['metadata'];
}
export type InitiativeDiagnosticSeverity = 'error' | 'warning';
export interface InitiativeDiagnostic {
    severity: InitiativeDiagnosticSeverity;
    code: string;
    message: string;
    target?: string;
    fix?: string;
    details?: InitiativeResolutionDetails;
}
export interface ContextStoreInitiativeListReference {
    contextStore: SelectedContextStore;
    initiatives: ListedInitiativeReference[];
    status: InitiativeDiagnostic[];
}
export interface InitiativeListReferenceResult {
    contextStore: SelectedContextStore | null;
    contextStores: ContextStoreInitiativeListReference[];
    initiatives: ListedInitiativeReference[];
    status: InitiativeDiagnostic[];
}
export declare function initiativeDiagnosticFromError(error: unknown): InitiativeDiagnostic;
export declare function parseInitiativeReference(reference: string | undefined, options: InitiativeSelectorOptions): {
    initiativeId: string;
    options: InitiativeSelectorOptions;
};
export declare function resolveRegisteredInitiativeContextStore(storeId: string): Promise<SelectedContextStore>;
export declare function resolvePathInitiativeContextStore(storePath: string): Promise<SelectedContextStore>;
export declare function selectContextStoreForInitiative(options: InitiativeSelectorOptions, commandName: 'create' | 'list' | 'show'): Promise<SelectedContextStore>;
export declare function resolveSelectedInitiativeViewReference(selected: SelectedContextStore, initiativeId: string): Promise<InitiativeViewReference>;
export declare function listSelectedInitiativeViewReferences(selected: SelectedContextStore): Promise<ContextStoreInitiativeListReference>;
export declare function listInitiativeViewReferences(options?: InitiativeSelectorOptions): Promise<InitiativeListReferenceResult>;
export declare function resolveInitiativeViewReference(reference: string | undefined, options?: InitiativeSelectorOptions): Promise<InitiativeViewReference>;
export interface InitiativeLinkReference {
    store: string;
    id: string;
}
export declare function resolveInitiativeLinkReference(reference: string | undefined, options?: InitiativeSelectorOptions): Promise<InitiativeLinkReference>;
//# sourceMappingURL=resolution.d.ts.map