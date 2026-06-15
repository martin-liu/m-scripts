import subprocess
import tempfile
import threading
from pathlib import Path
from talon import Module, actions, cron

mod = Module()

SCRIPT = Path(__file__).resolve().parent / "bin" / "dictate-terminal.sh"
_dictating = False


def _paste_unicode(text: str):
    """Paste Unicode text using AppleScript to avoid pbcopy encoding issues."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        f.write(text)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                f'set the clipboard to (read POSIX file "{tmp_path}" as «class utf8»)',
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            actions.app.notify("Dictation", f"Paste failed: {result.stderr[:100]}")
            return
        actions.sleep("100ms")
        actions.key("cmd-v")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _finish(text: str):
    """Called on main thread after dictation script completes."""
    global _dictating

    try:
        if text:
            _paste_unicode(text)

        # Small delay to ensure paste is complete before waking Talon
        actions.sleep("300ms")
        actions.speech.enable()

    finally:
        _dictating = False


def _run_script():
    """Run dictation script in background thread."""
    try:
        result = subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        text = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        text = ""
    finally:
        # Always callback to main thread, even on exception
        cron.after("0ms", lambda: _finish(text))


@mod.action_class
class Actions:
    def terminal_dictate():
        """Sleep Talon, run external dictation, paste result, wake Talon."""
        global _dictating

        if _dictating:
            return

        _dictating = True

        # Disable speech recognition immediately
        # This stops Talon from processing any audio including subtitles
        actions.speech.disable()

        # Run dictation while Talon remains asleep
        thread = threading.Thread(target=_run_script, daemon=True)
        thread.start()
