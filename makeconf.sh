#!/bin/sh

CONFIG_FILE=/data/options.json
CONFIG_srtapp=/share/srt/app.conf

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[Error] 설정 파일을 찾을 수 없습니다: $CONFIG_FILE"
    exit 1
fi

CONFIG=`cat $CONFIG_FILE`
echo "[Info] 설정 파일을 성공적으로 읽었습니다: $CONFIG_FILE"

> $CONFIG_srtapp
echo "[Info] $CONFIG_srtapp 파일을 초기화했습니다."

for i in $(echo $CONFIG | jq -r 'keys_unsorted | .[]')
do
  if [ $i == "Advanced" ]
  then 
    echo "[Info] Advanced 섹션에 도달하여 처리를 중단합니다."
    break
  fi 
  echo "[$i]" >> $CONFIG_srtapp
  echo "[Info] [$i] 섹션을 $CONFIG_srtapp에 추가했습니다."
  
  echo $CONFIG | jq --arg id "$i" -r '.[$id]|to_entries|map("\(.key)=\(.value|tostring)")|.[]' | sed -e "s/false/False/g" -e "s/true/True/g" >> $CONFIG_srtapp
  echo "[Info] $i 섹션의 설정값들을 $CONFIG_srtapp에 추가했습니다."
done

echo "[Info] 설정 파일 변환이 완료되었습니다: $CONFIG_srtapp"