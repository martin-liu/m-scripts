read -r -d '' pairs <<EOF
[
  ["$DIR/shell/config/alacritty.toml", "$HOME/.config/alacritty/alacritty.toml"],
  ["$DIR/shell/config/zellij/config.kdl", "$HOME/.config/zellij/config.kdl"],
  ["$DIR/shell/config/zellij/layouts/default.kdl", "$HOME/.config/zellij/layouts/default.kdl"],
  ["$DIR/shell/config/vimrc", "$HOME/.vimrc"],
  ["$DIR/shell/config/gitconfig", "$HOME/.gitconfig"]
]
EOF

python3 - $pairs <<EoF
import os, sys, json, filecmp, shutil

pairs = json.loads(sys.argv[1])
for source, target in pairs:
    if not os.path.exists(target) or not filecmp.cmp(source, target):
        print("Detected change, copying {} to {}".format(source, target))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
EoF
