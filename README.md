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
Installs only shell essentials, theme/look-and-feel, and AI coding tools (opencode, Claude Code, oh-my-opencode-slim). Skips Emacs, LaTeX, Rust build, and heavy dependencies.

Both modes will:
* add `register.sh` to `~/.zshrc`
* sync config files (Ghostty, Zellij, Git, opencode, Claude Code settings)
* install and configure [zellij-attention](https://github.com/KiryuuLight/zellij-attention) — marks the correct zellij tab ⚡ and sends a macOS notification (with sound) when an AI agent needs input
* install and configure [Talon Voice](https://talonvoice.com) for hands-free Zellij navigation, AI pane switching, and local Whisper dictation — see `talon/README.md` for commands

Full mode additionally:
* install Rust toolchain and build the `m` CLI
* install and configure DoomEmacs

### Emacs
Need one time `M-x all-the-icons-install-fonts` to ensure icons show correctly.

---

## Standalone: opencode quick setup

A self-contained script for setting up opencode with shell essentials on a fresh Mac. No dependency on this repo — can be run independently.

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/martin-liu/m-scripts/master/bin/setup-opencode.sh)
```

Includes: Homebrew, shell tools (starship, bat, eza, zellij, atuin, etc.), Ghostty + Dracula theme, Fira Code font, opencode, and agent-browser skill. Writes all configs and shell setup directly to `~/.zshrc`.

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
| **xdev** | Full software-lifecycle skill for multi-sprint feature work. Drives requirements → design → sprint loop → production close, with file-based state that survives context resets. Not for single-PR work. |
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

A Zellij plugin that flags the active tab with ⚡ when an AI agent (Claude Code or opencode) is waiting for your input. It also sends a macOS notification with sound.

### How it works

| Component | Purpose |
|-----------|---------|
| `plugins/zellij-attention/` (Rust/WASM) | Zellij plugin loaded via `load_plugins`. Handles tab renaming (add/remove ⚡) and auto-clears when you focus the tab. |
| `shell/config/claude-attention.sh` | Claude Code hook script. Fires on `Stop` and `Notification` events with a 3-second debounce. |
| `shell/config/opencode-zellij-attention.js` | opencode plugin. Tracks the main session ID and fires on `idle` / `question.asked` with a 3-second debounce. |

### Features

- **Auto-clear on focus**: Switch to a triggered tab and the ⚡ disappears automatically
- **Switch-away clear**: Switch away from a triggered tab and the ⚡ also disappears
- **Subagent filtering**: opencode tracks the main session ID; subagent sessions are ignored
- **Debounce**: Both Claude and opencode hooks wait 3 seconds before notifying, absorbing rapid subagent churn
- **Per-pane isolation**: Multiple opencode/Claude panes in different tabs don't interfere with each other

### Debug logging

Set the environment variable to see which events fire:

```bash
# Claude Code
CLAUDE_ATTENTION_DEBUG=1 claude
# Then check: cat /tmp/claude-attention-hooks.log

# opencode
OPENCODE_ATTENTION_DEBUG=1 opencode
# Then check: cat /tmp/opencode-events.log
```
* [Fira Code Font](https://github.com/tonsky/FiraCode)
* [opencode](https://opencode.ai), AI coding assistant (TUI)
* [Claude Code](https://claude.ai/code), AI coding assistant (CLI)
* [oh-my-opencode-slim](https://github.com/alvinunreal/oh-my-opencode-slim), opencode plugin for multi-agent orchestration
* [Rust Alternatives](https://github.com/TaKO8Ki/awesome-alternatives-in-rust)
