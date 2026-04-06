#!/bin/bash

# Usage: install.sh [--lite]
# --lite: install only shell essentials, AI coding tools, and theme/look-and-feel
# (no args): full install including emacs, latex, orbstack, etc.

LITE_MODE=false
if [[ "$1" == "--lite" ]]; then
    LITE_MODE=true
fi

# install homebrew
if [[ ! $(command -v brew) ]] ; then
     echo 'Installing Homebrew...'
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
     echo 'Updating Homebrew...'
     brew update
fi

## core tools (always installed)
brew install \
     ghostty `# terminal emulator` \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     starship zoxide ripgrep bat eza git-delta zellij fd `# rust cli tools` \
     node pnpm bun `# js runtimes` \
     git gh fzf zsh-syntax-highlighting jq yq `# others`

## Fira Font
brew install font-fira-code

## zsh-completion
echo "Updating common Zsh completions..."
rm -rf ~/.zsh-completions ~/.zcompdump
git clone --quiet --depth=1 https://github.com/zsh-users/zsh-completions ~/.zsh-completions

## AI coding tools
echo "Installing/updating opencode..."
pnpm install -g opencode@latest

echo "Installing/updating Claude Code..."
npm install -g @anthropic-ai/claude-code@latest

# oh-my-opencode-slim plugin (generates default configs; custom configs
# in shell/config/ are synced over by config.sh on shell load)
echo "Installing/updating oh-my-opencode-slim plugin..."
bunx oh-my-opencode-slim@latest install --no-tui --tmux=no --skills=yes

if [[ "$LITE_MODE" == true ]]; then
    echo "Lite install complete"
    exit 0
fi

## --- Full install below ---

## additional tools
brew install \
     orbstack uv `# envs` \
     rustup rust-analyzer just ast-grep tealdeer dust bottom `# rust cli tools` \
     basedpyright cmake hr libvterm graphviz tree-sitter pandoc `# others`

## Latex
brew install --cask basictex
## sudo tlmgr update --self && sudo tlmgr install dvipng

## Rust
rustup-init -y && rustup component add rust-src rust-analyzer rustfmt clippy

## Python
## link python to python3 if no python installed
if [[ ! $(command -v python) ]] && [[ $(command -v python3) ]] ; then
      sudo ln -s $(which python3) /usr/local/bin/python
fi

## emacs
# reinstall gcc to prevent potential `ld: library not found for -lemutls_w` issue
brew reinstall gcc && brew tap d12frosted/emacs-plus && \
    brew install emacs-plus@31 --with-native-comp --with-poll --with-debug && \
    ln -sf /opt/homebrew/opt/emacs-plus@31/Emacs.app /Applications

if [ -d "$HOME/.emacs.d/.git" ]; then
     echo "DoomEmacs already installed"
else
     echo "Checkout doomemacs..."
     git clone --depth 1 https://github.com/doomemacs/doomemacs $HOME/.emacs.d
     $HOME/.emacs.d/bin/doom install
fi

if [ -d "$HOME/.doom.d/.git" ]; then
     echo ".doom.d already installed"
else
     echo "Checkout https://github.com/martin-liu/.doom.d"
     git clone https://github.com/martin-liu/.doom.d $HOME/.doom.d
     $HOME/.emacs.d/bin/doom sync
fi
