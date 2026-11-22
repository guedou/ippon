# 🥇 ippon

## Getting Started

TBD

## Configuration

Create the configuration file before running the commands:

```shell
mkdir -p ~/.config/ippon
cp config.ini.example ~/.config/ippon/config.ini
$EDITOR ~/.config/ippon/config.ini
```

Each section must be named `competition.<id>` and define `name` and `year`
(the season's starting year).

### Ligue 1: LiveScore

```ini
[competition.ligue1]
name = Ligue 1
year = 2026
source = livescore
source_id = 68
```

Set `year` to the current season's starting year. `ippon sync` retrieves finished
matches and their scorers, including penalties, own goals and added time.
`ippon build` converts the cached JSON into the viewer format; no token is needed.
LiveScore is restricted to French Ligue 1 (`source_id = 68`). Its undocumented
API serves current-season results only; historical seasons are not supported.
Numeric matchdays are displayed as `Jour 1`, `Jour 2`, etc. When LiveScore sends
`Regular Season` instead of a matchday, the bundled official LFP 2026/2027
fixture calendar resolves it by home/away pair and season, including for old
caches. Provider numbers take priority; missing rounds outside the supported
calendar remain explicitly unknown. No matchday is guessed from the match date.

Other competitions retain their existing sources and can coexist in the same
configuration. For L'Équipe, define `start` and `end` in `DD/MM/YYYY` format;
`name` must exactly match its competition title. For football-data.org, define
`source = football-data`, `source_id` (for example `PL`), and set
`football_data_token` in `[core]`. No token is required for L'Équipe or LiveScore.

### Weather

The viewer fetches weather live from wttr.in. In configurations that use a
`[core]` section, its refresh interval can be changed in seconds:

```ini
[core]
weather_refresh_seconds = 900
```

The default is 900 seconds (15 minutes); the minimum is 60 seconds.

## Launcher logs

`launcher.sh` uses `.venv/bin/python` from its own project directory and saves
stdout and stderr to a separate file for each run in `~/.config/ippon/logs/`.
It no longer requires the project to be installed at `/home/ippon/ippon.git`.
Logs belong to the account running the launcher (for a systemd service, its
`User=` account). `latest.log` points to the most recent run.

```shell
./launcher.sh
# From another terminal:
tail -F ~/.config/ippon/logs/latest.log
```

Logs include Python tracebacks, unbuffered output, start/stop timestamps and
the application's exit status. Python's fault handler is enabled to provide
stack traces for native crashes such as segmentation faults. A forced kill
(`SIGKILL`) or power loss cannot produce a final traceback or stop timestamp.
When launched by systemd, output also remains available through
`journalctl -u <service-name>`; the launcher no longer uses `systemd-cat`.

Logs are private to the launching user and retained until manually deleted.
They may contain personal information: review them before sharing.

## Usage

```shell
ippon sync
ippon build
ippon logo
ippon view
```
## Tactile dashboard and offline demo

The native dashboard requires Python 3.10 or later and uses raylib with an
800 × 480 logical canvas. Its fonts
and demo crests are bundled with the package; it does not need a browser or
fonts installed on the device. `ippon view` uses the configured services;
`ippon view --demo` uses fictional results, lessons and homework exclusively.
The clock displays `HH:MM:SS` and refreshes every second. To use your actual
configured scores, school schedule and weather, omit `--demo`:

```shell
python -m ippon view
```

The demo makes no network requests and does not read or write account settings,
real school data or the user's cache. Dates are relative to the current local
date, and all sporting results and player names are invented.

```shell
python -m ippon view --demo
python -m ippon view --demo --demo-scenario long
python -m ippon view --demo --demo-scenario offline
python -m ippon view --demo --fullscreen
python -m ippon view --demo --frames 5 --screenshot /tmp/ippon-demo.png
```

Available scenarios:

| Scenario | Purpose |
| --- | --- |
| `normal` | Two competitions and two rounds, lessons, canceled lesson and homework |
| `long` | Long team/subject names, seven scorers and a homework description requiring multiple pages |
| `offline` | Cached content with a visibly old last-success timestamp |
| `empty` | Successful source with no content |
| `loading` | Initial loading without an earlier cache |
| `error` | Source failure without an earlier cache |

The demo contains eight lessons and six homework items (including one already
completed) for each populated day, plus empty dates. These are deliberately
fictional even if the selected day is a weekend. The `--demo-scenario` option
requires `--demo`. `--frames N` exits after N rendered frames; use it with
`--screenshot PATH` to produce a PNG without leaving the window running.
On macOS, a desktop session is required for the native window, including when
capturing a screenshot. Pi display, rotation and touch still require an actual
device test; macOS is suitable for navigation and layout development.
The desktop window can be resized while preserving the canvas aspect ratio.
Keyboard shortcuts: `F` toggles fullscreen, `Esc` goes back, and `Q` exits.
Screenshots and mouse navigation on macOS do not validate physical target sizes
or the HyperPixel touch mapping.

The school date picker starts at today and excludes past cached days. Today
remains selectable even when the cache is old; in that case the dashboard says
the day has not been loaded, rather than claiming there are no lessons. At
midnight the school selection returns to the new current day. The home card
can still open the next upcoming school day explicitly.

### Running a separate checkout with the existing interpreter

Use the desired checkout as the current directory and explicitly select its
source path. This reuses the existing dependencies without changing an editable
installation to point at another checkout. For the current development setup:

```shell
ippon_python=/Users/guedou/Projects/ippon.git/.venv/bin/python
ippon_checkout=/Users/guedou/Projects/ippon.git/.worktrees/tactile-v2
cd "$ippon_checkout"
PYTHONPATH="$ippon_checkout" "$ippon_python" -m ippon view
PYTHONPATH="$ippon_checkout" "$ippon_python" -m ippon view --demo
PYTHONPATH="$ippon_checkout" "$ippon_python" -m ippon view --demo --demo-scenario long
PYTHONPATH="$ippon_checkout" "$ippon_python" -m ippon view --demo --frames 5 --screenshot /tmp/ippon-v2.png
```

Replace `ippon_checkout` with the absolute path of your checkout if it moves.
Do not run `pip install -e` from the separate checkout using the main checkout's
virtual environment. The font license and asset provenance are shipped in
`ippon/assets/`; the club crests retain their owners' rights.
