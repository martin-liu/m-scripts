#!/bin/bash

# One-time setup: shell essentials + look and feel + opencode with browser skills
# Usage: bash setup-opencode.sh

set -e

# install homebrew
if [[ ! $(command -v brew) ]] ; then
     echo 'Installing Homebrew...'
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
     eval "$(/opt/homebrew/bin/brew shellenv)"
else
     echo 'Updating Homebrew...'
     brew update
fi

## shell essentials + look and feel
brew install \
     ghostty `# terminal emulator` \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     starship zoxide ripgrep bat eza git-delta zellij fd `# rust cli tools` \
     node pnpm `# js runtimes` \
     git gh fzf zsh-syntax-highlighting jq yq `# others`

## Fira Font
brew install font-fira-code

## zsh-completion
echo "Updating common Zsh completions..."
rm -rf ~/.zsh-completions ~/.zcompdump
git clone --quiet --depth=1 https://github.com/zsh-users/zsh-completions ~/.zsh-completions

## opencode
echo "Installing/updating opencode..."
pnpm install -g opencode@latest

## opencode skills
echo "Installing opencode skills..."
npx -y skillsadd vercel-labs/agent-browser

## Ghostty config
mkdir -p ~/.config/ghostty
cat > ~/.config/ghostty/config <<'GHOSTTY'
initial-command = "/bin/zsh -l -c /opt/homebrew/bin/zellij attach --index 0 --create"

# mac
macos-option-as-alt = true

# color
palette = 0=#21222c
palette = 1=#ff5555
palette = 2=#50fa7b
palette = 3=#f1fa8c
palette = 4=#bd93f9
palette = 5=#ff79c6
palette = 6=#8be9fd
palette = 7=#f8f8f2
palette = 8=#6272a4
palette = 9=#ff6e6e
palette = 10=#69ff94
palette = 11=#ffffa5
palette = 12=#d6acff
palette = 13=#ff92df
palette = 14=#a4ffff
palette = 15=#ffffff

background = 282a36
foreground = f8f8f2
cursor-color = f8f8f2
selection-background = 44475a
selection-foreground = f8f8f2
background-opacity = 0.88

# font
font-size = 20
font-family = "Fira Code"
GHOSTTY

## Zellij config
mkdir -p ~/.config/zellij/layouts
cat > ~/.config/zellij/config.kdl <<'ZELLIJ'
theme "dracula"
pane_frames false
simplified_ui true
copy_command "pbcopy"
scroll_buffer_size: 50000

keybinds {
    normal clear-defaults=true {
        bind "Ctrl s" { SwitchToMode "tmux"; }
        bind "Alt n" { NewPane; }
        bind "Alt t" { NewTab; }
        bind "Alt h" "Alt Left" { MoveFocusOrTab "Left"; }
        bind "Alt l" "Alt Right" { MoveFocusOrTab "Right"; }
        bind "Alt j" "Alt Down" { MoveFocus "Down"; }
        bind "Alt k" "Alt Up" { MoveFocus "Up"; }
        bind "Alt =" "Alt +" { Resize "Increase"; }
        bind "Alt -" { Resize "Decrease"; }
    }

    tmux clear-defaults=true {
        bind "Ctrl s" { ToggleTab; SwitchToMode "Normal"; }
        bind "Esc" { SwitchToMode "Normal"; }
        bind "[" { SwitchToMode "Scroll"; }
        bind "Ctrl b" { Write 2; SwitchToMode "Normal"; }
        bind "-" { NewPane "Down"; SwitchToMode "Normal"; }
        bind "|" { NewPane "Right"; SwitchToMode "Normal"; }
        bind "z" { ToggleFocusFullscreen; SwitchToMode "Normal"; }
        bind "c" { NewTab; SwitchToMode "Normal"; }
        bind "," { SwitchToMode "RenameTab"; }
        bind "p" { GoToPreviousTab; SwitchToMode "Normal"; }
        bind "n" { GoToNextTab; SwitchToMode "Normal"; }
        bind "Left" { MoveFocus "Left"; SwitchToMode "Normal"; }
        bind "Right" { MoveFocus "Right"; SwitchToMode "Normal"; }
        bind "Down" { MoveFocus "Down"; SwitchToMode "Normal"; }
        bind "Up" { MoveFocus "Up"; SwitchToMode "Normal"; }
        bind "h" { MoveFocus "Left"; SwitchToMode "Normal"; }
        bind "l" { MoveFocus "Right"; SwitchToMode "Normal"; }
        bind "j" { MoveFocus "Down"; SwitchToMode "Normal"; }
        bind "k" { MoveFocus "Up"; SwitchToMode "Normal"; }
        bind "o" { FocusNextPane; SwitchToMode "Normal"; }
        bind "d" { Detach; }
        bind "x" { CloseFocus; SwitchToMode "Normal"; }

        bind "1" { GoToTab 1; SwitchToMode "Normal"; }
        bind "2" { GoToTab 2; SwitchToMode "Normal"; }
        bind "3" { GoToTab 3; SwitchToMode "Normal"; }
        bind "4" { GoToTab 4; SwitchToMode "Normal"; }
        bind "5" { GoToTab 5; SwitchToMode "Normal"; }
        bind "6" { GoToTab 6; SwitchToMode "Normal"; }
        bind "7" { GoToTab 7; SwitchToMode "Normal"; }
        bind "8" { GoToTab 8; SwitchToMode "Normal"; }
        bind "9" { GoToTab 9; SwitchToMode "Normal"; }
        bind "Tab" { GoToNextTab; }

        bind "w" { ToggleFloatingPanes; SwitchToMode "Normal"; }
        bind ">" { Resize "Increase"; }
        bind "<" { Resize "Decrease"; }
    }
}
ZELLIJ

cat > ~/.config/zellij/layouts/default.kdl <<'LAYOUT'
layout {
    default_tab_template {
        pane
        pane size=1 borderless=true {
            plugin location="zellij:compact-bar"
        }
    }

    tab

    tab

    tab
}
LAYOUT

## Git config (delta + dracula theme)
cat > ~/.gitconfig <<'GITCFG'
[url "https://"]
    insteadOf = git://

[pull]
    rebase = true

[fetch]
    prune = true

[core]
    autocrlf = input
    pager = delta

[interactive]
    diffFilter = delta --color-only

[delta]
    features = side-by-side line-numbers decorations
    syntax-theme = Dracula
    plus-style = syntax "#003800"
    minus-style = syntax "#3f0001"

[delta "decorations"]
        commit-decoration-style = bold yellow box ul
    file-style = bold yellow ul
    file-decoration-style = none
    hunk-header-decoration-style = cyan box ul

[delta "line-numbers"]
    line-numbers-left-style = cyan
    line-numbers-right-style = cyan
    line-numbers-minus-style = 124
    line-numbers-plus-style = 28
GITCFG

# Prompt user to add their git name/email
echo ""
echo "NOTE: ~/.gitconfig was written without [user] section."
echo "Run the following to set your identity:"
echo "  git config --global user.name 'Your Name'"
echo "  git config --global user.email 'your@email.com'"
echo ""

## FZF key bindings
/opt/homebrew/opt/fzf/install --key-bindings --completion --no-update-rc --no-bash --no-fish 2>/dev/null || true

## Add shell config to .zshrc
MARKER="# >>> tmp-setup shell config >>>"
if ! grep -qF "$MARKER" ~/.zshrc 2>/dev/null; then
cat >> ~/.zshrc <<'ZSHRC'

# >>> tmp-setup shell config >>>
export HOMEBREW_PREFIX=/opt/homebrew
export PATH=${HOMEBREW_PREFIX}/bin:${HOMEBREW_PREFIX}/opt/gnu-sed/libexec/gnubin:${HOMEBREW_PREFIX}/opt/gnu-tar/libexec/gnubin:${HOMEBREW_PREFIX}/opt/coreutils/libexec/gnubin:$PATH
export PNPM_HOME="$HOME/Library/pnpm"
export PATH=$PNPM_HOME:$PATH
export TERM=xterm-ghostty

# zsh completions
fpath=(~/.zsh-completions/src $fpath)
fpath=(/opt/homebrew/share/zsh/site-functions $fpath)

# zsh syntax highlighting
[ -f $HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ] &&
    source $HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# history
SAVEHIST=100000
HISTSIZE=100000
HISTFILE=~/.zsh_history
setopt append_history inc_append_history share_history

# starship prompt
if (( $+commands[starship] )); then
    eval "$(starship init zsh)"
fi

# fzf
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# zoxide (better cd)
if (( $+commands[zoxide] )); then
    eval "$(zoxide init zsh)"
fi

# bat -> cat
if (( $+commands[bat] )); then
    alias cat='bat --paging=never --theme="Nord"'
fi

# eza -> ls
if (( $+commands[eza] )); then
    alias ls='eza -G  --color auto --icons -a -s type'
    alias ll='eza -l --color always --icons -a -s new'
    alias tree='eza -T --color always --icons -a -s new'
fi

# git aliases
alias g='git'
alias gb='git branch'
alias gco='git checkout'
alias gd='git diff'
alias gdc='git diff --cached'
alias gl='git pull'
alias gp='git push'
alias gst='git status'

# rg
alias rg='rg --colors path:fg:green --colors match:fg:red'

# compinit
autoload -Uz compinit && compinit -C
# <<< tmp-setup shell config <<<
ZSHRC
fi

echo "Done. Restart your shell or run: source ~/.zshrc"
