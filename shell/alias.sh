### Alias

## brew in M1 mac
if [[ $(uname -p) == 'arm' || $(uname -p) == 'arm64' ]]; then
    alias ibrew='arch -x86_64 /usr/local/bin/brew'
fi

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
    alias tree='exa -T --color always --icons -a -s new'
fi

# okta
if exists aws-okta; then
    alias ae='aws-okta exec'
fi
