ulimit -n 10240

_force_prepend_to_path /usr/local/sbin
_force_prepend_to_path /usr/local/bin
_append_to_path /usr/sbin

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

### Rancher Desktop
export PATH=$PATH:$HOME/.rd/bin
