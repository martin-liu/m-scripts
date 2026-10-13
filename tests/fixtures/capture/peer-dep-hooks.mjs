// Non-invasive peer-dep resolution for the installed pi-subagents plugin.
//
// Resolves `pi-subagents` itself, `typebox` (and subpaths), and the
// `@earendil-works/*` packages Pi's runtime provides. Those runtime packages
// publish an `exports` map (e.g. `"./compat": {"import": "./dist/compat.js"}`),
// so subpaths are resolved through `exports` first and by probing `dist/`
// second — never by handing Node a directory.
//
// Register with:
//   node --import tests/fixtures/capture/peer-dep-register.mjs <recipe.mjs>
import { readFileSync, existsSync, readdirSync } from "node:fs";

const PI_SUBAGENTS = "/Users/martinliu/.pi/agent/npm/node_modules/pi-subagents";
const TYPEBOX_ROOT =
  "/Users/martinliu/Library/pnpm/global/v11/21b6-18dc5f48a4ebf550-0/node_modules/.pnpm/typebox@1.3.27/node_modules/typebox/build";
const PI_RUNTIME_ROOT =
  "/Users/martinliu/Library/pnpm/global/v11/21b6-18dc5f48a4ebf550-0/node_modules/.pnpm/@earendil-works+pi-coding-agent@1.1.0_@aws-sdk+credential-provider-node@3.972.84_@smithy+signature-v4@5.7.4_ws@8.22.0/node_modules";

const TYPEBOX_MAP = {};
for (const sub of ["", "compile", "error", "format", "guard", "schema", "system", "type", "value"]) {
  TYPEBOX_MAP[sub ? `typebox/${sub}` : "typebox"] = TYPEBOX_ROOT + (sub ? `/${sub}` : "") + "/index.mjs";
}

let EARENDIL_NAMES = [];
try {
  EARENDIL_NAMES = readdirSync(PI_RUNTIME_ROOT + "/@earendil-works");
} catch {
  EARENDIL_NAMES = [];
}

/** Map a specifier to a real file path, or null to let Node resolve normally. */
function mapSpecifier(specifier) {
  if (specifier === "pi-subagents") return PI_SUBAGENTS + "/src/index.js";
  if (specifier.startsWith("pi-subagents/")) {
    return PI_SUBAGENTS + "/" + specifier.slice("pi-subagents/".length);
  }
  if (Object.prototype.hasOwnProperty.call(TYPEBOX_MAP, specifier)) return TYPEBOX_MAP[specifier];

  const prefix = "@earendil-works/";
  if (!specifier.startsWith(prefix) || EARENDIL_NAMES.length === 0) return null;
  const rest = specifier.slice(prefix.length);
  const name = rest.split("/")[0];
  if (!EARENDIL_NAMES.includes(name)) return null;
  const root = `${PI_RUNTIME_ROOT}/@earendil-works/${name}`;
  const tail = rest.slice(name.length).replace(/^\//, "");
  if (tail.length === 0) {
    for (const c of [`${root}/dist/index.js`, `${root}/index.js`, `${root}/dist/index.mjs`]) {
      if (existsSync(c)) return c;
    }
    return `${root}/dist/index.js`;
  }
  try {
    const pkg = JSON.parse(readFileSync(`${root}/package.json`, "utf8"));
    const entry = pkg.exports?.[`./${tail}`];
    const rel = typeof entry === "string" ? entry : entry?.import ?? entry?.default;
    if (typeof rel === "string" && rel.length > 0 && !rel.includes("*")) {
      const full = `${root}/${rel.replace(/^\.\//, "")}`;
      if (existsSync(full)) return full;
    }
  } catch {
    // fall through to probing
  }
  const candidates = [
    `${root}/${tail}`,
    `${root}/${tail}.js`,
    `${root}/dist/${tail}.js`,
    `${root}/${tail}/index.js`,
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return `${root}/dist/${tail}.js`;
}

export async function resolve(specifier, context, next) {
  const mapped = mapSpecifier(specifier);
  if (mapped !== null) return next("file://" + mapped, context);
  return next(specifier, context);
}