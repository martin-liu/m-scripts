function exists { command -v $1 &> /dev/null }

## starship for prompts
if exists starship; then
    eval "$(starship init zsh)"
fi

## alacritty for modern terminal, `brew install alacritty`
if cmp -s ~/.config/alacritty/alacritty.yml "$DIR/shell/config/alacritty.yml" ; then
    :
else
    echo "Detected change, copying $DIR/shell/config/alacritty.yml to ~/.config/alacritty/alacritty.yml"
    mkdir -p ~/.config/alacritty/
    cp $DIR/shell/config/alacritty.yml ~/.config/alacritty/alacritty.yml
fi

## Tmux
if cmp -s ~/.tmux.conf "$DIR/shell/config/tmux.conf" ; then
    :
else
    echo "Detected change, copying $DIR/shell/config/tmux.conf to ~/.tmux.conf"
    cp $DIR/shell/config/tmux.conf ~/.tmux.conf
fi

## gitconfig
if cmp -s ~/.gitconfig "$DIR/shell/config/gitconfig" ; then
    :
else
    echo "Detected change, copying $DIR/shell/config/gitconfig to ~/.gitconfig"
    cp $DIR/shell/config/gitconfig ~/.gitconfig
fi

## navi for snipets
if exists navi; then
    eval "$(navi widget zsh)"
fi

## FZF for fuzzy search history
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

### Languages
## Java
if exists jenv; then
    eval "$(jenv init -)"
fi

## Python
if exists pyenv; then
    eval "$(pyenv init --path)"
fi
