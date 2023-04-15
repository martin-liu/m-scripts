#!/bin/bash

# install homebrew
if [[ ! $(command -v brew) ]] ; then
     echo 'Installing Homebrew...'
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
     echo 'Updating Homebrew...'
     brew update
fi

## Alacritty terminal emulator
brew install --cask alacritty

## tools
brew install \
     pyenv `# envs` \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     rustup rust-analyzer starship ripgrep bat exa git-delta zellij tealdeer dust bottom fd `# rust cli tools` \
     hr git fzf zsh-syntax-highlighting libvterm graphviz tree-sitter pandoc `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code-nerd-font

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
brew tap d12frosted/emacs-plus && \
    brew install emacs-plus@29 --with-native-comp --with-poll --with-debug && \
    ln -sf /opt/homebrew/opt/emacs-plus@29/Emacs.app /Applications

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
     git clone --depth 1 https://github.com/martin-liu/.doom.d $HOME/.doom.d
     $HOME/.emacs.d/bin/doom sync
fi

## zsh-completion
echo "Updating common Zsh completions..."
rm -rf ~/.zsh-completions ~/.zcompdump
git clone --quiet --depth=1 https://github.com/zsh-users/zsh-completions ~/.zsh-completions
