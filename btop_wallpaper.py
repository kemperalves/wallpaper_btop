#!/usr/bin/env python3
"""Renders a btop-styled system dashboard and sets it as the macOS desktop wallpaper on a loop."""

import argparse
import collections
import json
import math
import os
import platform
import plistlib
import re
import resource
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 3840, 2160
PORTRAIT_WIDTH, PORTRAIT_HEIGHT = 1080, 1920
OUT_DIR = Path(__file__).parent / "output"
FONT_PATH = "/System/Library/Fonts/Menlo.ttc"

# Reserva nos cantos superiores para não ficar atrás de widgets do macOS
# (pilha de widgets, ícones do Finder etc.). Ajuste se você reorganizar
# os widgets/ícones da sua tela.
WIDGET_SAFE_LEFT = 480
WIDGET_SAFE_RIGHT = 480
DOCK_SAFE_BOTTOM = 220

# Paleta discreta (inspirada em Nord): tons dessaturados em vez das cores
# vivas de terminal — pensada pra não chamar atenção como papel de parede.
BG = (6, 7, 9)
PANEL_BG = (12, 13, 16)
BORDER_DIM = (26, 29, 34)
TEXT = (172, 176, 184)
TEXT_DIM = (82, 87, 96)
GREEN = (100, 122, 96)
CYAN = (90, 118, 124)
BLUE = (88, 104, 126)
YELLOW = (150, 132, 94)
ORANGE = (140, 102, 78)
RED = (140, 74, 78)
MAGENTA = (115, 94, 115)

HISTORY_LEN = 90

STRINGS = {
    "en": {
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "cores": "cores",
        "processes": "processes",
        "memory": "memory",
        "free": "free",
        "disk": "disk",
        "network": "network",
        "download": "▼ download",
        "upload": "▲ upload",
        "name": "NAME",
    },
    "pt-br": {
        "weekdays": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
        "cores": "núcleos",
        "processes": "processos",
        "memory": "memória",
        "free": "livre",
        "disk": "disco",
        "network": "rede",
        "download": "▼ recebendo",
        "upload": "▲ enviando",
        "name": "NOME",
    },
}
LANG = "en"


def t(key):
    return STRINGS[LANG][key]


def detect_system_lang():
    """Usado quando --lang não é passado: lê o idioma do macOS (Ajustes >
    Geral > Idioma e Região) e cai em português só se o idioma configurado
    for português — qualquer outro vira inglês, já que são as duas únicas
    traduções que existem. Repare que é o IDIOMA, não a região: um Mac en_BR
    (inglês, região Brasil) conta como inglês."""
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5)
        lang_code = r.stdout.strip().split("_")[0].split("-")[0].lower()
        return "pt-br" if lang_code == "pt" else "en"
    except (subprocess.SubprocessError, OSError):
        return "en"


def load_font(size):
    return ImageFont.truetype(FONT_PATH, size)


FONTS = {
    "clock": load_font(88),
    "big": load_font(58),
    "title": load_font(30),
    "normal": load_font(28),
    "small": load_font(23),
    "tiny": load_font(20),
}


def blend(c1, c2, t):
    return tuple(int(c1[i] * t + c2[i] * (1 - t)) for i in range(3))


def level_color(pct):
    if pct < 50:
        return GREEN
    if pct < 80:
        return YELLOW
    return RED


def human_bytes(n):
    """Formata bytes com prefixo de escala (sem a letra 'B' final) — ex: "478.8", "3.8K", "7.5G"."""
    n = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


def human_rate(bytes_per_sec):
    return human_bytes(bytes_per_sec) + "B/s"


class Draw:
    """Thin wrapper around ImageDraw with the helpers this dashboard needs."""

    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img)

    def text(self, xy, s, font, fill, bold=False):
        self.d.text(xy, s, font=font, fill=fill)
        if bold:
            self.d.text((xy[0] + 1, xy[1]), s, font=font, fill=fill)

    def width(self, s, font):
        return self.d.textlength(s, font=font)

    def text_right(self, x_right, y, s, font, fill, bold=False):
        w = self.width(s, font)
        self.text((x_right - w, y), s, font, fill, bold)

    def text_center(self, x_center, y, s, font, fill, bold=False):
        w = self.width(s, font)
        self.text((x_center - w / 2, y), s, font, fill, bold)

    def panel(self, x0, y0, x1, y1, title, accent, title_x=None):
        self.d.rectangle([x0, y0, x1, y1], fill=PANEL_BG, outline=BORDER_DIM, width=2)
        pad = 18
        tx = max(x0 + 22, title_x) if title_x is not None else x0 + 22
        tw = self.width(title, FONTS["title"])
        self.d.rectangle([tx, y0 - 20, tx + tw + 2 * pad, y0 + 1], fill=BG)
        self.text((tx + pad, y0 - 20), title, FONTS["title"], accent, bold=True)
        return x0 + 32, y0 + 44, x1 - 32, y1 - 28  # inner content box

    def hbar(self, x, y, w, h, pct, color, bg=BORDER_DIM):
        self.d.rectangle([x, y, x + w, y + h], fill=bg)
        fw = int(w * max(0, min(pct, 100)) / 100)
        if fw > 0:
            self.d.rectangle([x, y, x + fw, y + h], fill=color)

    def sparkline(self, x, y, w, h, values, color, max_val=None):
        self.d.rectangle([x, y, x + w, y + h], fill=blend(color, BG, 0.06))
        if len(values) < 2:
            return
        maxv = max_val if max_val else max(max(values), 1)
        n = len(values)
        step = w / (n - 1)
        pts = [(x + i * step, y + h - (min(v, maxv) / maxv) * h) for i, v in enumerate(values)]
        poly = pts + [(x + w, y + h), (x, y + h)]
        self.d.polygon(poly, fill=blend(color, PANEL_BG, 0.30))
        self.d.line(pts, fill=color, width=3, joint="curve")


DiskUsage = collections.namedtuple("DiskUsage", "total used free percent")


def root_disk_usage():
    """psutil.disk_usage('/') lê só o volume APFS 'Data', que no macOS
    moderno mostra pouquíssimo uso mesmo com o disco quase cheio de
    verdade — a maior parte do espaço (System, snapshots locais, etc.)
    vive em outros volumes do MESMO container. Ajustes > Armazenamento
    soma o container inteiro, então é isso que usamos aqui também."""
    try:
        r = subprocess.run(["diskutil", "info", "-plist", "/"], capture_output=True, timeout=5)
        info = plistlib.loads(r.stdout)
        total, free = info["APFSContainerSize"], info["APFSContainerFree"]
        used = total - free
        return DiskUsage(total, used, free, 100 * used / total if total else 0)
    except (subprocess.SubprocessError, plistlib.InvalidFileException, KeyError, OSError):
        return psutil.disk_usage("/")


class Stats:
    def __init__(self):
        self.cpu_hist = collections.deque(maxlen=HISTORY_LEN)
        self.mem_hist = collections.deque(maxlen=HISTORY_LEN)
        self.rx_hist = collections.deque(maxlen=HISTORY_LEN)
        self.tx_hist = collections.deque(maxlen=HISTORY_LEN)
        self._procs = {}
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.monotonic()
        self._boot = datetime.fromtimestamp(psutil.boot_time())
        self._net_start = self._last_net
        psutil.cpu_percent(percpu=True)  # prime
        self._own_process = psutil.Process(os.getpid())
        self._own_process.cpu_percent(None)  # prime
        self._last_children_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._last_children_t = time.monotonic()

    def _own_tree_cpu_pct(self):
        """Quanto do CPU (na escala "100 = 1 núcleo") foi gasto por nós mesmos
        desde a última leitura: o processo principal (psutil) + a soma de
        toda a árvore de subprocessos que já rodou e terminou nesse meio-tempo
        (system_profiler, osascript, diskutil — via RUSAGE_CHILDREN, que
        acumula recursivamente contanto que cada processo espere pelos
        próprios filhos, que é o caso do subprocess.run)."""
        own_pct = self._own_process.cpu_percent(None)

        now_t = time.monotonic()
        children_now = resource.getrusage(resource.RUSAGE_CHILDREN)
        children_dt = (children_now.ru_utime + children_now.ru_stime) - (
            self._last_children_rusage.ru_utime + self._last_children_rusage.ru_stime
        )
        elapsed = max(now_t - self._last_children_t, 0.001)
        self._last_children_rusage = children_now
        self._last_children_t = now_t

        return own_pct + 100 * children_dt / elapsed

    def sample(self):
        cpu_total_raw = psutil.cpu_percent(percpu=False)
        cpu_per_core_raw = psutil.cpu_percent(percpu=True)

        # Sem isso, gerar a própria imagem (desenhar em 4K, chamar
        # system_profiler/osascript/diskutil) aparece no dashboard como se
        # fosse carga "do sistema" — no fundo é só o próprio dashboard se
        # medindo. Descontamos nosso consumo do total e distribuímos esse
        # desconto entre os núcleos ativos, proporcional ao uso de cada um
        # (não dá pra saber em qual núcleo específico rodamos, mas isso
        # aproxima bem e mantém o total sempre igual à soma das barras).
        nonzero_sum = sum(c for c in cpu_per_core_raw if c > 0)
        to_subtract = min(self._own_tree_cpu_pct(), nonzero_sum)
        if nonzero_sum > 0:
            cpu_per_core = [
                max(0.0, c - to_subtract * (c / nonzero_sum)) if c > 0 else 0.0
                for c in cpu_per_core_raw
            ]
        else:
            cpu_per_core = cpu_per_core_raw
        cpu_total = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else cpu_total_raw

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        now_net = psutil.net_io_counters()
        now_t = time.monotonic()
        dt = max(now_t - self._last_net_t, 0.001)
        rx_rate = (now_net.bytes_recv - self._last_net.bytes_recv) / dt
        tx_rate = (now_net.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net = now_net
        self._last_net_t = now_t

        live_pids = set(psutil.pids()) - {os.getpid()}
        for pid in list(self._procs):
            if pid not in live_pids:
                del self._procs[pid]
        for pid in live_pids:
            if pid not in self._procs:
                try:
                    p = psutil.Process(pid)
                    p.cpu_percent(None)
                    self._procs[pid] = p
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        procs = []
        for p in self._procs.values():
            try:
                procs.append(
                    (p.pid, p.name(), p.cpu_percent(None), p.memory_percent())
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda r: r[2], reverse=True)

        self.cpu_hist.append(cpu_total)
        self.mem_hist.append(mem.percent)
        self.rx_hist.append(rx_rate)
        self.tx_hist.append(tx_rate)

        disks = [("/", root_disk_usage())]
        root_dev = os.stat("/").st_dev
        for p in sorted(Path("/Volumes").glob("*")):
            name = p.name
            if name.startswith(".") or "timemachine" in name.lower():
                continue
            try:
                if not p.is_dir() or os.stat(p).st_dev == root_dev:
                    continue
                disks.append((str(p), psutil.disk_usage(str(p))))
            except OSError:
                continue

        return {
            "cpu_total": cpu_total,
            "cpu_per_core": cpu_per_core,
            "mem": mem,
            "swap": swap,
            "rx_rate": rx_rate,
            "tx_rate": tx_rate,
            "net_total_recv": now_net.bytes_recv - self._net_start.bytes_recv,
            "net_total_sent": now_net.bytes_sent - self._net_start.bytes_sent,
            "procs": procs[:60],
            "proc_count": len(self._procs),
            "disks": disks,
            "uptime": datetime.now() - self._boot,
            "loadavg": os.getloadavg(),
        }


def format_uptime(delta: timedelta):
    total = int(delta.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def get_desktop_displays():
    """Mapeia cada `desktop N` do System Events ao monitor físico correspondente,
    cruzando o nome do monitor (`display name of desktop N`) com a resolução
    real reportada pelo system_profiler — é assim que sabemos qual desktop
    está num monitor em pé (retrato) sem depender de índice fixo, já que a
    ordem pode mudar se os cabos forem reconectados."""
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to count of desktops'],
            capture_output=True, text=True, timeout=10,
        )
        n = int(r.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return {}

    names = {}
    for i in range(1, n + 1):
        try:
            r = subprocess.run(
                ["osascript", "-e", f'tell application "System Events" to get display name of desktop {i}'],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                names[i] = r.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            pass

    res_by_name = {}
    try:
        r = subprocess.run(["system_profiler", "SPDisplaysDataType", "-json"],
                            capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout)
        for gpu in data.get("SPDisplaysDataType", []):
            for disp in gpu.get("spdisplays_ndrvs", []):
                name = disp.get("_name")
                m = re.match(r"(\d+)\s*x\s*(\d+)", disp.get("_spdisplays_resolution", ""))
                if name and m:
                    res_by_name[name] = (int(m.group(1)), int(m.group(2)))
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError, OSError):
        pass

    displays = {}
    for i, name in names.items():
        w, h = res_by_name.get(name, (None, None))
        displays[i] = {"name": name, "width": w, "height": h, "portrait": bool(w and h and h > w)}
    return displays


def render(state, stats: Stats) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    dr = Draw(img)

    margin = 40
    gap = 24

    # Painéis (barra superior inclusa) ficam dentro dessa faixa — não só o
    # texto — para não caírem atrás de ícones/widgets colados na lateral.
    content_x0 = margin + WIDGET_SAFE_LEFT
    content_x1 = WIDTH - margin - WIDGET_SAFE_RIGHT

    # Reserva vertical simétrica: embaixo precisa desviar do Dock
    # (DOCK_SAFE_BOTTOM); em cima não tem nada a evitar, mas usamos a mesma
    # folga para o conjunto ficar centralizado em vez de "descer".
    v_margin = margin + DOCK_SAFE_BOTTOM

    # --- Top bar -------------------------------------------------------
    top_h = 130
    dr.d.rectangle([content_x0, v_margin, content_x1, v_margin + top_h], fill=PANEL_BG, outline=BORDER_DIM, width=2)
    safe_left_x = content_x0 + 40
    safe_right_x = content_x1 - 40

    host = socket.gethostname().removesuffix(".local")
    osver = f"macOS {platform.mac_ver()[0]}"
    dr.text((safe_left_x, v_margin + 20), host, FONTS["big"], TEXT, bold=True)
    dr.text((safe_left_x, v_margin + 78), osver, FONTS["small"], TEXT_DIM)

    now = datetime.now()
    dr.text_center((content_x0 + content_x1) / 2, v_margin + 14, now.strftime("%H:%M:%S"), FONTS["clock"], TEXT, bold=True)
    weekday = t("weekdays")[now.weekday()]
    dr.text_center((content_x0 + content_x1) / 2, v_margin + 96, f"{weekday}, {now.strftime('%d/%m/%Y')}", FONTS["small"], TEXT_DIM)

    la1, la5, la15 = state["loadavg"]
    dr.text_right(safe_right_x, v_margin + 20, f"uptime {format_uptime(state['uptime'])}", FONTS["normal"], TEXT)
    dr.text_right(safe_right_x, v_margin + 66, f"load {la1:.2f} {la5:.2f} {la15:.2f}", FONTS["small"], TEXT_DIM)
    dr.text_right(safe_right_x, v_margin + 96, f"{state['proc_count']} {t('processes')}", FONTS["small"], TEXT_DIM)

    # --- Column layout ---------------------------------------------------
    content_y0 = v_margin + top_h + gap
    content_y1 = HEIGHT - v_margin
    content_h = content_y1 - content_y0
    content_w = content_x1 - content_x0

    left_w = int(content_w * 0.60)
    right_x0 = content_x0 + left_w + gap
    right_w = content_x1 - right_x0

    # --- CPU panel (left, top) -------------------------------------------
    cpu_h = int(content_h * 0.42)
    cx0, cy0, cx1, cy1 = dr.panel(content_x0, content_y0, content_x0 + left_w, content_y0 + cpu_h,
                                    f"cpu — {len(state['cpu_per_core'])} {t('cores')}", CYAN, title_x=safe_left_x)

    num_x = max(cx0, safe_left_x)
    color = level_color(state["cpu_total"])
    dr.text((num_x, cy0), f"{state['cpu_total']:.0f}%", FONTS["clock"], color, bold=True)
    dr.text((num_x, cy0 + 92), "total", FONTS["small"], TEXT_DIM)

    num_w = dr.width("100%", FONTS["clock"])  # largura no pior caso, para o gráfico não invadir o número
    spark_x = num_x + num_w + 40
    spark_w = cx1 - spark_x
    spark_h = int((cy1 - cy0) * 0.30)
    dr.sparkline(spark_x, cy0, spark_w, spark_h, list(stats.cpu_hist), color, max_val=100)

    grid_y0 = cy0 + spark_h + 18
    grid_h = cy1 - grid_y0
    cores = state["cpu_per_core"]
    cols = 2 if len(cores) > 6 else 1
    rows = math.ceil(len(cores) / cols)
    cell_w = spark_w / cols
    cell_h = grid_h / rows
    for i, pct in enumerate(cores):
        col, row = i % cols, i // cols
        cx = spark_x + col * cell_w
        cyy = grid_y0 + row * cell_h
        label = f"C{i:<2d}"
        dr.text((cx, cyy + cell_h / 2 - 14), label, FONTS["small"], TEXT_DIM)
        bar_x = cx + 66
        bar_w = cell_w - 66 - 70
        dr.hbar(bar_x, cyy + cell_h / 2 - 9, bar_w, 18, pct, level_color(pct))
        dr.text_right(cx + cell_w - 10, cyy + cell_h / 2 - 14, f"{pct:.0f}%", FONTS["small"], TEXT_DIM)

    # --- Process panel (left, bottom) ------------------------------------
    proc_y0 = content_y0 + cpu_h + gap
    px0, py0, px1, py1 = dr.panel(content_x0, proc_y0, content_x0 + left_w, content_y1, t("processes"), MAGENTA)

    col_pid, col_cpu, col_mem = px1 - 380, px1 - 260, px1 - 130
    dr.text((px0, py0), "PID", FONTS["small"], TEXT_DIM)
    dr.text((px0 + 90, py0), t("name"), FONTS["small"], TEXT_DIM)
    dr.text((col_cpu, py0), "CPU%", FONTS["small"], TEXT_DIM)
    dr.text((col_mem, py0), "MEM%", FONTS["small"], TEXT_DIM)
    row_h = 40
    y = py0 + 38
    name_w_limit = col_cpu - (px0 + 90) - 20
    for pid, name, cpu, mem_pct in state["procs"]:
        if y + row_h > py1:
            break
        while dr.width(name, FONTS["small"]) > name_w_limit and len(name) > 3:
            name = name[:-2] + "…"
        dr.text((px0, y), str(pid), FONTS["small"], TEXT_DIM)
        dr.text((px0 + 90, y), name, FONTS["small"], TEXT)
        dr.text((col_cpu, y), f"{cpu:.1f}", FONTS["small"], level_color(cpu))
        dr.text((col_mem, y), f"{mem_pct:.1f}", FONTS["small"], TEXT_DIM)
        y += row_h

    # --- Memory panel (right, top) ---------------------------------------
    mem = state["mem"]
    swap = state["swap"]
    mem_h = int(content_h * 0.34)
    mx0, my0, mx1, my1 = dr.panel(right_x0, content_y0, content_x1, content_y0 + mem_h, t("memory"), GREEN)

    mem_color = level_color(mem.percent)
    dr.text((mx0, my0), f"{mem.percent:.0f}%", FONTS["big"], mem_color, bold=True)
    dr.text_right(min(mx1, safe_right_x), my0 + 12, f"{human_bytes(mem.used)}B / {human_bytes(mem.total)}B", FONTS["normal"], TEXT)
    bar_y = my0 + 76
    dr.hbar(mx0, bar_y, mx1 - mx0, 26, mem.percent, mem_color)

    lines = [
        ("wired", getattr(mem, "wired", 0), YELLOW),
        ("active", mem.active, CYAN),
        ("inactive", mem.inactive, BLUE),
        (t("free"), mem.available, GREEN),
    ]
    ly = bar_y + 56
    row_gap = (my1 - ly) / len(lines)
    for label, value, col in lines:
        dr.text((mx0, ly), label, FONTS["small"], TEXT_DIM)
        dr.hbar(mx0 + 150, ly + 4, (mx1 - mx0) - 150 - 160, 14, 100 * value / mem.total, col)
        dr.text_right(mx1, ly, f"{human_bytes(value)}B", FONTS["small"], TEXT)
        ly += row_gap

    swap_pct = swap.percent
    dr.text((mx0, my1 - 30), f"swap {human_bytes(swap.used)}B / {human_bytes(swap.total)}B", FONTS["small"], TEXT_DIM)
    dr.hbar(mx0 + 330, my1 - 26, (mx1 - mx0) - 330, 14, swap_pct, ORANGE if swap_pct else BORDER_DIM)

    # --- Disk panel (right, middle) ---------------------------------------
    disk_y0 = content_y0 + mem_h + gap
    disk_h = int(content_h * 0.14)
    dx0, dy0, dx1, dy1 = dr.panel(right_x0, disk_y0, content_x1, disk_y0 + disk_h, t("disk"), ORANGE)
    disks = state["disks"][:3] or []
    row_gap = (dy1 - dy0) / max(len(disks), 1)
    yy = dy0
    for mp, usage in disks:
        label = "Macintosh HD" if mp == "/" else Path(mp).name
        col = level_color(usage.percent)
        dr.text((dx0, yy), label, FONTS["normal"], TEXT)
        dr.text_right(dx1, yy, f"{human_bytes(usage.used)}B / {human_bytes(usage.total)}B  ({usage.percent:.0f}%)", FONTS["small"], TEXT_DIM)
        dr.hbar(dx0, yy + 36, dx1 - dx0, 20, usage.percent, col)
        yy += row_gap

    # --- Network panel (right, bottom) ------------------------------------
    net_y0 = disk_y0 + disk_h + gap
    nx0, ny0, nx1, ny1 = dr.panel(right_x0, net_y0, content_x1, content_y1, t("network"), BLUE)

    half = (nx1 - nx0 - 40) / 2
    dr.text((nx0, ny0), t("download"), FONTS["small"], TEXT_DIM)
    dr.text((nx0, ny0 + 30), human_rate(state["rx_rate"]), FONTS["big"], CYAN, bold=True)
    dr.text((nx0 + half + 40, ny0), t("upload"), FONTS["small"], TEXT_DIM)
    dr.text((nx0 + half + 40, ny0 + 30), human_rate(state["tx_rate"]), FONTS["big"], MAGENTA, bold=True)

    spark_y = ny0 + 106
    spark_h2 = ny1 - spark_y - 40
    max_net = max(list(stats.rx_hist) + list(stats.tx_hist) + [1024 * 200])
    dr.sparkline(nx0, spark_y, half, spark_h2, list(stats.rx_hist), CYAN, max_val=max_net)
    dr.sparkline(nx0 + half + 40, spark_y, half, spark_h2, list(stats.tx_hist), MAGENTA, max_val=max_net)

    dr.text((nx0, ny1 - 26), f"total ↓ {human_bytes(state['net_total_recv'])}B", FONTS["tiny"], TEXT_DIM)
    dr.text_right(nx1, ny1 - 26, f"total ↑ {human_bytes(state['net_total_sent'])}B", FONTS["tiny"], TEXT_DIM)

    return img


def render_portrait(state, stats: Stats) -> Image.Image:
    """Mesmos dados do render() principal, mas empilhados numa coluna só —
    para monitores girados em retrato (ex.: um 1080x1920)."""
    img = Image.new("RGB", (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), BG)
    dr = Draw(img)

    margin = 40
    gap = 16
    content_x0 = margin
    content_x1 = PORTRAIT_WIDTH - margin
    cx = (content_x0 + content_x1) / 2

    # --- Top bar (host/relógio/uptime empilhados; não cabem lado a lado) --
    top_h = 310
    dr.d.rectangle([content_x0, margin, content_x1, margin + top_h], fill=PANEL_BG, outline=BORDER_DIM, width=2)

    host = socket.gethostname().removesuffix(".local")
    osver = f"macOS {platform.mac_ver()[0]}"
    y = margin + 16
    dr.text_center(cx, y, host, FONTS["big"], TEXT, bold=True)
    y += 68
    dr.text_center(cx, y, osver, FONTS["small"], TEXT_DIM)
    y += 34

    now = datetime.now()
    dr.text_center(cx, y, now.strftime("%H:%M:%S"), FONTS["clock"], TEXT, bold=True)
    y += 108
    weekday = t("weekdays")[now.weekday()]
    dr.text_center(cx, y, f"{weekday}, {now.strftime('%d/%m/%Y')}", FONTS["small"], TEXT_DIM)
    y += 34

    la1, la5, la15 = state["loadavg"]
    info = f"uptime {format_uptime(state['uptime'])} · load {la1:.2f} {la5:.2f} {la15:.2f} · {state['proc_count']} proc"
    dr.text_center(cx, y, info, FONTS["tiny"], TEXT_DIM)

    # --- Coluna única -------------------------------------------------
    content_y0 = margin + top_h + gap
    content_y1 = PORTRAIT_HEIGHT - margin
    content_h = content_y1 - content_y0

    # cpu precisa de espaço pros 11 núcleos empilhados; memória precisa de
    # 4 linhas (wired/active/inactive/livre) sem se sobrepor — daí as
    # proporções não serem uniformes. O resto (processos) fica com o sobra.
    cpu_h = int(content_h * 0.31)
    mem_h = int(content_h * 0.20)
    disk_h = int(content_h * 0.08)
    net_h = int(content_h * 0.15)
    proc_y0 = content_y0 + cpu_h + mem_h + disk_h + net_h + 4 * gap

    # --- CPU ------------------------------------------------------------
    cpu_y0 = content_y0
    cx0, cy0, cx1, cy1 = dr.panel(content_x0, cpu_y0, content_x1, cpu_y0 + cpu_h,
                                    f"cpu — {len(state['cpu_per_core'])} {t("cores")}", CYAN)
    color = level_color(state["cpu_total"])
    dr.text((cx0, cy0), f"{state['cpu_total']:.0f}%", FONTS["clock"], color, bold=True)
    dr.text((cx0, cy0 + 92), "total", FONTS["small"], TEXT_DIM)

    num_w = dr.width("100%", FONTS["clock"])
    spark_x = cx0 + num_w + 30
    spark_w = cx1 - spark_x
    spark_h = 96
    dr.sparkline(spark_x, cy0, spark_w, spark_h, list(stats.cpu_hist), color, max_val=100)

    grid_y0 = cy0 + max(spark_h, 108) + 14
    grid_h = cy1 - grid_y0
    cores = state["cpu_per_core"]
    row_h = grid_h / len(cores)
    for i, pct in enumerate(cores):
        yy = grid_y0 + i * row_h
        label = f"C{i:<2d}"
        dr.text((cx0, yy + row_h / 2 - 12), label, FONTS["small"], TEXT_DIM)
        bar_x = cx0 + 60
        bar_w = (cx1 - cx0) - 60 - 70
        dr.hbar(bar_x, yy + row_h / 2 - 8, bar_w, 16, pct, level_color(pct))
        dr.text_right(cx1, yy + row_h / 2 - 12, f"{pct:.0f}%", FONTS["small"], TEXT_DIM)

    # --- Memória ----------------------------------------------------------
    mem = state["mem"]
    swap = state["swap"]
    mem_y0 = cpu_y0 + cpu_h + gap
    mx0, my0, mx1, my1 = dr.panel(content_x0, mem_y0, content_x1, mem_y0 + mem_h, t("memory"), GREEN)

    mem_color = level_color(mem.percent)
    dr.text((mx0, my0), f"{mem.percent:.0f}%", FONTS["big"], mem_color, bold=True)
    dr.text_right(mx1, my0 + 6, f"{human_bytes(mem.used)}B / {human_bytes(mem.total)}B", FONTS["small"], TEXT)
    bar_y = my0 + 62
    dr.hbar(mx0, bar_y, mx1 - mx0, 20, mem.percent, mem_color)

    lines = [
        ("wired", getattr(mem, "wired", 0), YELLOW),
        ("active", mem.active, CYAN),
        ("inactive", mem.inactive, BLUE),
        (t("free"), mem.available, GREEN),
    ]
    ly = bar_y + 40
    row_gap = max((my1 - ly) / len(lines), 1)
    for label, value, col in lines:
        dr.text((mx0, ly), label, FONTS["tiny"], TEXT_DIM)
        dr.hbar(mx0 + 110, ly + 2, (mx1 - mx0) - 110 - 130, 11, 100 * value / mem.total, col)
        dr.text_right(mx1, ly, f"{human_bytes(value)}B", FONTS["tiny"], TEXT)
        ly += row_gap

    # --- Disco --------------------------------------------------------
    disk_y0 = mem_y0 + mem_h + gap
    dx0, dy0, dx1, dy1 = dr.panel(content_x0, disk_y0, content_x1, disk_y0 + disk_h, t("disk"), ORANGE)
    disks = state["disks"][:2] or []
    row_gap = (dy1 - dy0) / max(len(disks), 1)
    yy = dy0
    for mp, usage in disks:
        label = "Macintosh HD" if mp == "/" else Path(mp).name
        col = level_color(usage.percent)
        dr.text((dx0, yy), label, FONTS["small"], TEXT)
        dr.text_right(dx1, yy, f"{usage.percent:.0f}%", FONTS["small"], TEXT_DIM)
        dr.hbar(dx0, yy + 28, dx1 - dx0, 16, usage.percent, col)
        yy += row_gap

    # --- Rede (empilhada: recebendo em cima, enviando embaixo) -----------
    net_y0 = disk_y0 + disk_h + gap
    nx0, ny0, nx1, ny1 = dr.panel(content_x0, net_y0, content_x1, net_y0 + net_h, t("network"), BLUE)
    half_h = (ny1 - ny0 - gap) / 2
    max_net = max(list(stats.rx_hist) + list(stats.tx_hist) + [1024 * 200])

    dr.text((nx0, ny0), t("download"), FONTS["tiny"], TEXT_DIM)
    dr.text((nx0, ny0 + 22), human_rate(state["rx_rate"]), FONTS["normal"], CYAN, bold=True)
    spark1_y = ny0 + 62
    dr.sparkline(nx0, spark1_y, nx1 - nx0, half_h - 62, list(stats.rx_hist), CYAN, max_val=max_net)

    tx_y0 = ny0 + half_h + gap
    dr.text((nx0, tx_y0), t("upload"), FONTS["tiny"], TEXT_DIM)
    dr.text((nx0, tx_y0 + 22), human_rate(state["tx_rate"]), FONTS["normal"], MAGENTA, bold=True)
    spark2_y = tx_y0 + 62
    dr.sparkline(nx0, spark2_y, nx1 - nx0, half_h - 62, list(stats.tx_hist), MAGENTA, max_val=max_net)

    # --- Processos (resto do espaço) ------------------------------------
    px0, py0, px1, py1 = dr.panel(content_x0, proc_y0, content_x1, content_y1, t("processes"), MAGENTA)
    col_cpu, col_mem = px1 - 150, px1 - 65
    name_x = px0 + 56
    dr.text((px0, py0), "PID", FONTS["tiny"], TEXT_DIM)
    dr.text((name_x, py0), t("name"), FONTS["tiny"], TEXT_DIM)
    dr.text((col_cpu, py0), "CPU%", FONTS["tiny"], TEXT_DIM)
    dr.text((col_mem, py0), "MEM%", FONTS["tiny"], TEXT_DIM)
    row_h = 34
    y = py0 + 30
    name_w_limit = col_cpu - name_x - 16
    for pid, name, cpu, mem_pct in state["procs"]:
        if y + row_h > py1:
            break
        while dr.width(name, FONTS["tiny"]) > name_w_limit and len(name) > 3:
            name = name[:-2] + "…"
        dr.text((px0, y), str(pid), FONTS["tiny"], TEXT_DIM)
        dr.text((name_x, y), name, FONTS["tiny"], TEXT)
        dr.text((col_cpu, y), f"{cpu:.1f}", FONTS["tiny"], level_color(cpu))
        dr.text((col_mem, y), f"{mem_pct:.1f}", FONTS["tiny"], TEXT_DIM)
        y += row_h

    return img


# O macOS mantém, por conta própria, um cache de cada imagem que já foi
# usada como papel de parede (um arquivo por troca, nunca reaproveitado nem
# limpo sozinho). Trocar o wallpaper com frequência sem podar essa pasta
# enche o disco em pouco tempo — foi exatamente isso que aconteceu aqui.
WALLPAPER_AGENT_CACHE = (
    Path.home()
    / "Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches"
    / "com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image"
)


def prune_wallpaper_agent_cache(keep_seconds):
    # Best-effort: sem "Acesso Total ao Disco" concedido ao Python, o macOS
    # nega acesso ao container de outro processo (PermissionError) — nesse
    # caso simplesmente desistimos nesta rodada em vez de derrubar o loop.
    try:
        if not WALLPAPER_AGENT_CACHE.is_dir():
            return
        cutoff = time.time() - keep_seconds
        for f in WALLPAPER_AGENT_CACHE.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _run_set_picture(target: str, path: Path) -> bool:
    script = f'tell application "System Events" to tell {target} to set picture to (POSIX file "{path}")'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"aviso: osascript falhou ao definir o wallpaper ({target}): {r.stderr.strip()}", file=sys.stderr)
    return r.returncode == 0


def set_wallpaper_all(path: Path) -> bool:
    return _run_set_picture("every desktop", path)


def set_wallpaper_desktop(index: int, path: Path) -> bool:
    return _run_set_picture(f"desktop {index}", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=60.0, help="segundos entre atualizações")
    ap.add_argument("--once", action="store_true", help="renderiza um único frame e sai (não define o wallpaper)")
    ap.add_argument("--portrait", action="store_true", help="com --once, renderiza o layout de monitor em retrato")
    ap.add_argument("--lang", choices=sorted(STRINGS), default=None,
                     help="idioma dos textos do dashboard (padrão: detecta pelo idioma do macOS)")
    args = ap.parse_args()

    global LANG
    LANG = args.lang or detect_system_lang()

    OUT_DIR.mkdir(exist_ok=True)
    stats = Stats()

    if args.once:
        time.sleep(1.0)  # allow cpu_percent to have a real window to measure
        state = stats.sample()
        img = render_portrait(state, stats) if args.portrait else render(state, stats)
        out = OUT_DIR / "preview.png"
        img.save(out)
        print(f"saved {out}")
        return

    # Nome de arquivo único a cada ciclo: reaproveitar o mesmo caminho pode
    # não atualizar a tela. Só o frame mais novo fica no nosso diretório;
    # o cache que o macOS cria por conta própria é podado à parte (ver
    # prune_wallpaper_agent_cache).
    prev_landscape = None
    prev_portrait = None
    for stale in OUT_DIR.glob("frame_*.png"):
        stale.unlink(missing_ok=True)

    print(f"wallpaper_btop rodando, atualizando a cada {args.interval}s. Ctrl+C para parar.")
    try:
        while True:
            state = stats.sample()

            displays = get_desktop_displays()
            portrait_idxs = [i for i, d in displays.items() if d["portrait"]]
            landscape_idxs = [i for i in displays if i not in portrait_idxs]

            landscape_path = OUT_DIR / f"frame_{int(time.time() * 1000)}_h.png"
            render(state, stats).save(landscape_path)

            if displays and portrait_idxs:
                # Alguns monitores estão de pé: cada grupo (retrato/paisagem)
                # recebe sua própria imagem, endereçando o desktop certo.
                portrait_path = OUT_DIR / f"frame_{int(time.time() * 1000)}_v.png"
                render_portrait(state, stats).save(portrait_path)
                for i in portrait_idxs:
                    set_wallpaper_desktop(i, portrait_path)
                for i in landscape_idxs:
                    set_wallpaper_desktop(i, landscape_path)
                if prev_portrait is not None:
                    prev_portrait.unlink(missing_ok=True)
                prev_portrait = portrait_path
            else:
                # Detecção falhou ou é tudo paisagem: comportamento simples de antes.
                set_wallpaper_all(landscape_path)
                if prev_portrait is not None:
                    prev_portrait.unlink(missing_ok=True)
                    prev_portrait = None

            if prev_landscape is not None:
                prev_landscape.unlink(missing_ok=True)
            prev_landscape = landscape_path

            prune_wallpaper_agent_cache(keep_seconds=max(args.interval * 3, 30))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nparado.")
        sys.exit(0)


if __name__ == "__main__":
    main()
