ulimit -n 10240
HISTSIZE=1000000
SAVEHIST=1000000

export PATH=$PATH:$DIR/bin
# support 24-bit true color
export TERM=alacritty-direct

### use gnu utils, ensure `brew install`
export PATH=${HOMEBREW_PREFIX}/bin:${HOMEBREW_PREFIX}/opt/gnu-sed/libexec/gnubin:${HOMEBREW_PREFIX}/opt/gnu-tar/libexec/gnubin:${HOMEBREW_PREFIX}/opt/coreutils/libexec/gnubin:$PATH

### Rust
export PATH=$PATH:$HOME/.cargo/bin

### GO
export PATH=$PATH:$HOME/go/bin

### Latex
export PATH=$PATH:/Library/TeX/texbin
