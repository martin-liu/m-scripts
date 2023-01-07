## ZSH configurations
# ZSH-SPECIFIC COMPLETION {{{1

# Add new Zsh Completions repo
fpath=(~/.zsh-completions/src $fpath)

# Add Homebrew site functions
fpath=(/opt/homebrew/share/zsh/site-functions $fpath)

## zsh syntax highlighting
[ -f $HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ] &&
    source $HOMEBREW_PREFIX/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# History control
if [ -w ~/.zsh_history -o -w ~ ]; then
  SAVEHIST=100000
  HISTSIZE=100000
  HISTFILE=~/.zsh_history
fi

# ---------------------------------------------
# The following lines were added by compinstall

zstyle ':completion:*' completer _complete _correct _approximate _prefix
zstyle ':completion:*' completions 1
zstyle ':completion:*' glob 1
zstyle ':completion:*' group-name ''
zstyle ':completion:*:manuals.*' insert-sections true
zstyle ':completion:*' insert-unambiguous false
zstyle ':completion:*' list-colors "di=01;34:ma=43;30"
zstyle ':completion:*' matcher-list '' 'm:{[:lower:]}={[:upper:]}' 'm:{[:lower:][:upper:]}={[:upper:][:lower:]}' 'r:|[._-]=* r:|=*'
zstyle ':completion:*' max-errors 5
zstyle ':completion:*' menu select=0
zstyle ':completion:*:man:*' menu yes select
zstyle ':completion:*' select-prompt %SScrolling active: current selection at %p%s
zstyle ':completion:*:manuals' separate-sections true
zstyle ':completion:*' use-perl true
zstyle :compinstall filename '/Users/ian/.zshrc'

autoload -Uz compinit
compinit -u
# End of lines added by compinstall
# ---------------------------------------------

# Ignore useless files, like .pyc.
zstyle ':completion:*:(all-|)files' ignored-patterns '(|*/).pyc'

# Completing process IDs with menu selection.
zstyle ':completion:*:*:kill:*' menu yes select
zstyle ':completion:*:kill:*'   force-list always

# Load menu-style completion.
zmodload -i zsh/complist
bindkey -M menuselect '^M' accept

# This inserts a tab after completing a redirect. You want this.
# (Source: http://www.zsh.org/mla/users/2006/msg00690.html)
self-insert-redir() {
integer l=$#LBUFFER
zle self-insert
(( $l >= $#LBUFFER )) && LBUFFER[-1]=" $LBUFFER[-1]"
}
zle -N self-insert-redir
for op in \| \< \> \& ; do
  bindkey "$op" self-insert-redir
done

# Automatically quote URLs when pasted
autoload -U url-quote-magic
zle -N self-insert url-quote-magic

# ZSH KEYBINDINGS {{{1

# First, primarily use emacs key bindings
bindkey -e

# One keystroke to cd ..
bindkey -s '\eu' '\eq^Ucd ..; ls^M'
bindkey -s '¨' '\eq^Ucd ..; ls^M'

# Smart less-adder
bindkey -s "\el" "^E 2>&1|less^M"
bindkey -s "¬" "^E 2>&1|less^M"

# This lets me use ^Z to toggle between open text editors.
bindkey -s '^Z' '^Ufg^M'

# More custom bindings
bindkey "^O" copy-prev-shell-word
bindkey "^Q" push-line
bindkey "^T" history-incremental-search-forward
bindkey "ESC-." insert-last-word

# Edit the current command line with Meta-e
autoload -U edit-command-line
zle -N edit-command-line
bindkey '\ee' edit-command-line
bindkey '´' edit-command-line

# Let ^W delete to slashes - zsh-users list, 4 Nov 2005
# (I can't live without this)
backward-delete-to-slash() {
  local WORDCHARS=${WORDCHARS//\//}
  zle .backward-delete-word
}
zle -N backward-delete-to-slash
bindkey "^W" backward-delete-to-slash

# AUTO_PUSHD is set so we can always use popd
bindkey -s '\ep' '^Upopd >/dev/null; dirs -v^M'
bindkey -s 'π' '^Upopd >/dev/null; dirs -v^M'

# ZSH OPTIONS {{{1

# Changing Directories
unsetopt auto_cd
setopt auto_pushd
setopt pushd_ignore_dups
setopt pushd_silent

# Completion
setopt auto_param_slash
setopt complete_in_word
setopt glob_complete
setopt list_beep
setopt list_packed
setopt list_rows_first
setopt no_beep

# History
setopt append_history
setopt inc_append_history
setopt share_history
unsetopt bang_hist
unsetopt extended_history

# Job Control
setopt notify
