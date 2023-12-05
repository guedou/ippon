# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import click

from ippon.view import test_window


@click.command(help="display scores")
def view():
    test_window()


@click.group()
def main():
    pass


main.add_command(view)
