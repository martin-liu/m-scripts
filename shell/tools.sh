## starship for prompts
if _has starship; then
    eval "$(starship init zsh)"
fi

## navi for snipets
if _has navi; then
    eval "$(navi widget zsh)"
fi

## FZF for fuzzy search history
if _has fzf; then
    # To install useful key bindings and fuzzy completion:
    [ -f ~/.fzf.zsh ] || $HOMEBREW_PREFIX/opt/fzf/install
    [ -f ~/.fzf.zsh ] && source ~/.fzf.zsh
fi

## zoxide for better cd
if _has zoxide; then
    eval "$(zoxide init zsh)"
fi

### Languages
## Java, commented out due to slow
#if _has jenv; then
#    eval "$(jenv init - zsh)"
#fi

## Python
if _has pyenv; then
    eval "$(pyenv init --path)"
fi

## conda
if [ -f "$HOMEBREW_PREFIX/Caskroom/miniforge/base/etc/profile.d/conda.sh" ]; then
    . "$HOMEBREW_PREFIX/Caskroom/miniforge/base/etc/profile.d/conda.sh"
else
    export PATH="$HOMEBREW_PREFIX/Caskroom/miniforge/base/bin:$PATH"
fi

## NodeJS
