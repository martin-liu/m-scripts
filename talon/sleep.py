import time

from talon import Module, actions, noise

mod = Module()

_sleeping = False
_last_pop = 0.0


@mod.action_class
class Actions:
    def talon_sleep():
        """Put Talon into real sleep (disable speech recognition)."""
        global _sleeping
        _sleeping = True
        actions.speech.disable()

    def talon_wake():
        """Wake Talon from sleep (enable speech recognition)."""
        global _sleeping
        _sleeping = False
        actions.speech.enable()


def on_pop(active):
    """Wake Talon on two mouth pops close together."""
    global _last_pop

    if not active or not _sleeping:
        return

    now = time.monotonic()
    gap = now - _last_pop
    _last_pop = now

    # Require two pops within 0.1-1 seconds
    if 0.10 <= gap <= 1:
        actions.user.talon_wake()


noise.register("pop", on_pop)
