import { createCollectionRegistry, mountCollections, } from '../runtime.js';
import { INITIATIVE_COLLECTION_ID } from './schema.js';
export function createInitiativesCollectionRegistry() {
    return createCollectionRegistry([
        {
            id: INITIATIVE_COLLECTION_ID,
            mount: INITIATIVE_COLLECTION_ID,
        },
    ]);
}
export function mountInitiativesCollection(storeRoot) {
    return mountCollections({
        storeRoot,
        collections: createInitiativesCollectionRegistry(),
    }).require(INITIATIVE_COLLECTION_ID);
}
//# sourceMappingURL=collection.js.map