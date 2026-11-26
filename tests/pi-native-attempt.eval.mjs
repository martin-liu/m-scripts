// Pi 1.6.1. No arguments: closed. --check BASELINE_DIR: serialize matched cases, intercept before transfer.
// Separately authorized only: PI_ATTEMPT_LIVE=matched-synthetic-v1 PI_ATTEMPT_TOKEN=<gateway bearer>
// node tests/pi-native-attempt.eval.mjs --live-matched BASELINE_DIR. No installed profile, prompt-file or URL override.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { cases, fixture, grade, loadPolicy } from './pi-attempt-cases.mjs';

const self = fileURLToPath(import.meta.url), repo = resolve(dirname(self), '..');
export const endpoint = 'https://llmgateway.app.nand.ai/v1/responses'; // Independent of models.json and SDK.
const provider = 'litellm', model = 'gpt-6.1-terra', effort = 'xhigh', maxRequests = 6;
const digest = b => createHash('sha256').update(b).digest('hex');
const same = (actual, expected, why) => assert.ok(isDeepStrictEqual(actual, expected), why); // never print rejected bytes
const pins = {
  baseline: ['40854d9470d2ef0b9521c690705a676acac2bbd8ca9a32002f95a704a549427a', '38cae65e9ee7979aa52de7b0a60d08b0f7941053188967ce6a75322feb3d3e79', '5c58a2da940460143197b6e0a52c5f9ce5a776adf85be92a440bd2bee7c9bac4', 'e1d2fd622aeafce6919210b194cbec637642fad953e62121ff923ac295e7ef90'],
  candidate: ['0ca7c4b82add713627d815ee3b05b1f76704057f267c692343eb7c22099d0eef', '771c7f2dcc9bb9097fcde2da3b50161b33bd4e8393c6a3cc2fafd09ef7f66ac9', '1a04cf4f08c9678e2b4e4769443c0fb32ef49e24a098272711ad80ec997ebcfc', 'bb1d52019c592671a904f89a957e2dc3dd522a5ce842f30b976bf8d160e3b88d'],
};
function boundPolicy(dir, arm) {
  const root = fs.realpathSync(dir); let i = 0;
  return loadPolicy(rel => {
    const path = join(root, rel);
    assert.ok(fs.realpathSync(path) === path && fs.statSync(path).isFile(), 'Not a regular fixture file under the bound root');
    const bytes = fs.readFileSync(path);
    assert.ok(digest(bytes) === pins[arm][i++], `Unapproved ${arm} policy revision (${rel})`);
    return bytes.toString('utf8');
  });
}
export function mode(args, consent) {
  if (!args.length) return 'closed';
  assert.ok(args.length === 2 && ['--check', '--live-matched'].includes(args[0]) && !args[1].startsWith('-'), 'Expected --check or --live-matched and a baseline directory');
  if (args[0] === '--check') return 'check';
  assert.ok(consent === 'matched-synthetic-v1', 'Matched live inference not authorized'); return 'live';
}
const userItem = text => ({ role: 'user', content: [{ type: 'input_text', text }] });
function pair(id, name, args, output) {
  return [{ type: 'function_call', call_id: id, name, arguments: JSON.stringify(args), status: 'completed' },
    { type: 'function_call_output', call_id: id, output }];
}
const text = content => content.filter(m => m.type === 'text').map(m => m.text).join('\n');
const block = text => [{ type: 'text', text }];
// Positive allowlist, applied to the actual HTTP body at transfer time (not an onPayload counter).
// Fixture and fake results supply every byte of input. Only tool calls observed from this same synthetic session
// are replayed; reasoning blobs, assistant prose, provider item IDs and SDK/client headers never travel back.
export function checkedBody(url, method, raw, expected) {
  assert.ok(url === endpoint && method === 'POST', 'Unapproved request target or method');
  const body = JSON.parse(raw);
  same(body, expected, 'Unexpected serialized payload, identifier, tool, prompt or history');
  return JSON.stringify(expected);
}

// Exercise one real SDK tool round trip on both a cold and a warm case, without an HTTP request or inference.
function offlineToolResponse(name, args) {
  const item = { type: 'function_call', id: 'fc_fixture', call_id: 'call_offline', name, arguments: JSON.stringify(args) };
  const events = ['added', 'done'].map(state => ({ type: `response.output_item.${state}`, output_index: 0, item }));
  events.push({ type: 'response.completed', response: { status: 'completed', output: [item] } });
  return new Response(events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
}

function installedSdk() {
  const bin = process.env.PATH.split(':').map(d => join(d, 'pi')).find(p => fs.existsSync(p));
  assert.ok(bin, 'Requires installed Pi 1.6.1 on PATH');
  const cli = fs.realpathSync(bin), entry = cli.endsWith('.js') ? cli : fs.readFileSync(cli, 'utf8').match(/^# cmd-shim-target=(.+)$/m)?.[1];
  for (let p = dirname(fs.realpathSync(entry)); p !== dirname(p); p = dirname(p)) {
    if (fs.existsSync(join(p, 'dist/core/sdk.js'))) {
      const pkg = JSON.parse(fs.readFileSync(join(p, 'package.json'), 'utf8'));
      same([pkg.name, pkg.version], ['@earendil-works/pi-coding-agent', '1.6.1'], 'Unsupported SDK'); return p;
    }
  }
  throw Error('Installed Pi SDK not found');
}
async function main(args) {
  const run = mode(args, process.env.PI_ATTEMPT_LIVE);
  if (run === 'closed') { console.log('Closed. --check BASELINE_DIR exercises the SDK without transfer.'); return; }
  const policies = { baseline: boundPolicy(args[1], 'baseline'), candidate: boundPolicy(repo, 'candidate') };
  const cfg = rel => JSON.parse(fs.readFileSync(join(repo, 'shell/config/pi', rel), 'utf8'));
  const s = cfg('settings.json'), p = cfg('models.json').providers[provider];
  same([s.defaultProvider, s.defaultModel, s.defaultThinkingLevel, p.baseUrl + '/responses'], [provider, model, effort, endpoint], 'Unapproved Pi configuration');
  const spec = p.models.find(m => m.id === model);
  same([spec.api, spec.thinkingLevelMap.xhigh, spec.reasoning], ['openai-responses', effort, true], 'Unapproved model/effort');
  const sdk = installedSdk(), load = rel => import(pathToFileURL(join(sdk, 'dist', rel)));
  const token = run === 'live' ? process.env.PI_ATTEMPT_TOKEN : null; // never passed to Pi or put in a prompt
  assert.ok(run !== 'live' || typeof token === 'string' && /^[A-Za-z0-9._~+/=-]{10,4096}$/.test(token), 'A separately supplied gateway bearer is required');
  assert.ok(process.env.NODE_USE_ENV_PROXY !== '1' && process.env.NODE_TLS_REJECT_UNAUTHORIZED !== '0', 'Refusing proxy or disabled TLS validation');
  const transfer = globalThis.fetch;
  const noFetch = () => { throw Error('No transfer permitted during setup or outside the bound turn'); };
  globalThis.fetch = noFetch;
  for (const key of Object.keys(process.env)) delete process.env[key]; // do not let installed SDK discover auth, proxy or context from the caller
  const tmp = fs.mkdtempSync(join(dirname(self), '.pi-attempt-'));
  try {
    const agentDir = join(tmp, 'config'), cwd = '/fixture/project';
    process.chdir(tmp);
    for (const key of ['home', 'config', 'tmp']) fs.mkdirSync(join(tmp, key));
    Object.assign(process.env, { HOME: join(tmp, 'home'), TMPDIR: join(tmp, 'tmp'), PI_CODING_AGENT_DIR: agentDir,
      PI_PACKAGE_DIR: sdk, PI_OFFLINE: '1', PI_TELEMETRY: '0', PATH: '/usr/bin:/bin' });
    const pi = await load('index.js'), { AuthStorage } = await load('core/auth-storage.js');
    assert.equal(pi.VERSION, '1.6.1');
    const runtime = await pi.ModelRuntime.create({ modelsPath: null, credentials: AuthStorage.inMemory(), allowModelNetwork: false, refreshOnCreate: false });
    // Import only fixed public model fields, never a models.json command, auth selector, headers or arbitrary compatibility overrides.
    runtime.registerProvider(provider, { api: 'openai-responses', baseUrl: endpoint.slice(0, -10), apiKey: 'fixture-key', models: [{
      id: model, name: model, reasoning: true, input: ['text'], contextWindow: 320000, maxTokens: 32000, thinkingLevelMap: { xhigh: effort },
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, // SDK requires a tariff; no billed rate is known or reported.
    }] });
    const parent = runtime.getModel(provider, model);
    same([parent.provider, parent.id, parent.api, parent.baseUrl + '/responses', parent.contextWindow, parent.maxTokens],
      [provider, model, spec.api, endpoint, spec.contextWindow, spec.maxTokens], 'Unapproved native model');
    // No writes outside the isolated fixture. Pi's displayed cwd below is logical, not an actual checkout.
    assert.ok(!fs.existsSync('/fixture/project'), 'Synthetic cwd unexpectedly exists');
    const settingsManager = pi.SettingsManager.inMemory({ defaultProvider: provider, defaultModel: model, defaultThinkingLevel: effort,
      retry: { enabled: false, provider: { maxRetries: 0, timeoutMs: 120000 } }, compaction: { enabled: false }, enableAnalytics: false, enableInstallTelemetry: false, cacheWarming: 'off' });
    for (const [i, c] of cases.entries()) for (const arm of (i % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate'])) {
      const f = fixture(c, policies[arm]), names = f.tools.map(t => t.function.name), sessionId = `fixture-${arm}-${c.id}`;
      const resourceLoader = new pi.DefaultResourceLoader({ cwd: tmp, agentDir, settingsManager, noExtensions: true, noContextFiles: true,
        noSkills: true, noThemes: true, noPromptTemplates: true, systemPrompt: 'Synthetic Pi decision fixture.', appendSystemPrompt: [],
        appendSystemPromptOverride: () => [f.messages[0].content] });
      await resourceLoader.reload();
      for (const list of [resourceLoader.getExtensions().extensions, resourceLoader.getExtensions().errors, resourceLoader.getSkills().skills, resourceLoader.getAgentsFiles().agentsFiles]) assert.equal(list.length, 0);
      const sessionManager = pi.SessionManager.inMemory(cwd, { id: sessionId }), calls = new Map(), receipts = new Map(), attempted = [];
      const offlineCall = c.id === 'terminal-error' ? ['submit_candidate', {}] : c.id === 'private-rename' ? ['subagent', { agent: 'worker', task: 'Direct: ' + c.request }] : null;
      let projections = 0, transfers = 0, projectedWireBytes = 0, usage = [], final = '', problem, intercepted = false;
      const input = [{ role: 'developer', content: `Synthetic Pi decision fixture.\n\n<addendum>\n${f.messages[0].content}\n</addendum>\n\n<cwd>\n${cwd}\n</cwd>` }, userItem(f.messages[1].content)];
      const customTools = f.tools.map(({ function: fn }) => ({ ...fn, label: fn.name, execute: async (id, args) => {
        try {
          const observed = calls.get(id);
          same([observed?.name, observed?.args], [fn.name, args], 'Tool not requested by this synthetic session');
          const r = f.execute({ name: fn.name, arguments: args }, projections), output = typeof r === 'string' ? r : JSON.stringify(r);
          receipts.set(id, output); return { content: block(output), details: {} };
        } catch { problem = new Error('Fixture rejected a tool call'); session.agent.abort(); throw problem; }
      } }));
      const { session } = await pi.createAgentSession({ cwd, agentDir, resourceLoader, settingsManager, sessionManager, modelRuntime: runtime, model: parent,
        tools: names, noTools: 'all', customTools });
      try {
        await session.bindExtensions({ mode: 'print' });
        for (const list of [session.getAllTools().map(t => t.name), session.getActiveToolNames()]) same(list.sort(), [...names].sort(), 'Only in-memory tools may be registered');
        assert.equal(session.thinkingLevel, effort);
        if (!c.cold) {
          const seed = await session._prepareRun({ messageType: 'user', prompt: f.messages[1].content });
          const { name, arguments: args } = f.messages[2].tool_calls[0].function, id = 'call_prepare', output = f.messages[3].content;
          seed.push({ role: 'assistant', api: parent.api, provider, model, stopReason: 'toolUse', timestamp: 0,
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { total: 0 } }, content: [{ type: 'toolCall', id, name, arguments: args }] },
          { role: 'toolResult', toolCallId: id, toolName: name, content: block(output), isError: false, timestamp: 0 });
          for (const m of seed) sessionManager.appendMessage(m); session.agent.state.messages = seed;
          input.push(...pair(id, name, args, output), userItem(f.messages[4].content));
        }
        session.agent.subscribe(e => {
          if (e.type !== 'message_end' || e.message.role !== 'assistant') return;
          if (run === 'live' && e.message.stopReason !== 'error') usage.push(e.message.usage);
          for (const t of e.message.content.filter(t => t.type === 'toolCall')) {
            attempted.push(t.name === 'subagent' ? t.arguments.agent : t.name);
            calls.set(t.id, { name: t.name, args: structuredClone(t.arguments), synthetic: `call_fixture_${calls.size + 1}` });
          }
        });
        const originalTransform = session.agent.transformContext;
        session.agent.transformContext = async (...args) => (await originalTransform(...args)).map(m => {
          if (m.role === 'toolResult' && calls.has(m.toolCallId)) return { ...m, toolCallId: calls.get(m.toolCallId).synthetic };
          if (m.role !== 'assistant' || m.timestamp === 0) return m;
          return { ...m, content: m.content.filter(t => t.type === 'toolCall').map(t => ({ type: 'toolCall', id: calls.get(t.id).synthetic, name: t.name, arguments: t.arguments })) };
        });
        globalThis.fetch = async (url, opts) => {
          try {
            if (problem) throw problem;
            assert.ok(++projections <= maxRequests, 'Model request limit reached');
            const history = [...input];
            for (const [id, t] of calls) {
              assert.ok(receipts.has(id), 'Missing fake tool receipt');
              history.push(...pair(t.synthetic, t.name, t.args, receipts.get(id)));
            }
            const expected = { model, input: history, stream: true, store: false, prompt_cache_key: sessionId,
              max_output_tokens: 32000, tools: f.tools.map(t => ({ type: 'function', ...t.function })),
              reasoning: { effort, summary: 'auto' }, include: ['reasoning.encrypted_content'] };
            const body = checkedBody(String(url), opts?.method, opts?.body, expected);
            projectedWireBytes += Buffer.byteLength(body);
            if (run === 'check') {
              if (offlineCall && projections === 1) return offlineToolResponse(...offlineCall);
              intercepted = true; throw Error('Offline interception');
            }
            transfers++;
            return await transfer(endpoint, { method: 'POST', redirect: 'error', signal: opts.signal,
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body });
          } catch (e) { if (!intercepted) problem = e; throw e; }
        };
        await session.prompt(f.messages.at(-1).content);
        if (problem) throw problem;
        if (run === 'check') {
          assert.ok(intercepted && projections === (offlineCall ? 2 : 1) && transfers === 0, 'SDK did not reach the expected offline boundary');
          same(f.trace, offlineCall ? c.trace : [], 'Offline tool round trip did not execute');
        }
        else {
          same(attempted, f.trace, 'A model call did not execute');
          const last = session.messages.at(-1); assert.ok(last.role === 'assistant' && last.stopReason === 'stop', 'Provider did not return a terminal answer');
          final = text(last.content);
          if (Object.values(grade(c, f.trace, final)).includes(false)) process.exitCode = 1;
        }
      } catch (e) {
        // A behavioral failure still gets its matched partner; a boundary/transport error closes the entire run.
        if (run !== 'live' || problem?.message !== 'Fixture rejected a tool call') throw e;
        process.exitCode = 1;
      } finally {
        globalThis.fetch = noFetch; session.dispose();
        console.log(JSON.stringify({ run, arm, case: c.id, history: c.cold ? 'cold' : 'warm', provider, model, effort, projections, transfers,
          projectedWireBytes, actualParentUsage: usage.map(({ input, output, cacheRead, cacheWrite }) => ({ input, output, cacheRead, cacheWrite })),
          billedCost: null, ...f.metrics, attempted, executed: f.trace, expectedTrace: c.trace, final, ...(run === 'live' ? grade(c, f.trace, final) : {}) }));
      }
    }
  } finally { process.chdir(dirname(self)); } // Leave the isolated SDK directories for operator inspection.
}
if (process.argv[1] && resolve(process.argv[1]) === self) await main(process.argv.slice(2)).catch(e => {
  // SDK errors may contain private paths, raw provider responses or headers; never print them.
  console.error(e.code === 'ERR_ASSERTION' && !e.generatedMessage ? e.message.split('\n')[0] : 'Native fixture setup/transport failed'); process.exitCode = 1;
});
