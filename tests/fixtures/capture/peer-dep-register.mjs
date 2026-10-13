// Registers the peer-dep resolve hook so the capture recipe can import the
// INSTALLED pi-subagents package. Usage:
//   node --import tests/fixtures/capture/peer-dep-register.mjs \
//        tests/fixtures/capture/capture-rpc-envelopes.mjs
import { register } from "node:module";
import { pathToFileURL } from "node:url";

register("./tests/fixtures/capture/peer-dep-hooks.mjs", pathToFileURL("./"));