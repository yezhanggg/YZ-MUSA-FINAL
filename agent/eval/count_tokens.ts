// Tokens the assistant sends on every request before the conversation: system prompt plus tool schemas.
//   node agent/eval/cli.mjs count_tokens.ts      (needs ANTHROPIC_API_KEY, uses the free count_tokens endpoint)
// Without a key it prints a character count only.
import Anthropic from '@anthropic-ai/sdk';
import type { Tool } from '@anthropic-ai/sdk/resources/messages';
import { DEFAULT_MODEL, SYSTEM_PROMPT, TOOLS } from '../schema';

const model = process.env.EVAL_MODEL || DEFAULT_MODEL;
const chars = SYSTEM_PROMPT.length + JSON.stringify(TOOLS).length;
console.log(`tools: ${TOOLS.length}, system prompt ${SYSTEM_PROMPT.length} chars, tool schemas ${JSON.stringify(TOOLS).length} chars, total ${chars} chars`);
const key = process.env.ANTHROPIC_API_KEY;
if (key) {
  const sdk = new Anthropic({ apiKey: key });
  const messages = [{ role: 'user' as const, content: 'hi' }];
  const bare = await sdk.messages.countTokens({ model, messages });
  const full = await sdk.messages.countTokens({ model, system: SYSTEM_PROMPT, tools: TOOLS as unknown as Tool[], messages });
  console.log(`${model}: system prompt + tool schemas = ${full.input_tokens - bare.input_tokens} tokens`);
} else console.log('ANTHROPIC_API_KEY not set: no token count.');
