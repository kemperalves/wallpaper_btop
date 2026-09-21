# wallpaper_btop

English | **[Português](README.pt-br.md)**

Renders a **btop**-style dashboard (CPU, memory, disk, network, processes) and
sets it as the macOS desktop wallpaper on a loop. It's not a real animated
live wallpaper (macOS has no native concept of that) — it's an image that
gets redrawn and swapped periodically, which in practice reads as "alive".

Detects monitors standing in portrait automatically and uses a dedicated
stacked layout for them — each System Events `desktop` gets the image
(landscape 3840×2160 or portrait 1080×1920) that matches its physical
monitor, identified by name via `system_profiler`. It doesn't depend on
which monitor is "number 2" — if cables get reconnected in a different
order, detection re-runs every cycle and adjusts itself.

## Layout

```
wallpaper_btop/
├── btop_wallpaper.py                   # main script (collects stats, draws, detects monitors, sets the wallpaper)
├── venv/                               # Python virtual env (Pillow + psutil) — created on install, not in the repo
├── local.wallpaperbtop.plist.template  # LaunchAgent template (bin/start.sh generates the real .plist from this)
├── bin/
│   ├── start.sh                 # starts now + configures auto-start on every login/reboot
│   ├── stop.sh                  # stops now (comes back on next login by itself)
│   ├── uninstall.sh             # stops and removes auto-start (won't come back, even on reboot)
│   └── clean_wallpaper_cache.sh # clears macOS's own wallpaper cache (run from Terminal.app, not from here)
├── output/                    # only the most recent frame per orientation (frame_..._h.png / _v.png)
└── logs/                      # stdout.log / stderr.log for the background process
```

## Install (from scratch)

Requires macOS with Python 3 and the Xcode Command Line Tools
(`xcode-select --install`, if you don't have them yet). Clone anywhere —
the scripts figure out their own location, no fixed path needed.

```bash
git clone https://github.com/kemperalves/wallpaper_btop.git
cd wallpaper_btop
python3 -m venv venv
./venv/bin/pip install Pillow psutil
```

## Keep it always running (including after a Mac restart)

```bash
bin/start.sh
```

This generates `~/Library/LaunchAgents/local.wallpaperbtop.plist` from the
template (with the path to wherever you cloned the project) and registers
it with `launchd`. From then on the process:

- starts by itself on every login/boot (`RunAtLoad`);
- restarts automatically if it dies (`KeepAlive`);
- runs at low CPU/IO priority, so it doesn't get in the way of anything else.

Running `start.sh` again at any point (after editing the `.plist` template,
for example) reloads the configuration and restarts the process.

## Pause temporarily

```bash
bin/stop.sh
```

Stops the process now. **Comes back by itself on the next login/reboot**,
since the LaunchAgent stays installed. The wallpaper stays frozen on the
last frame generated until you run `start.sh` again.

## Turn off for good (won't come back, even on reboot)

```bash
bin/uninstall.sh
```

Removes the LaunchAgent from login items. The project files are untouched —
to reactivate, just run `bin/start.sh` again.

## Test manually (without touching the service)

Render a single test frame, without applying it as the wallpaper:

```bash
./venv/bin/python3 btop_wallpaper.py --once             # landscape layout
./venv/bin/python3 btop_wallpaper.py --once --portrait  # portrait layout
open output/preview.png
```

Run in the foreground (applies the wallpaper for real, but only while the
terminal stays open — Ctrl+C to stop):

```bash
./venv/bin/python3 btop_wallpaper.py --interval 5
```

## Settings

- **Update interval**: edit `--interval 60` in
  `local.wallpaperbtop.plist.template` and run `bin/start.sh` again to apply.
  Shorter intervals feel more "live", but every wallpaper change makes macOS
  keep a copy in its own cache (which only goes away by running
  `bin/clean_wallpaper_cache.sh` now and then) — an interval that was too
  short (5s), running for hours, is what filled up the disk the first time.
  60s is the current balance; don't go lower without running the cleanup
  script regularly.
- **Resolution**: `WIDTH`/`HEIGHT` (landscape) and
  `PORTRAIT_WIDTH`/`PORTRAIT_HEIGHT` (portrait) constants at the top of
  `btop_wallpaper.py`.
- **Monitors considered "portrait"**: any desktop whose detected resolution
  is taller than it is wide. If detection fails (e.g. `system_profiler`
  unavailable), it falls back to the old behavior — the same landscape
  image on every monitor.
- **Dashboard text language**: `--lang en` (default) or `--lang pt-br`, in
  `local.wallpaperbtop.plist.template`.

## Logs / diagnostics

```bash
tail -f logs/stdout.log
tail -f logs/stderr.log

# detailed launchd status:
launchctl print gui/$(id -u)/local.wallpaperbtop
```

## Going back to your old wallpaper

At any point, in **System Settings → Wallpaper**, just pick another image —
that doesn't interfere with the service (it goes back to swapping it on the
next cycle, unless you run `bin/stop.sh` or `bin/uninstall.sh`).
