#!/bin/bash

cd "$(dirname "$0")"

for cast_file in *.cast; do
    echo "Exporting $cast_file"
    base_name="${cast_file%.*}"
    agg "$cast_file" "../assets/$base_name.gif"
    cp -f "../assets/$base_name.gif" "../docs/$base_name.gif"
    cp -f "../assets/$base_name.gif" "../docs/assets/$base_name.gif"
done

echo "All exported and copied!"
