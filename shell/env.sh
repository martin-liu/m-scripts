ulimit -n 10240
export PATH=$PATH:$DIR/bin
export TERM=screen-256color

### use gnu utils, ensure `brew install`
export PATH=${HOMEBREW_PREFIX}/bin:${HOMEBREW_PREFIX}/opt/gnu-sed/libexec/gnubin:${HOMEBREW_PREFIX}/opt/gnu-tar/libexec/gnubin:${HOMEBREW_PREFIX}/opt/coreutils/libexec/gnubin:$PATH

### GO
export PATH=$PATH:$HOME/go/bin

### Latex
export PATH=$PATH:/Library/TeX/texbin
