from talon import Module, Context, actions

mod = Module()
ctx = Context()

mod.list("edit_count", desc="Small repeat counts for terminal editing")

ctx.lists["user.edit_count"] = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


@mod.capture(rule="{user.edit_count}")
def edit_count(m) -> int:
    return int(m.edit_count)


@mod.action_class
class Actions:
    def press_key_times(key_name: str, count: int):
        """Press a key multiple times."""
        for _ in range(count):
            actions.key(key_name)

    def terminal_delete_chars(count: int):
        """Delete N characters backward."""
        for _ in range(count):
            actions.key("backspace")

    def terminal_delete_words(count: int):
        """Delete N previous words using readline ctrl-w."""
        for _ in range(count):
            actions.key("ctrl-w")

    def terminal_delete_next_words(count: int):
        """Delete N next words using readline alt-d."""
        for _ in range(count):
            actions.key("alt-d")

    def terminal_word_left(count: int):
        """Move left by N words."""
        for _ in range(count):
            actions.key("alt-b")

    def terminal_word_right(count: int):
        """Move right by N words."""
        for _ in range(count):
            actions.key("alt-f")

    def terminal_clear_line():
        """Clear the whole current input line."""
        actions.key("ctrl-a")
        actions.key("ctrl-k")

    def terminal_delete_to_start():
        """Delete from cursor to start of line."""
        actions.key("ctrl-u")

    def terminal_delete_to_end():
        """Delete from cursor to end of line."""
        actions.key("ctrl-k")

    def terminal_line_start():
        """Move cursor to start of input line."""
        actions.key("ctrl-a")

    def terminal_line_end():
        """Move cursor to end of input line."""
        actions.key("ctrl-e")

    def terminal_undo():
        """Undo in readline-style terminal input."""
        actions.key("ctrl-x")
        actions.key("ctrl-u")
