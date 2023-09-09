#!/bin/bash

cd "$(dirname "$0")"

for cast_file in *.cast; do
    echo "Exporting $cast_file"
    base_name="${cast_file%.*}"
    agg "$cast_file" "../assets/$base_name.gif" --theme=monokai --font-size=18
    cp -f "../assets/$base_name.gif" "../docs/$base_name.gif"
    cp -f "../assets/$base_name.gif" "../docs/assets/$base_name.gif"
done

echo "All exported and copied!"


# Generate slideshow

gifsicle --loop --colors 256 \
  ../assets/explain_what_you_want.gif \
  ../assets/describe_what_you_are_looking_for.gif \
  ../assets/incorporate_regex.gif \
  > ../assets/demo-slideshow.gif

cp -f ../assets/demo-slideshow.gif ../docs/demo-slideshow.gif
cp -f ../assets/demo-slideshow.gif ../docs/assets/demo-slideshow.gif
