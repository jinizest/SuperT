#!/bin/sh
mkdir logs 2>/dev/null
nohup python3 -u app.py > logs/srt.log 2>&1 & sleep 1 ; tail -100f logs/srt.log