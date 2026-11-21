#!/usr/bin/env bash
# lang: Bash | file: net_recon.sh | target: Linux/macOS
# tag: recon | shell: bash

echo "===== OPEN PORTS ====="
ss -tulnp 2>/dev/null || netstat -tulnp 2>/dev/null
echo ""

echo "===== ESTABLISHED CONNECTIONS ====="
ss -tnp 2>/dev/null || netstat -tnp 2>/dev/null
echo ""

echo "===== ARP TABLE ====="
arp -a
echo ""

echo "===== ROUTING TABLE ====="
ip route 2>/dev/null || route -n 2>/dev/null || netstat -rn
echo ""

echo "===== DNS ====="
cat /etc/resolv.conf 2>/dev/null
echo ""

echo "===== HOSTS FILE ====="
cat /etc/hosts
