## auto-attach zellij when opening Ghostty (not already inside zellij)
## On an existing machine with a differently-named session, run once:
##   zellij action rename-session main
if [[ -n "$GHOSTTY_RESOURCES_DIR" ]] && [[ -z "$ZELLIJ" ]]; then
    exec zellij attach main --create
fi

## starship for prompts
if _has starship; then
    eval "$(starship init zsh)"
fi

## zoxide for better cd
if _has zoxide; then
    eval "$(zoxide init zsh)"
fi

## atuin — smart shell history (replaces fzf Ctrl-R with searchable, synced history)
if _has atuin; then
    eval "$(atuin init zsh --disable-up-arrow)"
fi

### Languages
## Java, commented out since it's slow
#if _has jenv; then
#    eval "$(jenv init - zsh)"
#fi


## conda
if [ -f "$HOMEBREW_PREFIX/Caskroom/miniforge/base/etc/profile.d/conda.sh" ]; then
    . "$HOMEBREW_PREFIX/Caskroom/miniforge/base/etc/profile.d/conda.sh"
else
    export PATH="$HOMEBREW_PREFIX/Caskroom/miniforge/base/bin:$PATH"
fi
