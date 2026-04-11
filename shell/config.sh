# Symlink-based config management
# Runs on every shell load. Idempotent — safe to run multiple times.
# Use `_m_config_uninstall` to cleanly remove all managed symlinks.

# ── Declared link pairs (source|target) ──────────────────────
_M_CONFIG_LINKS=(
    "$DIR/shell/config/ghostty.config|$HOME/.config/ghostty/config"
    "$DIR/shell/config/zellij/config.kdl|$HOME/.config/zellij/config.kdl"
    "$DIR/shell/config/zellij/layouts/default.kdl|$HOME/.config/zellij/layouts/default.kdl"
    "$DIR/shell/config/vimrc|$HOME/.vimrc"
    "$DIR/shell/config/gitconfig|$HOME/.gitconfig"
    "$DIR/shell/config/opencode.json|$HOME/.config/opencode/opencode.json"
    "$DIR/shell/config/oh-my-opencode-slim.json|$HOME/.config/opencode/oh-my-opencode-slim.json"
    "$DIR/shell/config/oh-my-opencode-slim|$HOME/.config/opencode/oh-my-opencode-slim"
    "$DIR/shell/config/claude-settings.json|$HOME/.claude/settings.json"
)

# ── Core: ensure one symlink ─────────────────────────────────
_m_ensure_symlink() {
    local src="$1" target="$2"

    # Source must exist
    [[ -e "$src" ]] || return 0

    # Fast path: already correctly linked
    if [[ -L "$target" && "$(readlink "$target")" == "$src" ]]; then
        return 0
    fi

    # Ensure parent directory exists
    mkdir -p "$(dirname "$target")"

    # Back up existing file or wrong symlink
    if [[ -e "$target" || -L "$target" ]]; then
        mv "$target" "${target}.bak.$(date +%s)"
    fi

    ln -sf "$src" "$target"
}

# ── Install: link all configs + auto-discover skills ─────────
_m_config_install() {
    local pair
    for pair in "${_M_CONFIG_LINKS[@]}"; do
        _m_ensure_symlink "${pair%%|*}" "${pair##*|}"
    done

    # Directory-level symlinks for agent skills
    local skills_src="$DIR/skills"
    local skills_targets=("$HOME/.agents/skills" "$HOME/.claude/skills")
    if [[ -d "$skills_src" ]]; then
        local skill_dir skill_dirs=("$skills_src"/*(/N))
        local skills_dst
        for skills_dst in "${skills_targets[@]}"; do
            mkdir -p "$skills_dst"
            for skill_dir in "${skill_dirs[@]}"; do
                local name="$(basename "$skill_dir")"
                _m_ensure_symlink "$skill_dir" "${skills_dst}/${name}"
            done
        done
    fi
}

# ── Uninstall: remove only symlinks pointing into our repo ───
_m_config_uninstall() {
    local pair target
    for pair in "${_M_CONFIG_LINKS[@]}"; do
        target="${pair##*|}"
        if [[ -L "$target" && "$(readlink "$target")" == "$DIR/"* ]]; then
            rm "$target"
            echo "removed $target"
        fi
    done

    local skills_targets=("$HOME/.agents/skills" "$HOME/.claude/skills")
    local skills_dst
    for skills_dst in "${skills_targets[@]}"; do
        if [[ -d "$skills_dst" ]]; then
            local entry entries=("$skills_dst"/*(@N))
            for entry in "${entries[@]}"; do
                if [[ -L "$entry" && "$(readlink "$entry")" == "$DIR/"* ]]; then
                    rm "$entry"
                    echo "removed $entry"
                fi
            done
        fi
    done
}

# ── Run on shell load ────────────────────────────────────────
_m_config_install
