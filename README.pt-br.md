# wallpaper_btop

**[English](README.md)** | Português

Gera um dashboard estilo **btop** (CPU, memória, disco, rede, processos) e
define como papel de parede do macOS, atualizando em loop. Não é uma live
wallpaper animada de verdade (o macOS não tem esse conceito nativo) — é uma
imagem redesenhada e trocada periodicamente, o que na prática fica "vivo".

Detecta monitores em pé (retrato) automaticamente e usa um layout empilhado
específico para eles — cada `desktop` do System Events recebe a imagem
(paisagem 3840×2160 ou retrato 1080×1920) que combina com seu monitor físico,
identificado por nome via `system_profiler`. Não depende de qual monitor é
"o 2" — se os cabos forem reconectados em outra ordem, a detecção roda de
novo a cada ciclo e se ajusta sozinha.

## Estrutura

```
wallpaper_btop/
├── btop_wallpaper.py                   # script principal (coleta stats, desenha, detecta monitores, troca o wallpaper)
├── venv/                               # ambiente virtual Python (Pillow + psutil) — criado na instalação, não vem no repo
├── local.wallpaperbtop.plist.template  # modelo do LaunchAgent (bin/start.sh gera o .plist real a partir daqui)
├── bin/
│   ├── start.sh                 # liga agora + configura para iniciar sempre no login/reboot
│   ├── stop.sh                  # para agora (volta a ligar sozinho no próximo login)
│   ├── uninstall.sh             # para e remove o auto-start (não volta nem no reboot)
│   └── clean_wallpaper_cache.sh # limpa o cache de wallpaper do macOS (rodar pelo Terminal.app, não daqui)
├── output/                    # só o frame mais recente de cada orientação (frame_..._h.png / _v.png)
└── logs/                      # stdout.log / stderr.log do processo em segundo plano
```

## Instalar (do zero)

Requer macOS com Python 3 e o Xcode Command Line Tools (`xcode-select --install`,
se ainda não tiver). Clone em qualquer pasta — os scripts descobrem o próprio
caminho sozinhos, não precisa ser um lugar específico.

```bash
git clone https://github.com/kemperalves/wallpaper_btop.git
cd wallpaper_btop
python3 -m venv venv
./venv/bin/pip install Pillow psutil
```

## Deixar sempre rodando (inclusive depois de reiniciar o Mac)

```bash
bin/start.sh
```

Isso gera `~/Library/LaunchAgents/local.wallpaperbtop.plist` a partir do
template (com o caminho de onde você clonou o projeto) e registra no
`launchd`. A partir daí o processo:

- inicia sozinho a cada login/boot (`RunAtLoad`);
- é reiniciado automaticamente se cair (`KeepAlive`);
- roda em baixa prioridade de CPU/IO, para não incomodar o resto do sistema.

Rodar `start.sh` de novo a qualquer momento (depois de editar o `.plist`,
por exemplo) recarrega a configuração e reinicia o processo.

## Pausar temporariamente

```bash
bin/stop.sh
```

Para o processo agora. **Volta a ligar sozinho no próximo login/reboot**,
porque o LaunchAgent continua instalado. O papel de parede fica parado no
último frame gerado até você rodar `start.sh` de novo.

## Desligar de vez (não volta nem no reboot)

```bash
bin/uninstall.sh
```

Remove o LaunchAgent do login. Os arquivos do projeto continuam intactos —
para reativar, é só rodar `bin/start.sh` novamente.

## Testar manualmente (sem mexer no serviço)

Gerar um único frame de teste, sem aplicar como wallpaper:

```bash
./venv/bin/python3 btop_wallpaper.py --once             # layout paisagem
./venv/bin/python3 btop_wallpaper.py --once --portrait  # layout retrato
open output/preview.png
```

Rodar em primeiro plano (aplica o wallpaper de verdade, mas só enquanto o
terminal ficar aberto — Ctrl+C para parar):

```bash
./venv/bin/python3 btop_wallpaper.py --interval 5
```

## Configurações

- **Intervalo de atualização**: edite `--interval 5` em
  `local.wallpaperbtop.plist.template` e rode `bin/start.sh` de novo para aplicar.
  Cada troca de wallpaper faz o macOS guardar uma cópia no próprio cache
  dele, que nunca limpa sozinho (~25MB por troca) — no padrão de 5s isso é
  ±300MB/minuto, ~18GB/hora (o dobro se você tiver um monitor em retrato,
  já que aí é uma segunda imagem por ciclo). Foi exatamente isso, rodando
  sem supervisão por horas, que encheu o disco da primeira vez. **Rode
  `bin/clean_wallpaper_cache.sh` pelo Terminal.app com frequência** se
  manter esse padrão — ou aumente o intervalo (60s+ é bem mais tranquilo
  pra esse cache) se preferir não se preocupar com isso.
- **Resolução**: constantes `WIDTH`/`HEIGHT` (paisagem) e
  `PORTRAIT_WIDTH`/`PORTRAIT_HEIGHT` (retrato) no topo de `btop_wallpaper.py`.
- **Monitores considerados em "retrato"**: qualquer desktop cuja resolução
  detectada tenha altura maior que largura. Se a detecção falhar (ex.:
  `system_profiler` indisponível), cai no comportamento antigo — mesma
  imagem paisagem em todos os monitores.
- **Idioma dos textos do dashboard**: `--lang en` (padrão) ou `--lang pt-br`,
  em `local.wallpaperbtop.plist.template`.

## Logs / diagnóstico

```bash
tail -f logs/stdout.log
tail -f logs/stderr.log

# status detalhado no launchd:
launchctl print gui/$(id -u)/local.wallpaperbtop
```

## Voltar ao papel de parede antigo

A qualquer momento, em **Ajustes do Sistema → Papel de parede**, é só
escolher outra imagem — isso não interfere no serviço (ele volta a trocar
no próximo ciclo, a menos que você rode `bin/stop.sh` ou `bin/uninstall.sh`).
