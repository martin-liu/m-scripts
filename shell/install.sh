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
# brew install --cask alacritty

## tools
brew install \
     ghostty `# terminal emulator`
     orbstack rye `# envs` \
     coreutils gnu-sed gnu-tar `# gnu utils` \
     rustup rust-analyzer starship zoxide ripgrep bat eza git-delta zellij tealdeer dust bottom fd `# rust cli tools` \
     pyright pnpm cmake hr git fzf zsh-syntax-highlighting libvterm graphviz tree-sitter pandoc yq `# others`

## Fira Font
brew tap homebrew/cask-fonts && brew install font-fira-code

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
    brew install emacs-plus@30 --with-native-comp --with-poll --with-debug && \
    ln -sf /opt/homebrew/opt/emacs-plus@30/Emacs.app /Applications

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

## zsh-completion
echo "Updating common Zsh completions..."
rm -rf ~/.zsh-completions ~/.zcompdump
git clone --quiet --depth=1 https://github.com/zsh-users/zsh-completions ~/.zsh-completions
