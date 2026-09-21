#!/bin/bash
# Limpa o cache que o próprio macOS acumula a cada troca de papel de parede
# (~/Library/Containers/com.apple.wallpaper.agent/.../extension-com.apple.wallpaper.extension.image).
# O daemon roda com poucos privilégios e não consegue limpar essa pasta sozinho
# (o container pertence a outro processo do sistema) — rode este script pelo
# seu terminal de vez em quando, ou quando notar o disco apertado.
CACHE="$HOME/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches/com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image"

if [ ! -d "$CACHE" ]; then
    echo "Pasta de cache não encontrada (pode já estar limpa, ou o caminho mudou nesta versão do macOS)."
    exit 0
fi

listing=$(find "$CACHE" -type f 2>&1)
if echo "$listing" | grep -qi "not permitted"; then
    echo "Sem permissão para acessar essa pasta a partir daqui."
    echo "Rode este script direto no Terminal.app — lá costuma ter o acesso necessário."
    exit 1
fi

count=$(echo "$listing" | grep -c .)
before=$(du -sh "$CACHE" 2>/dev/null | cut -f1)

echo "Cache do wallpaper: $count arquivos, $before."
if [ "$count" -eq 0 ]; then
    echo "Nada para limpar."
    exit 0
fi

find "$CACHE" -type f -delete
echo "Limpo."
