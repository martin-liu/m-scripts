## docker for mac
if exists docker-machine; then
    command="docker-machine env default 2> /dev/null"

    if [ $(docker-machine status default) != "Running" ]; then
        docker-machine start default > /dev/null 2>&1 && eval $(eval $command)
        echo "Starting docker machine 'default' in background..."
    else
        eval $(eval $command)
    fi

fi
