#!/bin/bash
# Para o wallpaper_btop agora. Ele volta a iniciar sozinho no próximo login/reboot
# (use uninstall.sh se quiser que ele fique desligado de vez).
UID_N=$(id -u)
LABEL="local.wallpaperbtop"

if launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null; then
    echo "wallpaper_btop parado."
else
    echo "wallpaper_btop já não estava rodando."
fi
