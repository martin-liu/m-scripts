// Opt-in macOS test: node tests/installed-pi-boundary.mjs [--strict-retirement]
// The default checks compatibility with a hidden retained definition, NOT retirement.
// Uses installed packages read-only; set PI_SDK_ROOT / PI_NPM_MODULES for nonstandard installs.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import { registerHooks } from 'node:module';
import { homedir, tmpdir } from 'node:os';
import { delimiter, dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const self = fileURLToPath(import.meta.url), repo = resolve(dirname(self), '..');
const json = path => JSON.parse(fs.readFileSync(path, 'utf8'));
const load = path => import(pathToFileURL(path).href);
const roles = ['oracle', 'planner', 'worker'];
const args = process.argv.slice(2);
const strict = args.includes('--strict-retirement');
const inside = args[0] === '--isolated';
assert.deepEqual(args, [...(inside ? ['--isolated'] : []), ...(strict ? ['--strict-retirement'] : [])],
  'Usage: node tests/installed-pi-boundary.mjs [--strict-retirement]');

function sdkRoot() {
  if (process.env.PI_SDK_ROOT) return fs.realpathSync(process.env.PI_SDK_ROOT);
  const bin = process.env.PATH.split(delimiter).map(p => join(p, 'pi')).find(p => fs.existsSync(p));
  assert.ok(bin, 'Missing installed pi on PATH; alternatively set PI_SDK_ROOT to its package directory');
  const cli = fs.realpathSync(bin);
  const target = cli.endsWith('.js') ? cli : fs.readFileSync(cli, 'utf8').match(/^# cmd-shim-target=(.+)$/m)?.[1];
  assert.ok(target, 'Unrecognized pi launcher; set PI_SDK_ROOT to the installed @earendil-works/pi-coding-agent package');
  for (let p = dirname(fs.realpathSync(target)); p !== dirname(p); p = dirname(p)) {
    if (fs.existsSync(join(p, 'package.json')) && json(join(p, 'package.json')).name === '@earendil-works/pi-coding-agent') return p;
  }
  throw Error('Cannot locate installed Pi SDK; set PI_SDK_ROOT');
}

function runIsolated() {
  assert.ok(process.platform === 'darwin' && fs.existsSync('/usr/bin/sandbox-exec'), 'Requires macOS sandbox-exec; refusing an unsandboxed run');
  assert.equal(typeof registerHooks, 'function', 'Requires Node with module.registerHooks');
  const sdk = sdkRoot(), modules = fs.realpathSync(process.env.PI_NPM_MODULES ?? join(homedir(), '.pi/agent/npm/node_modules'));
  const src = join(repo, 'shell/config/pi');
  for (const [root, name, version] of [[sdk, '@earendil-works/pi-coding-agent', '1.6.0'], [join(modules, 'pi-subagents'), 'pi-subagents', '0.90.0']]) {
    const pkg = json(join(root, 'package.json'));
    assert.equal(`${pkg.name}@${pkg.version}`, `${name}@${version}`, `Unsupported installed boundary; requires ${name}@${version}`);
  }
  const packages = json(join(src, 'settings.json')).packages.map(spec => {
    assert.ok(spec.startsWith('npm:'), `Unsupported Pi package source: ${spec}`);
    const pkg = json(join(modules, spec.slice(4), 'package.json'));
    return `${pkg.name}@${pkg.version}`;
  });
  console.log(`Pi 1.6.0; ${packages.join(', ')}; ${process.version}; ${strict ? 'strict retirement' : 'retained compatibility (NOT retirement)'}`);
  const root = fs.realpathSync(fs.mkdtempSync(join(tmpdir(), 'pi-boundary-')));
  try {
    const cfg = join(root, 'config'), cwd = join(root, 'project'), home = join(root, 'home'), temp = join(root, 'tmp');
    for (const p of [cwd, home, temp, join(cfg, 'npm')]) fs.mkdirSync(p, { recursive: true });
    for (const item of ['settings.json', 'models.json', 'agents', 'extensions', 'APPEND_SYSTEM.md', 'themes', 'pi-fff.json']) {
      fs.cpSync(join(src, item), join(cfg, item), { recursive: true });
    }
    for (const skill of ['agent-review', 'xdev']) fs.cpSync(join(repo, 'skills', skill), join(cfg, 'skills', skill), { recursive: true });
    fs.symlinkSync(modules, join(cfg, 'npm/node_modules'));
    // Only the fixture is writable. Do not inherit credentials, inspect real runs or allow
    // package code to start a provider, detached runner or CLI (including via a shell).
    const node = fs.realpathSync(process.execPath), q = JSON.stringify;
    const deps = sdk.match(/^(.*\/pnpm\/store\/[^/]+\/links)\//)?.[1] ?? resolve(sdk, '../..');
    const profile = `(version 1)(allow default)(deny network*)(deny process-fork)(deny process-exec)(allow process-exec (literal ${q(node)}))
      (deny file-write*)(allow file-write* (subpath ${q(root)}) (literal "/dev/null"))
      (deny file-read-data (subpath ${q(homedir())}) (subpath "/private/var/folders") (subpath "/private/tmp") (subpath "/Library/Keychains"))
      (allow file-read-data (literal ${q(self)}) (subpath ${q(root)}) (subpath ${q(modules)}) (subpath ${q(deps)}))
      (deny file-read-data (regex #"/auth\\.json$"))`;
    const result = spawnSync('/usr/bin/sandbox-exec', ['-p', profile, node, self, '--isolated', ...args], {
      cwd, stdio: 'inherit', timeout: 90_000, env: {
        HOME: home, TMPDIR: temp, PATH: '/usr/bin:/bin', SHELL: '/bin/sh', PI_OFFLINE: '1', PI_TELEMETRY: '0',
        PI_CODING_AGENT_DIR: cfg, PI_CODING_AGENT_SESSION_DIR: join(root, 'sessions'), PI_SUBAGENTS_TEMP_ROOT: temp,
        PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT: sdk, PI_SUBAGENTS_TYPES_PATH: join(modules, 'pi-subagents/src/shared/types.js'),
        PI_NPM_MODULES: modules, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1',
      },
    });
    if (result.error || result.signal) throw Error(`Isolated test did not finish: ${result.error ?? result.signal}`);
    process.exitCode = result.status ?? 1;
  } finally { console.log(`Disposable fixture (system temp): ${root}`); }
}

async function checkInstalled() {
  const cwd = process.cwd(), root = dirname(cwd), cfg = process.env.PI_CODING_AGENT_DIR;
  assert.equal(cfg, join(root, 'config')); assert.equal(process.env.HOME, join(root, 'home'));
  const sdk = process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT;
  const sub = rel => load(join(process.env.PI_NPM_MODULES, 'pi-subagents/src', `${rel}.js`));
  const { resolveHostPeerAliases } = await sub('runs/background/runner-aliases');
  const { aliases, missing } = resolveHostPeerAliases(sdk);
  assert.deepEqual(missing, [], 'Required installed Pi peers are missing');
  registerHooks({ resolve: (name, ctx, next) => aliases[name] ? { url: pathToFileURL(aliases[name]).href, shortCircuit: true } : next(name, ctx) });
  const { loadHostPiCodingAgent, createDefaultChildSessionFactory } = await sub('runs/shared/child-session');
  const pi = await loadHostPiCodingAgent();
  assert.equal(pi.VERSION, '1.6.0');
  const { AuthStorage } = await load(join(sdk, 'dist/core/auth-storage.js'));
  const offlineRuntime = () => pi.ModelRuntime.create({ credentials: AuthStorage.inMemory(), allowModelNetwork: false });
  const settings = json(join(cfg, 'settings.json')), provider = settings.defaultProvider;
  const runtime = await offlineRuntime();
  const availableModels = runtime.getAllModels(provider).map(({ provider, id, contextWindow }) => ({ provider, id, fullId: `${provider}/${id}`, contextWindow }));
  const parentModel = runtime.getModel(provider, settings.defaultModel);
  assert.ok(parentModel, 'Default model not in fixture model registry');
  const { discoverAgents } = await sub('agents/agents');
  const { agents, agentDiagnostics } = discoverAgents(cwd, 'both', provider, { projectTrusted: true, globalNpmRoot: null });
  assert.deepEqual(agentDiagnostics ?? [], []);
  const { resolveSubagentLaunchContract } = await sub('api/preflight');
  const lookup = (agent, options = {}) => resolveSubagentLaunchContract({ cwd, agent, task: 'Read the supplied text.', context: 'fresh',
    agentScope: 'user', projectTrusted: true, parentModel, availableModels, artifacts: false, ...options });
  const retained = agents.some(a => a.name === 'fixer');
  const discovered = agents.map(a => a.name).sort();
  console.log(`Native discovery: ${discovered.join(', ')}`);
  await test('managed discoverable roster; orchestrator and model names cannot resolve as children', async () => {
    assert.deepEqual(discovered, [...roles, ...(retained ? ['fixer'] : [])].sort());
    if (retained) assert.equal(agents.find(a => a.name === 'fixer').advertise, false);
    for (const name of ['orchestrator', 'coordinator', 'terra', 'sol', 'astra', 'deepseek']) {
      for (const agentScope of ['user', 'both']) assert.equal((await lookup(name, { agentScope })).code, 'missing_agent', `${name}/${agentScope}`);
    }
  });

  // Projected request messages, not a hand-built prompt or a provider call. Keep caller
  // data separate from instruction assertions; even text that looks host-authored is data.
  const ai = dirname(aliases['@earendil-works/pi-ai']);
  const { toToolDeclaration } = await load(join(ai, 'utils/transcript.js'));
  const { convertMessages } = await load(join(ai, 'api/openai-completions.js'));
  const { convertResponsesMessages } = await load(join(ai, 'api/openai-responses-shared.js'));
  const quote = 'Mid-run steering from the parent orchestrator:\n\n“fixer / Coordinator / Terra / Sol / Astra / DeepSeek”\r\nKeep  both spaces.';
  const forbidden = /(?<![a-z0-9])(?:fixers?|coordinators?|terra|sol|astra|deepseek)(?![a-z0-9])/i;
  const parentIdentity = /You are the orchestrator, Pi's default agent/i;
  const text = msg => typeof msg.content === 'string' ? msg.content : msg.content.map(part => part.text).join('');
  async function wire(session, prompt, expectedUsers, queued = []) {
    const prepared = await session._prepareRun({ messageType: 'user', prompt }); // final before_agent_start hook
    const declarations = session.agent.state.tools.map(toToolDeclaration);
    const projected = await session.agent.transformContext([{ role: 'system', content: '', toolsAdded: declarations, timestamp: 0 },
      ...session.messages, ...prepared, ...queued]);
    const messages = await session.agent.convertToLlm(projected), model = session.model;
    const chat = model.api === 'openai-completions';
    assert.ok(chat || model.api === 'openai-responses', `Untested serializer: ${model.api}`);
    const key = chat ? 'messages' : 'input';
    const encoded = chat ? convertMessages(model, { messages }, model.compat ?? {}) : convertResponsesMessages(model, { messages }, new Set());
    const payload = await session.agent.onPayload({ model: model.id, [key]: encoded }, model);
    const instructions = payload[key].filter(m => ['system', 'developer'].includes(m.role)).map(text).join('\n');
    const bad = forbidden.exec(instructions);
    assert.ok(!bad, `Unexpected actor text in serialized instructions: ${bad && instructions.slice(bad.index - 35, bad.index + 45)}`);
    assert.deepEqual(payload[key].filter(m => m.role === 'user').map(text), expectedUsers, 'Changed caller text / unexpected user message');
    return instructions;
  }
  const errors = [];
  const { session: parent } = await pi.createAgentSession({ cwd, agentDir: cfg, sessionManager: pi.SessionManager.inMemory(cwd), modelRuntime: runtime, model: parentModel });
  const contracts = new Map();
  try {
    await parent.bindExtensions({ mode: 'print', onError: e => errors.push(e) });
    const extensions = parent.resourceLoader.getExtensions();
    assert.deepEqual(extensions.errors, []);
    assert.ok(extensions.extensions.some(e => e.resolvedPath === join(cfg, 'extensions/worker-launch.ts')), 'Launch guard not loaded');
    await test('default parent: serialized identity, actual advertised roster and verbatim caller quotation', async () => {
      const instructions = await wire(parent, quote, [quote]);
      assert.ok(instructions.includes(fs.readFileSync(join(cfg, 'APPEND_SYSTEM.md'), 'utf8').trim()),
        'Managed orchestrator prompt missing or truncated in serialized instructions');
      assert.ok(parentIdentity.test(instructions), 'Missing default parent identity in serialized instructions');
      assert.ok(!instructions.includes('<active_agent '), 'Parent identified as a child');
      const catalog = instructions.match(/<advertised_subagents>([\s\S]*?)<\/advertised_subagents>/)?.[1];
      assert.deepEqual(Array.from(catalog?.matchAll(/<name>([^<]+)<\/name>/g) ?? [], m => m[1]), roles);
      assert.deepEqual(errors, []);
    });
    await test('direct tool-call guard: fresh assignments bound, legacy direct/child slot blocked, retained-ID management untouched', async () => {
      const { flattenSubagentToolOptions } = await sub('extension/subagent-options');
      const dispatch = (input, toolName = 'subagent') => parent.extensionRunner.emitToolCall({ type: 'tool_call', toolName, toolCallId: 'sample', input });
      for (const role of roles) {
        const input = { agent: role, task: quote };
        assert.equal(await dispatch(input), undefined);
        const flat = flattenSubagentToolOptions(input);
        assert.deepEqual(flat, { agent: role, task: quote, agentScope: 'user', context: 'fresh', agentContract: { version: 1 } });
        const result = await lookup(role, flat);
        assert.ok(result.ok, result.message); assert.equal(result.contract.agent.filePath, join(cfg, 'agents', `${role}.md`));
        assert.equal(result.contract.tools.fanoutAuthorized, false); contracts.set(role, result.contract);
      }
      for (const tool of ['subagent', 'subagent_launch']) assert.equal((await dispatch({ agent: 'fixer', task: quote }, tool))?.block, true, tool);
      const resume = { action: 'resume', id: 'synthetic-retained-id', message: quote };
      const before = structuredClone(resume); assert.equal(await dispatch(resume), undefined); assert.deepEqual(resume, before);
    });
  } finally {
    await parent.extensionRunner.emit({ type: 'session_shutdown', reason: 'quit' }); parent.dispose();
  }

  const { runSync } = await sub('runs/foreground/execution');
  const { runChildSession } = await sub('runs/background/run-child-session');
  const { buildRunnerChildLaunch } = await sub('runs/background/runner-child-launch');
  const { buildEffectiveSystemPrompt } = await sub('runs/shared/effective-system-prompt');
  const { evaluateChildToolDiagnostic } = await sub('runs/shared/child-runtime-config');
  for (const role of roles) for (const mode of ['foreground', 'runner']) await test(`${role}/${mode}: serialized child identity, boundary and caller guidance`, async () => {
    const c = contracts.get(role), agent = agents.find(a => a.name === role);
    assert.ok(c, `No guarded ${role} contract`);
    const runner = mode === 'runner';
    if (runner) process.env.PI_SUBAGENT_CHILD = '1'; else delete process.env.PI_SUBAGENT_CHILD;
    let guide, inspected = false, failure;
    const factory = createDefaultChildSessionFactory({ loadPiCodingAgent: async () => ({ ...pi,
      ModelRuntime: { create: offlineRuntime }, createAgentSession: async options => {
        const result = await pi.createAgentSession(options), session = result.session;
        // Replace only the provider-bound entry. Both host paths still create/bind the real
        // SDK session, register native steer/followUp and invoke its child prompt port.
        session.prompt = async prompt => {
          try {
            assert.equal(prompt, `Task: ${quote}`);
            const expected = [prompt], queued = [];
            for (const action of ['steer', 'follow_up']) {
              await guide(action);
              queued.push(...session.agent.peekQueuedMessages()); session.clearQueue();
              const header = action === 'steer' ? 'Mid-run steering' : 'Queued follow-up';
              expected.push(runner ? `${header} from the parent orchestrator:\n\n${quote}\n\nIncorporate this guidance at the next safe point. Do not restart the task unless the guidance explicitly asks you to.` : quote);
            }
            const resources = session.resourceLoader.getExtensions();
            assert.deepEqual(resources.errors, []);
            assert.equal(resources.extensions.at(-1).path, '<inline:pi-subagents:prompt-boundary>');
            assert.equal(resources.extensions.some(e => e.resolvedPath === join(cfg, 'extensions/worker-launch.ts')), runner, 'Unexpected ambient extension mode');
            const missing = evaluateChildToolDiagnostic({ requiredTools: agent.tools }, session.getAllTools().map(t => t.name))?.missing ?? [];
            assert.deepEqual([...missing].sort(), role === 'worker' && !runner ? ['query-docs', 'resolve-library-id'] : []);
            const instructions = await wire(session, prompt, expected, queued);
            assert.ok(instructions.includes(`<active_agent name="${role}"/>`) && new RegExp(`You are ${role}\\b`, 'i').test(instructions), 'Missing child identity');
            assert.ok(!parentIdentity.test(instructions), 'Parent-only instructions leaked into a child');
            assert.ok(instructions.includes('You are a child subagent, not the parent orchestrator.') && instructions.includes('Do not propose or run subagents.'), 'Missing native anti-fanout instructions');
            assert.equal(`${session.model.provider}/${session.model.id}:${session.thinkingLevel}`, c.model);
            inspected = true;
          } catch (error) { failure = error; }
          finally { session.clearQueue(); }
          throw Error('OFFLINE_STOP');
        };
        return result;
      },
    }) });
    try {
      const id = `sample-${role}-${mode}`, opts = { cwd, context: 'fresh', projectTrusted: true, parentSessionId: 'sample-parent', orchestratorIntercomTarget: 'sample-parent', agentContract: { version: 1 } };
      let result;
      if (runner) {
        const systemPrompt = buildEffectiveSystemPrompt({ agent, resolvedSkills: c.skills.resolved, cwd });
        const launch = buildRunnerChildLaunch({ ...agent, ...opts, agent: role, systemPrompt }, { ...opts, id, flatIndex: 0 }, { sessionEnabled: false, model: c.model });
        result = await runChildSession({ factory, launch, prompt: `Task: ${quote}`, registerSteer: fn => {
          guide = async mode => assert.equal((await fn({ id: mode, source: 'steer-action', mode, message: quote })).state, 'queued');
        } });
      } else {
        result = await runSync(cwd, agents, role, quote, { ...opts, runId: id, preferredModelProvider: provider, availableModels,
          childSessionFactory: factory, onChildSession: port => { guide = mode => port[mode === 'steer' ? 'steer' : 'followUp'](quote); } });
      }
      if (failure) throw failure;
      assert.equal(result.error, 'OFFLINE_STOP'); assert.ok(inspected);
    } finally { await factory.dispose(); delete process.env.PI_SUBAGENT_CHILD; }
  });

  const { createScheduledRunManager } = await sub('runs/background/scheduled-runs');
  const { approveWorkflowChildLaunch } = await sub('extension/subagent-launch-tool');
  const { resolveCurrentSubagentCapabilityCeiling } = await sub('runs/shared/capability-ceiling');
  const { previewSimpleWorkflowRun } = await sub('workflows/scripted-workflow');
  // No live timer or child execution. Fire the real persisted timer path, observe the
  // tool-approval seam and resolve its simple named target via native preflight. This
  // is not a detached workflow execution or proof about arbitrary scripts/RPC/resume.
  async function probeTimer(name) {
    let now = 1_700_000_000_000, observed;
    const manager = createScheduledRunManager({ config: settings.subagents, storeRoot: join(root, 'schedule-store'), now: () => now,
      resolveCapabilityCeiling: resolveCurrentSubagentCapabilityCeiling,
      timers: { setTimeout: () => ({}), clearTimeout() {} }, async launch(params, ctx, signal) {
        const target = previewSimpleWorkflowRun(params.workflowScript);
        assert.equal(target?.agent, name); assert.equal(params.context, 'fresh');
        let offered = false;
        const approval = await approveWorkflowChildLaunch(ctx, () => { offered = true; return { ...target, key: 'one', workflowRunId: 'sample' }; }, signal);
        const resolution = await lookup(target.agent, { task: target.task, cwd: params.cwd, agentScope: 'both', context: params.context });
        observed = { offered, refusal: approval.refusal, target: resolution.ok ? resolution.contract.agent.name : resolution.code };
        throw Error('OFFLINE_STOP');
      },
    });
    const ctx = { cwd, sessionManager: { getSessionId: () => 'sample', getSessionFile: () => undefined } };
    try {
      const create = await manager.handleToolCall({ action: 'schedule.create', id: name, at: '+1s', workflowScript: `return runs.run("one", { agent: "${name}", task: "Read the sample." });` }, ctx);
      assert.ok(!create.isError, create.content[0].text);
      now += 1000; await manager.fire(manager.store, name);
      const history = (await manager.handleToolCall({ action: 'schedule.history', id: name }, ctx)).details.schedules.runs;
      assert.equal(history[0]?.dueReason, 'timer'); assert.equal(history[0]?.error, 'OFFLINE_STOP');
      return observed;
    } finally { manager.stop(); }
  }
  await test('native timer: ordinary Worker target remains resolvable; report actual legacy approval/lookup', async () => {
    const worker = await probeTimer('worker'); assert.equal(worker.target, 'worker'); assert.ok(!worker.refusal);
    const legacy = await probeTimer('fixer');
    console.log(`Fresh timer fixture: target=${legacy.target}; tool_call offered=${legacy.offered}; refusal=${legacy.refusal ?? 'none'}; stopped before execution`);
    assert.ok(legacy.target === 'missing_agent' || (retained && legacy.target === 'fixer'));
    if (strict) assert.ok(legacy.refusal || legacy.target === 'missing_agent', 'Strict retirement failed: fresh timer reached a resolvable fixer target without refusal');
  });
  await test(`${strict ? 'strict retirement' : 'retained compatibility ONLY'}: native fresh named lookup`, async () => {
    const legacy = await lookup('fixer');
    if (strict || !retained) {
      assert.equal(legacy.code, 'missing_agent', `Strict retirement failed: fresh fixer preflight ${legacy.ok ? 'accepted the retained definition' : legacy.code}`);
      assert.ok(!retained, 'Strict retirement failed: fixer remains discoverable');
      assert.ok(!fs.existsSync(join(cfg, 'agents/fixer.md')) && !settings.subagents.agentOverrides?.fixer, 'Legacy file or visibility override remains');
    } else {
      assert.ok(legacy.ok, legacy.message); assert.equal(legacy.contract.agent.filePath, join(cfg, 'agents/fixer.md'));
      console.log('Retained definition is hidden, NOT retired: fresh native lookup still accepts fixer.');
    }
  });
  await test('control only: with exactly the three current user files, fresh lookup cannot substitute another or a bundled role', async () => {
    const clean = join(root, 'current-roles-only'); fs.mkdirSync(join(clean, 'agents'), { recursive: true });
    for (const name of roles) fs.copyFileSync(join(cfg, 'agents', `${name}.md`), join(clean, 'agents', `${name}.md`));
    fs.writeFileSync(join(clean, 'settings.json'), JSON.stringify({ ...settings, subagents: { disableBuiltins: true } }));
    for (const dir of ['skills', 'npm']) fs.symlinkSync(join(cfg, dir), join(clean, dir));
    process.env.PI_CODING_AGENT_DIR = clean;
    try {
      for (const agentScope of ['user', 'both']) {
        assert.deepEqual(discoverAgents(cwd, agentScope, provider, { projectTrusted: true, globalNpmRoot: null }).agents.map(a => a.name).sort(), roles);
        assert.equal((await lookup('fixer', { agentScope })).code, 'missing_agent');
        assert.equal((await lookup('worker', { agentScope })).contract?.agent.filePath, join(clean, 'agents/worker.md'));
      }
    } finally { process.env.PI_CODING_AGENT_DIR = cfg; }
  });
}

if (inside) await checkInstalled(); else runIsolated();
