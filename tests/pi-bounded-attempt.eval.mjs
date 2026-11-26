// Opt-in: node tests/pi-bounded-attempt.eval.mjs <installed-local-Ollama-model>
// Loopback only; no model pull, native provider, real child, or service tools.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { cases, fixture, grade, loadPolicy } from './pi-attempt-cases.mjs';

const [model, ...extra] = process.argv.slice(2);
assert.ok(!extra.length && /^[a-z\d][a-z\d._:/-]*$/i.test(model ?? '') && !/cloud/i.test(model), 'Pass one installed local tool-capable model');
async function api(path, payload) {
  const response = await fetch(`http://127.0.0.1:11434/api/${path}`, {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(120_000),
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  assert.ok(response.ok, `Local Ollama ${path}: ${response.status}`);
  return response.json();
}
const info = await api('show', { model }); // Check before sending any policy; never pull a model.
assert.ok(!info.remote_host && !info.remote_model && info.capabilities.includes('tools'), 'Requires local inference and tool calls');
const policy = loadPolicy(path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
for (const c of cases) test(c.id, async t => {
  const { tools, messages, trace, execute, metrics } = fixture(c, policy);
  let requests = 0, inputTokens = 0, outputTokens = 0, final = '';
  t.after(() => t.diagnostic(JSON.stringify({ model, case: c.id, history: c.cold ? 'cold' : 'warm', requests,
    inputTokens, outputTokens, ...metrics, trace, expected: c.trace, final, ...grade(c, trace, final) })));
  while (requests < 6) {
    requests++;
    const { message, prompt_eval_count, eval_count } = await api('chat', { model, messages, tools, stream: false, think: false,
      options: { temperature: 0, seed: 42, num_ctx: 16384, num_predict: 1000 } });
    inputTokens += prompt_eval_count ?? 0; outputTokens += eval_count ?? 0;
    messages.push(message);
    if (!message.tool_calls?.length) { final = message.content; break; }
    for (const { function: call } of message.tool_calls) {
      const result = execute(call, requests);
      messages.push({ role: 'tool', tool_name: call.name, content: typeof result === 'string' ? result : JSON.stringify(result) });
    }
  }
  assert.deepEqual(grade(c, trace, final), { traceMatch: true, claimMatch: true, footerMatch: true });
});
