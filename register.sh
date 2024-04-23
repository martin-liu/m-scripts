#!env zsh

### Get current dir
DIR=$( cd "$( dirname "$0" )" && pwd )

source $DIR/shell/util.sh
source $DIR/shell/env.sh
source $DIR/shell/config.sh
source $DIR/shell/alias.sh
source $DIR/shell/tools.sh
# zsh options at last, otherwise some hooks may cause incorrect state
source $DIR/shell/zsh.sh

# Don't end with errors.
true
