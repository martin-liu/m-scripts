#!env zsh

### use gnu utils, ensure `brew install`
export PATH=/usr/local/opt/gnu-sed/libexec/gnubin:/usr/local/opt/gnu-tar/libexec/gnubin:/usr/local/opt/coreutils/libexec/gnubin:$PATH

### Get current dir
DIR=$( cd "$( dirname "$0" )" && pwd )
export PATH=$PATH:$DIR/bin
export TERM=screen-256color

## Languages
### GO
export GOPATH=~/martin/code/go
export PATH=$PATH:$GOPATH/bin

source $DIR/shell/tools.sh
source $DIR/shell/util.sh
