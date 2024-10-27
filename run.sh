#!/bin/sh

SHARE_DIR=/share/srt

# 기존 /share/srt 디렉토리가 있으면 삭제합니다.
if [ -d "$SHARE_DIR" ]; then
    rm -rf "$SHARE_DIR"

echo "[Info] mkdir!"
fi
# 새로운 /share/srt 디렉토리를 생성합니다.
mkdir -p $SHARE_DIR
mkdir -p $SHARE_DIR/templates

echo "[Info] mv /app.py!"
# /kocom.conf 파일과 /kocom.py 파일을 /share/kocom 디렉토리로 이동시킵니다.
mv /app.py $SHARE_DIR
mv /templates/index.html $SHARE_DIR

echo "[Info] Run srt macro!"
cd $SHARE_DIR
python3 $SHARE_DIR/app.py

# for dev
while true; do echo "still live"; sleep 100; done
