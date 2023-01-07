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
     rustup rust-analyzer starship ripgrep bat exa navi git-delta zellij tealdeer dust bottom fd `# rust cli tools` \
     fzf libvterm graphviz `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

## Latex
brew install --cask basictex
## sudo tlmgr update --self && sudo tlmgr install dvipng

## Rust
rustup-init -y && rustup component add rust-src rust-analyzer rustfmt clippy
