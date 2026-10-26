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

Each section must be named `competition.<id>` and define `name`, `year`,
`start`, and `end`. Dates use `DD/MM/YYYY`; `name` must exactly match the
competition title returned by L'Équipe.

### Weather

The viewer fetches weather live from wttr.in. In configurations that use a
`[core]` section, its refresh interval can be changed in seconds:

```ini
[core]
weather_refresh_seconds = 900
```

The default is 900 seconds (15 minutes); the minimum is 60 seconds.

## Usage

```shell
ippon sync
ippon build
ippon logo
ippon view
```