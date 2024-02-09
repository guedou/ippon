#!/usr/bin/bash
source /home/ippon/ippon.git/.venv/bin/activate
ippon sync
ippon logo
ippon build
sudo killall -9 ippon
ippon view &
