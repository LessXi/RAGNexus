import { Command } from 'commander';
import { type InitiativeResolutionDetails, type InitiativeDiagnostic } from '../core/collections/initiatives/index.js';
export declare class InitiativeCliError extends Error {
    readonly diagnostic: InitiativeDiagnostic;
    constructor(message: string, code: string, options?: {
        target?: string;
        fix?: string;
        details?: InitiativeResolutionDetails;
    });
}
export declare function initiativeDiagnosticFromError(error: unknown): InitiativeDiagnostic;
export declare function registerInitiativeCommand(program: Command): void;
//# sourceMappingURL=initiative.d.ts.map