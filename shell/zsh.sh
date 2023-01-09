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


# See https://gist.github.com/ctechols/ca1035271ad134841284
# Checking the cached .zcompdump file to see if it must be
# regenerated adds a noticable delay to zsh startup.  This little hack restricts
# it to once a day.  It should be pasted into your own completion file.
#
# The globbing is a little complicated here:
# - '#q' is an explicit glob qualifier that makes globbing work within zsh's [[ ]] construct.
# - 'N' makes the glob pattern evaluate to nothing when it doesn't match (rather than throw a globbing error)
# - '.' matches "regular files"
# - 'mh+24' matches files (or directories or whatever) that are older than 24 hours.
() {
    setopt local_options
    setopt extendedglob

    local zcd=${1}
    local zcomp_hours=${2:-24} # how often to regenerate the file
    local lock_timeout=${2:-1} # change this if compinit normally takes longer to run
    local lockfile=${zcd}.lock

    if [ -f ${lockfile} ]; then
        if [[ -f ${lockfile}(#q.NDmm+${lock_timeout}) ]]; then
            (
                echo "${lockfile} has been held by $(< ${lockfile}) for longer than ${lock_timeout} minute(s)."
                echo "This may indicate a problem with compinit"
            ) >&2
        fi
        # Exit if there's a lockfile; another process is handling things
        return
    else
        # Create the lockfile with this shell's PID for debugging
        echo $$ > ${lockfile}
        # Ensure the lockfile is removed
        trap "rm -f ${lockfile}" EXIT
    fi

    autoload -Uz compinit

    if [[ -f ${zcd}(#q.NDmh+${zcomp_hours}) ]]; then
        # The file is old and needs to be regenerated
        compinit
    else
        # The file is either new or does not exist. Either way, -C will handle it correctly
        compinit -C
    fi
} ${ZDOTDIR:-$HOME}/.zcompdump

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
setopt pushdminus

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

# Make sure that the terminal is in application mode when zle is active, since
# only then values from $terminfo are valid
if (( ${+terminfo[smkx]} )) && (( ${+terminfo[rmkx]} )); then
  function zle-line-init() {
    echoti smkx
  }
  function zle-line-finish() {
    echoti rmkx
  }
  zle -N zle-line-init
  zle -N zle-line-finish
fi

# Start typing + [Up-Arrow] - fuzzy find history forward
if [[ -n "${terminfo[kcuu1]}" ]]; then
  autoload -U up-line-or-beginning-search
  zle -N up-line-or-beginning-search

  bindkey -M emacs "${terminfo[kcuu1]}" up-line-or-beginning-search
  bindkey -M viins "${terminfo[kcuu1]}" up-line-or-beginning-search
  bindkey -M vicmd "${terminfo[kcuu1]}" up-line-or-beginning-search
fi
# Start typing + [Down-Arrow] - fuzzy find history backward
if [[ -n "${terminfo[kcud1]}" ]]; then
  autoload -U down-line-or-beginning-search
  zle -N down-line-or-beginning-search

  bindkey -M emacs "${terminfo[kcud1]}" down-line-or-beginning-search
  bindkey -M viins "${terminfo[kcud1]}" down-line-or-beginning-search
  bindkey -M vicmd "${terminfo[kcud1]}" down-line-or-beginning-search
fi

# Job Control
setopt notify


## Directories
setopt autocd
alias -g ...='../..'
alias -g ....='../../..'
alias -g .....='../../../..'
alias -g ......='../../../../..'

alias -- -='cd -'
alias 1='cd -1'
alias 2='cd -2'
alias 3='cd -3'
alias 4='cd -4'
alias 5='cd -5'
alias 6='cd -6'
alias 7='cd -7'
alias 8='cd -8'
alias 9='cd -9'

alias md='mkdir -p'
alias rd=rmdir

function d () {
  if [[ -n $1 ]]; then
    dirs "$@"
  else
    dirs -v | head -n 10
  fi
}
