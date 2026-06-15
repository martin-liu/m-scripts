import subprocess
from talon import Module, actions

ZELLIJ = "/opt/homebrew/bin/zellij"

mod = Module()

# Track tabs for toggle: current and previous (1-based)
_current_tab = 1
_previous_tab = 1


@mod.action_class
class Actions:
    def zellij_action(action: str):
        """Run a zellij action via CLI."""
        subprocess.run([ZELLIJ, "action", *action.split()], check=False)

    def zellij_go_to_tab(tab: int):
        """Switch to a zellij tab by index if it exists."""
        global _current_tab, _previous_tab

        count = _tab_count()

        if count is not None and (tab < 1 or tab > count):
            actions.app.notify(
                "Zellij",
                f"Tab {tab} does not exist; only {count} tab(s)"
            )
            return

        # Update history: previous becomes current, current becomes target
        if tab != _current_tab:
            _previous_tab = _current_tab
            _current_tab = tab

        subprocess.run(
            [ZELLIJ, "action", "go-to-tab", str(tab)],
            check=False,
        )

    def zellij_go_to_last_tab():
        """Switch to the last zellij tab (highest index)."""
        count = _tab_count()
        if count and count > 0:
            actions.user.zellij_go_to_tab(count)

    def zellij_toggle_tab():
        """Toggle between current tab and previously visited tab."""
        global _current_tab, _previous_tab

        # Swap current and previous
        target = _previous_tab

        count = _tab_count()
        if count is not None and (target < 1 or target > count):
            # Previous tab no longer exists, default to tab 1
            target = 1

        # Update history
        _previous_tab = _current_tab
        _current_tab = target

        subprocess.run(
            [ZELLIJ, "action", "go-to-tab", str(target)],
            check=False,
        )


def _tab_count() -> int | None:
    """Return current Zellij tab count, or None if unavailable."""
    try:
        result = subprocess.run(
            [ZELLIJ, "action", "list-tabs"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    lines = [line for line in result.stdout.splitlines() if line.strip()]

    if len(lines) <= 1:
        return 0

    return len(lines) - 1
