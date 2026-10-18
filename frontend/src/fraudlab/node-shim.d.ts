// Minimal typings for the few Node APIs facts.test.ts uses to read the research files. The project has no @types/node.
declare module 'node:fs' { export function readFileSync(path: string, encoding: 'utf8'): string; export function readdirSync(path: string): string[]; }
declare module 'node:path' { export function resolve(...parts: string[]): string; }
declare module 'node:url' { export function fileURLToPath(url: URL | string): string; }
