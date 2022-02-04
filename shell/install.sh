#!/bin/bash

brew install \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     starship bat exa navi git-delta `# rust cli tools` \
     fzf tmux reattach-to-user-namespace `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

## tmux
if cd ~/.tmux/plugins/tpm ; then
    git pull
else
    git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
fi
