#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title pdf emacs
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 🤖

# Documentation:
# @raycast.description Open pdf url in emacs
# @raycast.author Martin Liu

url=$(pbpaste)

if [[ -n $url ]]; then
    if [[ $url =~ arxiv\.org/pdf/([0-9]+\.[0-9]+) ]]; then
        filename="${BASH_REMATCH[1]}"
        extension="pdf"
    else
        filename=$(basename "$url")
        extension="${filename##*.}"
    fi

    if [[ $extension == "pdf" ]]; then
        if curl --head --silent --fail $url &> /dev/null; then
            echo "Downloading..."
            mkdir -p ~/Downloads/pdf && curl -o ~/Downloads/pdf/$filename $url && \
                echo "Downloading..." && \
                emacsclient -n -a "" ~/Downloads/pdf/$filename
        else
            echo "Not able download"
        fi
    else
        echo "Not a PDF"
    fi
fi
