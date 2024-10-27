#!/bin/sh
ps ax | grep app.py | grep -v grep | awk '{print "kill " $1}' | sh