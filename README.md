## Setup [Mac only]
Clone this repo and run `bin/setup.sh` in terminal, once it finish, then open Ghostty for terminal, open Emacs for coding.

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

Full mode additionally:
* install Rust toolchain and build the `m` CLI
* install and configure DoomEmacs

### Emacs
Need one time `M-x all-the-icons-install-fonts` to ensure icons show correctly.

## tools
* [Raycast](https://www.raycast.com)
  + Add `./raycast` folder as raycast script folder
* [Homebrew](https://brew.sh/)
* zsh
* [DoomEmacs](https://github.com/doomemacs/doomemacs)
* [fzf](https://github.com/junegunn/fzf), command-line fuzzy finder (for history, files, etc)
* [Ghostty](https://github.com/ghostty-org/ghostty) terminal emulator
* [Zellij](https://github.com/zellij-org/zellij), replacement of tmux/screen
* [Fira Code Font](https://github.com/tonsky/FiraCode)
* [opencode](https://opencode.ai), AI coding assistant (TUI)
* [Claude Code](https://claude.ai/code), AI coding assistant (CLI)
* [oh-my-opencode-slim](https://github.com/alvinunreal/oh-my-opencode-slim), opencode plugin for multi-agent orchestration
* [Rust Alternatives](https://github.com/TaKO8Ki/awesome-alternatives-in-rust)
