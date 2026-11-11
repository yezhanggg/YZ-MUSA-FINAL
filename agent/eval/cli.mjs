// Runs an eval script (TypeScript) outside Vite: `node agent/eval/cli.mjs <script.ts> [flags]`.
// jiti compiles the TypeScript, and `virtual:lot-index` (made by vite.config.ts in the app) points to a Node stand-in.
import { createJiti } from 'jiti';
import { resolve } from 'node:path';

const here = import.meta.dirname;
const [script, ...rest] = process.argv.slice(2);
if (!script) {
  console.error('usage: node agent/eval/cli.mjs <make_questions.ts | run.ts | score.ts> [flags]');
  process.exit(2);
}
process.argv = [process.argv[0], script, ...rest];
const jiti = createJiti(import.meta.url, { alias: { 'virtual:lot-index': resolve(here, 'lotIndex.node.ts') }, interopDefault: true });
await jiti.import(resolve(here, script));
