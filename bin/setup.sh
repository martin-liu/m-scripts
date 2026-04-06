#!/bin/bash

# Usage: setup.sh [--lite]
# --lite: shell + theme + AI coding tools only (no emacs, latex, rust build, etc.)

DIR=$( cd "$( dirname "$0" )/.." && pwd )

# add register to zshrc
grep -qxF "source $DIR/register.sh" ~/.zshrc || echo "source $DIR/register.sh" >> ~/.zshrc

# install tools (pass --lite flag through if present)
zsh $DIR/shell/install.sh "$@"

# build cli (skip in lite mode)
if [[ "$1" != "--lite" ]]; then
    pushd $DIR
    cargo build --release && cp target/release/m bin/
    popd
fi
