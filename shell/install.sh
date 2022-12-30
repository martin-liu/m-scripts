#!/bin/bash

## emacs
brew tap d12frosted/emacs-plus && \
    brew install emacs-plus@29 --with-native-comp --with-poll --with-debug

## Alacritty terminal emulator
brew install --cask alacritty

## tools
brew install \
     pyenv jenv `# envs` \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     starship ripgrep bat exa navi git-delta zellij `# rust cli tools` \
     fzf tmux reattach-to-user-namespace graphviz `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

## Latex
brew install --cask basictex
## sudo tlmgr update --self && sudo tlmgr install dvipng

## tmux
if cd ~/.tmux/plugins/tpm ; then
    git pull
else
    git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
fi
