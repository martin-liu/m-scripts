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
    "$DIR/shell/config/opencode-agents|$HOME/.config/opencode/agents"
    "$DIR/shell/config/opencode-cli.json|$HOME/.config/opencode/cli.json"
    "$DIR/shell/config/opencode-zellij-attention|$HOME/.config/opencode/plugins/zellij-attention"
    "$DIR/shell/config/claude-settings.json|$HOME/.claude/settings.json"
    "$DIR/shell/config/claude-attention.sh|$HOME/.claude/claude-attention.sh"
    "$DIR/shell/config/agent-guidelines.md|$HOME/.config/agents/AGENTS.md"
    "$DIR/shell/config/agent-guidelines.md|$HOME/.claude/CLAUDE.md"
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

# ── Migration: remove only links managed by the old layouts ─────
_m_config_cleanup_legacy_links() {
    local pair target source
    local legacy_config="$HOME/.config/opencode"
    local legacy_v2="$HOME/.config/opencode2/opencode"
    local repo_config="$DIR/shell/config"
    local old_omo="oh-my-""opencode-slim"
    local old_attention="opencode-""zellij-attention.js"
    local legacy_links=(
        "$legacy_config/opencode.json|$repo_config/opencode.json"
        "$legacy_config/plugins/zellij-attention.js|$repo_config/$old_attention"
        "$legacy_config/$old_omo.json|$repo_config/$old_omo.json"
        "$legacy_config/$old_omo|$repo_config/$old_omo"
        "$legacy_v2/opencode.json|$repo_config/opencode2.json"
        "$legacy_v2/agents|$repo_config/opencode2-agents"
        "$legacy_v2/cli.json|$repo_config/opencode2-cli.json"
        "$legacy_v2/plugins/zellij-attention|$repo_config/opencode2-zellij-attention"
    )
    for pair in "${legacy_links[@]}"; do
        target="${pair%%|*}"
        source="${pair##*|}"
        if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
            rm "$target"
            echo "removed $target"
        fi
    done
}

# ── Install: link all configs + auto-discover skills ─────────
_m_config_install() {
    local pair
    _m_config_cleanup_legacy_links
    for pair in "${_M_CONFIG_LINKS[@]}"; do
        _m_ensure_symlink "${pair%%|*}" "${pair##*|}"
    done

    # Directory-level symlinks for agent skills
    local skills_src="$DIR/skills"
    local skills_targets=("$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.config/opencode/skills")
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
    _m_config_cleanup_legacy_links
    for pair in "${_M_CONFIG_LINKS[@]}"; do
        target="${pair##*|}"
        if [[ -L "$target" && "$(readlink "$target")" == "$DIR/"* ]]; then
            rm "$target"
            echo "removed $target"
        fi
    done

    local skills_targets=("$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.config/opencode/skills")
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
