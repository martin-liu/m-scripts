function exists { command -v $1 &> /dev/null }

## starship for prompts
if exists starship; then
    eval "$(starship init zsh)"
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
