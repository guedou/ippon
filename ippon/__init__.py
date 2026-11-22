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


@click.command(help="display the tactile dashboard")
@click.option("--demo", is_flag=True, help="Use fictional data without network or accounts.")
@click.option("--demo-scenario", default="normal", show_default=True,
              type=click.Choice(["normal", "long", "offline", "empty", "loading", "error"]),
              help="Choose the demo's content or source state (requires --demo).")
@click.option("--fullscreen", is_flag=True, help="Start in fullscreen mode.")
@click.option("--screenshot", type=click.Path(dir_okay=False),
              help="Save a PNG of the last rendered frame.")
@click.option("--frames", type=click.IntRange(min=1),
              help="Exit after this many rendered frames (useful for screenshots).")
def view(demo, demo_scenario, fullscreen, screenshot, frames):
    if not demo and demo_scenario != "normal":
        raise click.UsageError("--demo-scenario requires --demo.")
    from ippon.view import window_logic
    window_logic(demo=demo, demo_scenario=demo_scenario,
                 fullscreen=fullscreen, screenshot=screenshot, frames=frames)


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
