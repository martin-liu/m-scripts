## Setup [Mac only]
Clone this repo and run `bin/setup.sh` in terminal, then open Ghostty.

### Full setup
```sh
bin/setup.sh
```
Installs everything: shell tools, AI coding tools, Rust toolchain, Emacs, LaTeX, etc.

### Lite setup
```sh
bin/setup.sh --lite
```
Installs only shell essentials, theme/look-and-feel, and AI coding tools (OpenCode and Claude Code). OpenCode uses its native V2 agents and plugins. Skips Emacs, LaTeX, Rust build, and heavy dependencies.

Both modes will:
* add `register.sh` to `~/.zshrc`
* sync config files (Ghostty, Zellij, Git, OpenCode, Claude Code settings)
* install and configure [zellij-attention](https://github.com/KiryuuLight/zellij-attention) for OpenCode — marks the correct zellij tab ⚡ and notifies when an agent needs input
* install and configure [Talon Voice](https://talonvoice.com) for hands-free Zellij navigation, AI pane switching, and local Whisper dictation — see `talon/README.md` for commands

### OpenCode

The V2 CLI is installed with:

```sh
pnpm add -g --allow-build=@opencode/cli @opencode/cli
```

Use `opencode` to start OpenCode. Configuration is managed at the standard `~/.config/opencode` paths, with native agents and the local zellij-attention plugin. The `upgrade` command updates the stable CLI and restarts its service.

Full mode additionally:
* install Rust toolchain and build the `m` CLI
* install and configure DoomEmacs

### Emacs
Need one time `M-x all-the-icons-install-fonts` to ensure icons show correctly.

---

## Standalone: opencode quick setup

A self-contained script for setting up and configuring OpenCode with shell essentials on a fresh Mac. No dependency on this repo — it can be run independently.

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/martin-liu/m-scripts/master/bin/setup-opencode.sh)
```

Includes: Homebrew, shell tools (starship, bat, eza, zellij, atuin, etc.), Ghostty + Dracula theme, Fira Code font, the OpenCode V2 CLI, and the agent-browser skill. Writes standalone shell and tool configuration directly to the user's home directory; it does not install repository-managed OpenCode agents or plugins.

---

## Skills

AI agent skills that can be installed with the [skills CLI](https://github.com/vercel-labs/skills):

```sh
# Install all skills from this repo
npx -y skills add martin-liu/m-scripts -g

# Install all skills from this repo over SSH
npx -y skills add git@github.com:martin-liu/m-scripts.git -g

# Install only linkedin-sourcing
npx -y skills add martin-liu/m-scripts --skill linkedin-sourcing -g

# Install only linkedin-sourcing over SSH
npx -y skills add git@github.com:martin-liu/m-scripts.git --skill linkedin-sourcing -g
```

To update installed skills to the latest version:

```sh
# Update all installed skills
npx -y skills update

# Update only linkedin-sourcing
npx -y skills update linkedin-sourcing
```

### Available skills

| Skill | Description |
|-------|-------------|
| **xdev** | Full software-lifecycle route for complex multi-sprint work requiring durable coordination across phases, risk boundaries, or context limits. Use Direct or Reviewed for bounded work. |
| **linkedin-sourcing** | LinkedIn Recruiter (paid product) sourcing assistant. Automates candidate outreach with Excel-driven state, phased execution, and browser automation. Requires macOS + Google Chrome. |

---

## Tools
* [Raycast](https://www.raycast.com)
  + Add `./raycast` folder as raycast script folder
* [Homebrew](https://brew.sh/)
* zsh
* [DoomEmacs](https://github.com/doomemacs/doomemacs)
* [atuin](https://github.com/atuinsh/atuin), shell history search (replaces fzf Ctrl-R)
* [Ghostty](https://github.com/ghostty-org/ghostty) terminal emulator
* [Zellij](https://github.com/zellij-org/zellij), replacement of tmux/screen
* [zellij-attention](https://github.com/KiryuuLight/zellij-attention), marks the zellij tab needing input with ⚡ (for multi-agent workflows)
* [Talon Voice](https://talonvoice.com), hands-free voice control for Zellij navigation and AI pane switching — see `talon/README.md` for commands

---

## zellij-attention

A Zellij plugin that flags the active tab with ⚡ when an AI agent (Claude Code or OpenCode) is waiting for your input. OpenCode's local plugin owns its notification and sound behavior, pairing it with the ⚡ flag. Its host-attention policy is managed in `~/.config/opencode/cli.json`.

### How it works

| Component | Purpose |
|-----------|---------|
| `plugins/zellij-attention/` (Rust/WASM) | Zellij plugin loaded via `load_plugins`. Handles tab renaming (add/remove ⚡) and auto-clears when you focus the tab. |
| `shell/config/claude-attention.sh` | Claude Code hook script. Fires on `Stop` and `Notification` events with a 3-second debounce. |
| `shell/config/opencode-zellij-attention/tui.js` | OpenCode local TUI plugin. Tracks root execution and attention events; successful completion has a 3-second delay, while permissions, forms, interruptions, and failures may notify immediately with an explicit OpenCode built-in sound request. |

### Features

- **Auto-clear on focus**: Switch to a triggered tab and the ⚡ disappears automatically
- **Switch-away clear**: Switch away from a triggered tab and the ⚡ also disappears
- **Subagent filtering**: OpenCode tracks the root session ID; subagent sessions are ignored
- **Debounce**: Claude and OpenCode successful completion notifications wait 3 seconds before notifying, absorbing rapid subagent churn; permission, form, interruption, and failure notifications may be immediate
- **Per-pane isolation**: Multiple OpenCode/Claude panes in different tabs don't interfere with each other

### Debug logging

Set the environment variable to see which events fire:

```bash
# Claude Code
CLAUDE_ATTENTION_DEBUG=1 claude
# Then check: cat /tmp/claude-attention-hooks.log

# OpenCode
OPENCODE_ATTENTION_DEBUG=1 opencode
# Then check: cat /tmp/opencode-attention-events.log
```
* [Fira Code Font](https://github.com/tonsky/FiraCode)
* [OpenCode](https://opencode.ai), AI coding assistant (TUI)
* [Claude Code](https://claude.ai/code), AI coding assistant (CLI)
* [Rust Alternatives](https://github.com/TaKO8Ki/awesome-alternatives-in-rust)
