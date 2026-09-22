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

# "Acesso Total ao Disco" não tem prompt clicável — só dá pra conceder
# manualmente, e arrastando o binário REAL (não um symlink tipo "python3":
# o TCC não segue o link, precisa ser "python3.14" mesmo). Isso não afeta
# o wallpaper em si (já rodando acima); só a limpeza automática do cache
# de wallpaper do macOS fica desativada até conceder. Revela o arquivo já
# selecionado no Finder + abre a janela certa + explica em um diálogo, pra
# a única coisa que sobra pro usuário ser arrastar de uma janela pra outra.
CACHE_DIR="$HOME/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches/com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image"
if find "$CACHE_DIR" -maxdepth 1 2>&1 | grep -qi "not permitted"; then
    PYTHON_REAL="$(realpath "$DIR/venv/bin/python3" 2>/dev/null)"
    echo ""
    echo "Sem \"Acesso Total ao Disco\", o cache de wallpaper do macOS não é limpo sozinho (o resto funciona normalmente)."
    if [ -n "$PYTHON_REAL" ]; then
        PYTHON_NAME="$(basename "$PYTHON_REAL")"
        echo "Abrindo o Finder e os Ajustes — arraste \"$PYTHON_NAME\" para a lista de Acesso Total ao Disco."

        open -R "$PYTHON_REAL" 2>/dev/null || true
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || \
            open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles" 2>/dev/null || true

        MSG=$'Para o wallpaper_btop limpar sozinho o cache de papel de parede do macOS, arraste o arquivo\n\n  '"$PYTHON_NAME"$'\n\n(já selecionado no Finder) para dentro da lista de Acesso Total ao Disco que acabou de abrir nos Ajustes.\n\nIsso é opcional — o wallpaper já está funcionando normalmente sem isso.'
        osascript -e "display dialog \"$MSG\" buttons {\"Entendi\"} default button \"Entendi\" with title \"wallpaper_btop\" with icon note giving up after 120" \
            2>/dev/null || true
    fi
fi
