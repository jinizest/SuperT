#!/bin/sh

CONFIG_FILE=/data/options.json
CONFIG_srtapp=/share/srt/app.conf

CONFIG=`cat $CONFIG_FILE`

> $CONFIG_srtapp

for i in $(echo $CONFIG | jq -r 'keys_unsorted | .[]')
do
  if [ $i == "Advanced" ]
  then 
    break
  fi 
  echo "[$i]" >> $CONFIG_srtapp
  echo $CONFIG | jq --arg id "$i" -r '.[$id]|to_entries|map("\(.key)=\(.value|tostring)")|.[]' | sed -e "s/false/False/g" -e "s/true/True/g" >> $CONFIG_srtapp
done