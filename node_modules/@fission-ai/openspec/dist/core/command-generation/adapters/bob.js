/**
 * Bob Shell Command Adapter
 *
 * Formats commands for Bob Shell following its markdown specification.
 * Commands are stored in .bob/commands/ directory.
 */
import path from 'path';
import { transformToHyphenCommands } from '../../../utils/command-references.js';
/**
 * Escapes a string value for safe YAML output.
 * Quotes the string if it contains special YAML characters.
 */
function escapeYamlValue(value) {
    // Check if value needs quoting (contains special YAML characters or starts/ends with whitespace)
    const needsQuoting = /[:\n\r#{}[\],&*!|>'"%@`]|^\s|\s$/.test(value);
    if (needsQuoting) {
        // Use double quotes and escape internal double quotes and backslashes
        const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
        return `"${escaped}"`;
    }
    return value;
}
/**
 * Bob Shell adapter for command generation.
 * File path: .bob/commands/opsx-<id>.md
 * Frontmatter: description, argument-hint
 */
export const bobAdapter = {
    toolId: 'bob',
    getFilePath(commandId) {
        return path.join('.bob', 'commands', `opsx-${commandId}.md`);
    },
    formatFile(content) {
        // Transform command references from colon to hyphen format for Bob
        const transformedBody = transformToHyphenCommands(content.body);
        return `---
description: ${escapeYamlValue(content.description)}
argument-hint: command arguments
---

${transformedBody}
`;
    },
};
//# sourceMappingURL=bob.js.map