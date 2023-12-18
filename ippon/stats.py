# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from datetime import datetime
import os
import sys

from ippon.config import init_config, load_configuation, StaticConfiguration, \
                         get_config_competitions
from ippon.utils import get_competitions_dates


def get_file_count(directory):
    """
    Return the number of files in a directory
    """

    try:
        return len(os.listdir(directory))
    except FileNotFoundError:
        return 0


def main(competition):

    try:
        init_config(StaticConfiguration.config_file_path)
        config = load_configuation(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return

    max_start, max_end = get_competitions_dates(config)

    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        year = competition["year"]
        print(f"[+] {name} - {year}")

    print("\n[-] Days")
    print("    Start:   {}".format(max_start.strftime("%d/%m/%Y")))
    print("    End:     {}".format(max_end.strftime("%d/%m/%Y")))

    today = datetime.today()
    if today < max_end:
        max_end = today

    total_days = max_end - max_start
    print("    Total:   {}".format(total_days.days))

    missing_days = total_days.days

    for year in set([max_start.year, max_end.year]):
        tmp_directory_path = os.path.join(StaticConfiguration.config_data_raw_directory_path,  # noqa: E501
                                          f"{year}")
        missing_days -= get_file_count(tmp_directory_path)

    print("    Missing: {}".format(missing_days))
