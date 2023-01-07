#!/bin/bash

DIR=$( cd "$( dirname "$0" )/.." && pwd )

# install tools
bash $DIR/shell/install.sh

# add register to zshrc
grep -qxF "source $DIR/register.sh" ~/.zshrc || echo "source $DIR/register.sh" >> ~/.zshrc

# build cli
pushd $DIR
cargo build --release && cp target/release/m /usr/local/bin
popd
