df -h
apt list --upgradable
sudo systemctl status cron
du -sh /workspace/* | sort -h | tail
free -m
uptime
ls -la /workspace
sudo journalctl -u cron --since yesterday | tail -20
df -h /home
exit
