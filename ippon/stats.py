# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import gzip
import json
import os
import sys

from ippon.config import StaticConfiguration, get_config_competitions, init_config
from ippon.utils import get_all_dates, get_competitions_dates


def get_football_data_match_count(filepath):
    """Return the number of matches in a built football-data file."""

    try:
        with gzip.open(filepath, "rt") as fd:
            return sum(len(games) for games in json.load(fd))
    except (OSError, json.JSONDecodeError):
        return None


def main(competition):
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return

    competitions = get_config_competitions(config)
    if competition:
        competitions = [item for item in competitions
                        if item["name"] == competition]
        if not competitions:
            print(f"Competition not found: {competition}", file=sys.stderr)
            return

    for item in competitions:
        print(f"[+] {item['name']} - {item['year']}")

    dated_competitions = [item for item in competitions
                          if item["start"] and item["end"]]
    sourced_competitions = [item for item in competitions
                            if item["source"] and item["source_id"]]

    if dated_competitions:
        max_start, max_end = get_competitions_dates(
            _CompetitionConfig(dated_competitions)
        )
        dates = get_all_dates(max_start, max_end)
        retrieved_dates = set()
        for year in {date[:4] for date in dates}:
            directory = os.path.join(
                StaticConfiguration.config_data_raw_directory_path, year
            )
            try:
                filenames = os.listdir(directory)
            except FileNotFoundError:
                continue
            for filename in filenames:
                if filename.endswith(".Football.html.gz"):
                    retrieved_dates.add(filename.split(".", 1)[0])

        print("\n[-] Days")
        print("    Start:   {}".format(max_start.strftime("%d/%m/%Y")))
        print("    End:     {}".format(max_end.strftime("%d/%m/%Y")))
        print(f"    Total:   {len(dates)}")
        print(f"    Missing: {len(set(dates) - retrieved_dates)}")

    if sourced_competitions:
        print("\n[-] football-data")
        for item in sourced_competitions:
            raw_path = os.path.join(
                StaticConfiguration.config_data_raw_directory_path,
                f"{item['name']}.json.gz",
            )
            built_path = os.path.join(
                StaticConfiguration.config_competitions_directory_path,
                f"{item['name']}.json.gz",
            )
            match_count = get_football_data_match_count(built_path)
            print(f"    {item['name']}: raw={'yes' if os.path.exists(raw_path) else 'no'}, "
                  f"built={'yes' if os.path.exists(built_path) else 'no'}, "
                  f"matches={match_count if match_count is not None else 0}")


class _CompetitionConfig:
    """Minimal ConfigParser-compatible object for dated competitions."""

    def __init__(self, competitions):
        self.competitions = competitions

    def sections(self):
        return [f"competition.{index}" for index in range(len(self.competitions))]

    def __getitem__(self, section):
        return self.competitions[int(section.rsplit(".", 1)[1])]
