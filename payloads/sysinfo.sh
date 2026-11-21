#!/usr/bin/env bash
# lang: Bash | file: sysinfo.sh | target: Linux/macOS
# tag: recon | shell: bash

echo "===== SYSTEM INFO ====="
echo "Hostname : $(hostname)"
echo "User     : $(whoami)"
echo "OS       : $(uname -a)"
echo "Uptime   : $(uptime -p 2>/dev/null || uptime)"
echo ""

echo "===== CPU ====="
lscpu 2>/dev/null || sysctl -n machdep.cpu.brand_string 2>/dev/null
echo ""

echo "===== MEMORY ====="
free -h 2>/dev/null || vm_stat 2>/dev/null
echo ""

echo "===== DISK ====="
df -h
echo ""

echo "===== PUBLIC IP ====="
curl -s https://api.ipify.org && echo
echo ""

echo "===== LOCAL IPs ====="
ip addr 2>/dev/null || ifconfig
