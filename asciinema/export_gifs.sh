#!/bin/bash
#
#
#



title_slide() {
    local title=$1
    local subtitle=$2

    local resolution="832x605"
    local bgcolor="#222c34"
    local fgcolor="#FFFFFF"

    convert -size $resolution xc:"$bgcolor" \
        -gravity Center \
        -fill "$fgcolor" \
        -pointsize 30 -annotate 0 "$title" \
        -pointsize 35 -annotate +0+40 "$subtitle" \
        GIF:-
}


title_gif() {
    local delay=$1
    local title=$2
    local subtitle=$3

    gifsicle --delay $delay <(title_slide "$title" "$subtitle")
}


cd "$(dirname "$0")"

for cast_file in *.cast; do
    echo "Exporting $cast_file"
    base_name="${cast_file%.*}"
    agg "$cast_file" "../assets/$base_name.gif" --theme=monokai --font-size=18
    cp -f "../assets/$base_name.gif" "../docs/$base_name.gif"
    cp -f "../assets/$base_name.gif" "../docs/assets/$base_name.gif"
done

echo "All exported and copied!"


gifsicle  --loop --colors 256 \
   <(title_gif 150 "Use Case 1" "Explain what you are trying to do" "title_1.gif") \
   ../assets/explain_what_you_want.gif \
   <(title_gif 150 "Use Case 2" "Describe what you are looking for" "title_1.gif") \
   ../assets/describe_what_you_are_looking_for.gif \
   <(title_gif 150 "Use Case 3" "Incorporate regular expressions" "title_1.gif") \
   ../assets/incorporate_regex.gif \
  > ../assets/demo-slideshow.gif

cp -f ../assets/demo-slideshow.gif ../docs/demo-slideshow.gif
cp -f ../assets/demo-slideshow.gif ../docs/assets/demo-slideshow.gif
