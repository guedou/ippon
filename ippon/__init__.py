# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import click


@click.command(help="build scores")
def build():
    from ippon.sync import build_logic
    build_logic()


@click.command(help="sync scores")
@click.option("--max", default=-1)
def sync(max):
    from ippon.sync import sync_logic
    sync_logic(max)


@click.command(help="display scores")
def view():
    from ippon.view import test_window
    test_window()


@click.command(help="display scores stats")
@click.argument("competition", required=False)
def stats(competition):
    from ippon.stats import main as main_stats
    main_stats(competition)


@click.command(help="sync logos")
def logo():
    from ippon.sync import logo_logic
    logo_logic()


@click.group()
def main():
    pass


main.add_command(build)
main.add_command(logo)
main.add_command(stats)
main.add_command(sync)
main.add_command(view)
