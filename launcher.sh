#!/usr/bin/bash
source /home/ippon/ippon.git/.venv/bin/activate
ippon view | systemd-cat -t ippon -p info
