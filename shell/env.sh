ulimit -n 10240

## Auto sync proxy env with macOS system proxy (e.g. Hiddify)
# Reads current system proxy settings and exports http_proxy, https_proxy
# and ALL_PROXY when enabled. Unsets them when disabled.
_m_sync_system_proxy() {
  [[ "$(uname -s)" == "Darwin" ]] || return 0

  local info
  info=$(scutil --proxy 2>/dev/null) || return 0

  _m_scutil_proxy_value() {
    local key="$1"
    echo "$info" | sed -n "s/^[[:space:]]*${key}[[:space:]]*:[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/\1/p" | head -n 1
  }

  local http_enable=$(_m_scutil_proxy_value HTTPEnable)
  local http_host=$(_m_scutil_proxy_value HTTPProxy)
  local http_port=$(_m_scutil_proxy_value HTTPPort)
  local https_enable=$(_m_scutil_proxy_value HTTPSEnable)
  local https_host=$(_m_scutil_proxy_value HTTPSProxy)
  local https_port=$(_m_scutil_proxy_value HTTPSPort)
  local socks_enable=$(_m_scutil_proxy_value SOCKSEnable)
  local socks_host=$(_m_scutil_proxy_value SOCKSProxy)
  local socks_port=$(_m_scutil_proxy_value SOCKSPort)

  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

  if [[ "$http_enable" == "1" && -n "$http_host" && -n "$http_port" ]]; then
    export http_proxy="http://${http_host}:${http_port}"
    export HTTP_PROXY="$http_proxy"
  fi

  if [[ "$https_enable" == "1" && -n "$https_host" && -n "$https_port" ]]; then
    export https_proxy="http://${https_host}:${https_port}"
    export HTTPS_PROXY="$https_proxy"
  fi

  if [[ "$socks_enable" == "1" && -n "$socks_host" && -n "$socks_port" ]]; then
    export ALL_PROXY="socks5://${socks_host}:${socks_port}"
  fi
}
_m_sync_system_proxy

_force_prepend_to_path /usr/local/sbin
_force_prepend_to_path /usr/local/bin
_append_to_path /usr/sbin

export PATH=$PATH:$DIR/bin
# support 24-bit true color
export TERM=xterm-ghostty

### use gnu utils, ensure `brew install`
export HOMEBREW_PREFIX=/opt/homebrew
export PATH=${HOMEBREW_PREFIX}/bin:${HOMEBREW_PREFIX}/opt/gnu-sed/libexec/gnubin:${HOMEBREW_PREFIX}/opt/gnu-tar/libexec/gnubin:${HOMEBREW_PREFIX}/opt/coreutils/libexec/gnubin:$PATH

### Rust
export PATH=$PATH:$HOME/.cargo/bin

### GO
export PATH=$PATH:$HOME/go/bin

### Latex
export PATH=$PATH:/Library/TeX/texbin

### Rancher Desktop
export PATH=$PATH:$HOME/.rd/bin

### Pnpm
export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
export PATH=$PATH:$PNPM_HOME/bin

### Python
export PATH=$PATH:$HOME/.local/bin
