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

## navi for
if exists navi; then
    eval "$(navi widget zsh)"
fi


## FZF for fuzzy search history
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

### Alias

## The fuck
if exists thefuck; then
    alias fuck='eval $(thefuck $(fc -ln -1 | tail -n 1)); fc -R'
fi

## hub
if exists hub; then
    alias git=hub
fi

## bat <-> cat
if exists bat; then
    unalias -m 'cat'
    alias cat='bat --paging=never --theme="Nord"'
fi

# exa <-> ls
if exists exa; then
    unalias -m 'll'
    unalias -m 'l'
    unalias -m 'la'
    unalias -m 'ls'
    alias ls='exa -G  --color auto --icons -a -s type'
    alias ll='exa -l --color always --icons -a -s new'
fi

# okta
if exists aws-okta; then
    alias ae='aws-okta exec'
fi
