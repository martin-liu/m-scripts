app.name: Ghostty
mode: command
-

# Navigation - prefixed to avoid accidental triggers
z left: user.zellij_action("move-focus left")
z right: user.zellij_action("move-focus right")
z up: user.zellij_action("move-focus up")
z down: user.zellij_action("move-focus down")

# Tabs - guarded by zellij_go_to_tab() which checks if tab exists
tab one: user.zellij_go_to_tab(1)
tab two: user.zellij_go_to_tab(2)
tab three: user.zellij_go_to_tab(3)
tab four: user.zellij_go_to_tab(4)
tab five: user.zellij_go_to_tab(5)
tab six: user.zellij_go_to_tab(6)
tab seven: user.zellij_go_to_tab(7)
tab eight: user.zellij_go_to_tab(8)
tab nine: user.zellij_go_to_tab(9)
tab ten: user.zellij_go_to_tab(10)
tab last: user.zellij_go_to_last_tab()
tab tab: user.zellij_toggle_tab()

z next: user.zellij_action("go-to-next-tab")
z previous: user.zellij_action("go-to-previous-tab")

# Pane management
z new pane: user.zellij_action("new-pane")
z close pane: user.zellij_action("close-pane")
z full screen: user.zellij_action("toggle-fullscreen")
z floating: user.zellij_action("toggle-floating-panes")
