#!/bin/bash
# Instala/liga o wallpaper_btop como LaunchAgent: roda agora e sempre no login/reboot.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="local.wallpaperbtop"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_N=$(id -u)

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
# O plist não aceita $HOME/variáveis nos caminhos — gera a partir do
# template substituindo pelo caminho real de onde este projeto está.
sed "s|__DIR__|$DIR|g" "$DIR/$LABEL.plist.template" > "$PLIST_DST"

launchctl enable "gui/$UID_N/$LABEL" >/dev/null 2>&1 || true
if ! launchctl bootstrap "gui/$UID_N" "$PLIST_DST" 2>/dev/null; then
    launchctl kickstart -k "gui/$UID_N/$LABEL"
fi

echo "wallpaper_btop rodando e configurado para iniciar automaticamente no login."
