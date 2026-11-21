#!/usr/bin/env bash
# lang: Bash | file: user_enum.sh | target: Linux/macOS
# tag: recon | shell: bash

echo "===== CURRENT USER ====="
id
whoami
echo ""

echo "===== ALL USERS ====="
cat /etc/passwd | grep -v "nologin\|false" | cut -d: -f1,3,6,7
echo ""

echo "===== SUDOERS / SUDO ACCESS ====="
sudo -l 2>/dev/null
echo ""

echo "===== GROUPS ====="
cat /etc/group | grep -v "^#"
echo ""

echo "===== LOGGED IN USERS ====="
who
w
echo ""

echo "===== LAST LOGINS ====="
last -n 20
