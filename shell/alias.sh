### Alias

## brew in M1 mac
if [[ $(uname -p) == 'arm' || $(uname -p) == 'arm64' ]]; then
    alias ibrew='arch -x86_64 /usr/local/bin/brew'
fi

## bat <-> cat
if _has bat; then
    unalias -m 'cat'
    alias cat='bat --paging=never --theme="Nord"'
fi

# eza <-> ls
if _has eza; then
    unalias -m 'll'
    unalias -m 'l'
    unalias -m 'la'
    unalias -m 'ls'
    alias ls='eza -G  --color auto --icons -a -s type'
    alias ll='eza -l --color always --icons -a -s new'
    alias tree='eza -T --color always --icons -a -s new'
    alias ltr='eza -lgr -sold'
fi

# okta
if _has aws-okta; then
    alias ae='aws-okta exec'
fi

# Interactive/verbose commands.
alias mv='mv -i'
for c in cp rm chmod chown rename; do
  alias $c="$c -v"
done

# ssh
alias ssh='TERM=xterm-256color ssh'
# vim
alias vi='TERM=xterm-256color vim'

# git
alias g='git'
alias gb='git branch'
alias gbd='git branch -D'
alias gco='git checkout'
alias gd='git diff'
alias gdc='git diff --cached'
alias gl='git pull'
alias gp='git push'
alias gr='git remote'
alias grv='git remote -v'
alias gst='git status'

# rg
alias rg='rg --colors path:fg:green --colors match:fg:red'

# Use GNU du if available
if _has gdu; then
  alias du=gdu
  function dut() { du -a -h --exclude=.git $@ * .* | sort -rh | head -n 20 }
else
  function dut() { du -h $@ * .* | sort -rh | head -n 20 }
fi

# k8s
alias k='kubectl'
alias kk='kubectl kustomize'

# What's using that TCP port?
if [ "$(uname -s)" = "Darwin" ]; then
  alias netwhat='sudo lsof -Pni tcp'
else
  alias netwhat='lsof -i +c 40'
fi
