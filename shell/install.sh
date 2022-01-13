#!/bin/bash

brew install starship fzf bat exa tmux reattach-to-user-namespace

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

## delta for git diff
brew install git-delta
## and add below to `~/.gitconfig`
# [core]
#   pager = delta
# [interactive]
#   diffFilter = delta --color-only
# [delta]
#   side-by-side = true
#   line-numbers-left-format = ""
#   line-numbers-right-format = "│ "
#   syntax-theme = Nord

## tmux
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
