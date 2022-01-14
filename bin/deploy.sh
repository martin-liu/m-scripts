#!/bin/bash

DIR=$( cd "$( dirname "$0" )" && pwd )

pushd $DIR/../

cargo build --release && cp target/release/m /usr/local/bin

popd
