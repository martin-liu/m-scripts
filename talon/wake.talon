mode: sleep
-

# Fallback voice wake (requires saying it twice with silence before/after)
^talon system activate talon system activate$:
    user.talon_wake()

# Catch all other speech in sleep mode to prevent false wakes
<phrase>:
    skip()
