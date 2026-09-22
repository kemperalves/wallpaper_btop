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

# "Acesso Total ao Disco" não tem prompt clicável — só dá pra conceder pelos
# Ajustes, manualmente. Isso não afeta o wallpaper em si (que já está
# rodando acima); só a limpeza automática do cache de wallpaper do macOS
# fica desativada até você conceder. Avisa e facilita, sem forçar nada.
CACHE_DIR="$HOME/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches/com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image"
if find "$CACHE_DIR" -maxdepth 1 2>&1 | grep -qi "not permitted"; then
    PYTHON_REAL="$(realpath "$DIR/venv/bin/python3" 2>/dev/null)"
    echo ""
    echo "Aviso: sem \"Acesso Total ao Disco\", o cache de wallpaper do macOS não é limpo sozinho (o resto funciona normalmente)."
    if [ -n "$PYTHON_REAL" ]; then
        echo "$PYTHON_REAL" | pbcopy 2>/dev/null && \
            echo "Pra ativar: Ajustes > Privacidade e Segurança > Acesso Total ao Disco > + > Cmd+Shift+G > colar (já copiado):" || \
            echo "Pra ativar: Ajustes > Privacidade e Segurança > Acesso Total ao Disco > + > Cmd+Shift+G > colar:"
        echo "  $PYTHON_REAL"
    fi
    echo "Ou rode: open \"x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles\""
fi
