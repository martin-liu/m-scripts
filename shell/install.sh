#!/bin/bash

brew install \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     starship bat exa navi git-delta `# rust cli tools` \
     fzf tmux reattach-to-user-namespace `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

## delta for git diff, add below to `~/.gitconfig`
#[delta]
#    features = side-by-side line-numbers decorations
#    syntax-theme = Dracula
#    plus-style = syntax "#003800"
#    minus-style = syntax "#3f0001"
#
#[delta "decorations"]
#    commit-decoration-style = bold yellow box ul
#    file-style = bold yellow ul
#    file-decoration-style = none
#    hunk-header-decoration-style = cyan box ul
#
#[delta "line-numbers"]
#    line-numbers-left-style = cyan
#    line-numbers-right-style = cyan
#    line-numbers-minus-style = 124
#    line-numbers-plus-style = 28

## tmux
if cd ~/.tmux/plugins/tpm ; then
    git pull
else
    git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
fi
