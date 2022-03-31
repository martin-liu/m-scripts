read -r -d '' pairs <<EOF
[
  ["$DIR/shell/config/alacritty.yml", "$HOME/.config/alacritty/alacritty.yml"],
  ["$DIR/shell/config/tmux.conf", "$HOME/.tmux.conf"],
  ["$DIR/shell/config/gitconfig", "$HOME/.gitconfig"]
]
EOF

python3 - $pairs <<EoF
import sys, json, filecmp, shutil

pairs = json.loads(sys.argv[1])
for source, target in pairs:
    if not filecmp.cmp(source, target):
        print("Detected change, copying {} to {}".format(source, target))
        shutil.copyfile(source, target)
EoF
