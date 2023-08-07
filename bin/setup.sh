#!/bin/bash

DIR=$( cd "$( dirname "$0" )/.." && pwd )

# add register to zshrc
grep -qxF "source $DIR/register.sh" ~/.zshrc || echo "source $DIR/register.sh" >> ~/.zshrc

# install tools
zsh $DIR/shell/install.sh

# build cli
pushd $DIR
cargo build --release && cp target/release/m bin/
popd
