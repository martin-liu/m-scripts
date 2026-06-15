app.name: Ghostty
mode: command
-

# Character deletion - prefixed to avoid accidental triggers
term delete:
    key(backspace)

term delete <user.edit_count>:
    user.terminal_delete_chars(edit_count)

# Word deletion
chuck word:
    user.terminal_delete_words(1)

chuck <user.edit_count> words:
    user.terminal_delete_words(edit_count)

chuck next word:
    user.terminal_delete_next_words(1)

chuck next <user.edit_count> words:
    user.terminal_delete_next_words(edit_count)

# Line deletion
chuck line:
    user.terminal_clear_line()

clear line:
    user.terminal_clear_line()

chuck start:
    user.terminal_delete_to_start()

chuck end:
    user.terminal_delete_to_end()

# Cursor movement
char left:
    key(left)

char right:
    key(right)

char <user.edit_count> left:
    user.press_key_times("left", edit_count)

char <user.edit_count> right:
    user.press_key_times("right", edit_count)

word left:
    user.terminal_word_left(1)

word right:
    user.terminal_word_right(1)

word <user.edit_count> left:
    user.terminal_word_left(edit_count)

word <user.edit_count> right:
    user.terminal_word_right(edit_count)

line start:
    user.terminal_line_start()

line end:
    user.terminal_line_end()

# Option selection (for menus/lists with up/down arrows)
opt up:
    key(up)

opt down:
    key(down)

# Clipboard
term copy:
    key(cmd-c)

term paste:
    key(cmd-v)

# Undo
term undo:
    user.terminal_undo()

# Submit/cancel
submit:
    key(enter)

term cancel:
    key(escape)
