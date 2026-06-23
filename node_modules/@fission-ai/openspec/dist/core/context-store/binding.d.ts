import { type ContextStorePathOptions } from './foundation.js';
import { type ResolvedContextStore } from './registry.js';
export type ContextStoreSelector = {
    kind: 'registry';
    id: string;
} | {
    kind: 'path';
    path: string;
    observed_id?: string;
};
export type ContextStoreSelectorSource = 'registry' | 'path';
export interface ContextStoreSelectorOptions {
    store?: string;
    storePath?: string;
}
export interface SelectedContextStore {
    id: string;
    root: string;
    source: ContextStoreSelectorSource;
}
export interface ContextStoreBinding {
    id: string;
    selector: ContextStoreSelector;
}
export interface ContextStoreBindingWarning {
    code: string;
    message: string;
    target?: string;
    fix?: string;
}
export interface ResolvedContextStoreBinding {
    binding: ContextStoreBinding;
    id: string;
    root: string;
    source: 'registry' | 'path';
    registered?: ResolvedContextStore;
    warnings: ContextStoreBindingWarning[];
}
export declare function createRegisteredContextStoreBinding(id: string): ContextStoreBinding;
export declare function createPathContextStoreBinding(input: {
    id: string;
    path: string;
}): ContextStoreBinding;
export declare function normalizeContextStoreBinding(binding: ContextStoreBinding): ContextStoreBinding;
export declare function sameContextStoreBinding(left: ContextStoreBinding, right: ContextStoreBinding): boolean;
export declare function formatContextStoreBinding(binding: ContextStoreBinding): string;
export declare function formatContextStoreBindingSelector(binding: ContextStoreBinding): string;
export declare function formatContextStoreSelector(selected: SelectedContextStore): string;
export declare function createContextStoreBindingFromSelected(selected: SelectedContextStore): ContextStoreBinding;
export declare function requireContextStoreSelector(options: ContextStoreSelectorOptions, commandName: string): void;
export declare function resolveSelectedContextStore(options: ContextStoreSelectorOptions, commandName: string, pathOptions?: ContextStorePathOptions): Promise<SelectedContextStore>;
export declare function resolveContextStoreBinding(binding: ContextStoreBinding, options?: ContextStorePathOptions): Promise<ResolvedContextStoreBinding>;
//# sourceMappingURL=binding.d.ts.map