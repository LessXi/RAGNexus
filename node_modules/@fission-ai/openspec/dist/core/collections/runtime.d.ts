export type CollectionMetadata = Readonly<Record<string, unknown>>;
export type CollectionHooks = Readonly<Record<string, unknown>>;
export interface CollectionDefinition<THandle = unknown> {
    id: string;
    mount: string;
    metadata?: CollectionMetadata;
    hooks?: CollectionHooks;
    createHandle?: (context: MountedCollectionContext) => THandle;
}
export interface CollectionRegistry {
    list(): readonly CollectionDefinition[];
    get<THandle = unknown>(collectionId: string): CollectionDefinition<THandle> | undefined;
    require<THandle = unknown>(collectionId: string): CollectionDefinition<THandle>;
}
export interface MountedCollectionContext {
    storeRoot: string;
    collectionId: string;
    mount: string;
    mountRoot: string;
    resolvePath(relativePath?: string): string;
    toStorePath(relativePath?: string): string;
}
export interface MountedCollection<THandle = unknown> {
    collectionId: string;
    mount: string;
    mountRoot: string;
    context: MountedCollectionContext;
    handle: THandle | undefined;
    resolvePath(relativePath?: string): string;
    toStorePath(relativePath?: string): string;
}
export interface MountedCollectionRegistry {
    list(): readonly MountedCollection[];
    get<THandle = unknown>(collectionId: string): MountedCollection<THandle> | undefined;
    require<THandle = unknown>(collectionId: string): MountedCollection<THandle>;
}
export interface MountCollectionsInput {
    storeRoot: string;
    collections: CollectionRegistry;
}
export declare function validateCollectionId(id: string): string;
export declare function validateMount(mount: string): string;
export declare function parseCollectionPath(input?: string): string;
export declare function createCollectionRegistry(definitions: readonly CollectionDefinition[]): CollectionRegistry;
export declare function mountCollections(input: MountCollectionsInput): MountedCollectionRegistry;
//# sourceMappingURL=runtime.d.ts.map