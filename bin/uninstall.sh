#!/bin/bash
# Para o wallpaper_btop e remove o início automático (não volta nem no reboot).
# Os arquivos do projeto continuam intactos; para reativar, rode bin/start.sh de novo.
UID_N=$(id -u)
LABEL="local.wallpaperbtop"

launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
launchctl disable "gui/$UID_N/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"

echo "wallpaper_btop desligado e removido do login."
