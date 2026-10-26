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

## Usage

```shell
ippon sync
ippon build
ippon logo
ippon view
```