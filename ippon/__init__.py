# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import click

from ippon.view import test_window


@click.command(help="sync scores")
@click.argument("month", type=click.INT)
@click.argument("year", type=click.INT)
@click.argument("day", type=click.INT)
@click.option("--pretty", is_flag=True, default=False)
def sync(month, year, day, pretty):
    from ippon.sync import sync_logic
    sync_logic(month, year, day, pretty)


@click.command(help="display scores")
def view():
    test_window()


@click.group()
def main():
    pass


main.add_command(sync)
main.add_command(view)
