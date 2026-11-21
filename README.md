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