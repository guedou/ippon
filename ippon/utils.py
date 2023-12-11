# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from datetime import datetime, timedelta

from ippon.config import get_config_competitions


def get_competitions_dates(config):
    """
    Return the min start and the max end dates for all competitions
    """

    max_start = datetime.strptime("31/12/2100", "%d/%m/%Y")
    max_end = datetime.strptime("01/01/1970", "%d/%m/%Y")

    competitions = get_config_competitions(config)
    for competition in competitions:
        start = competition["start"]
        end = competition["end"]
        start = datetime.strptime(start, "%d/%m/%Y")
        if start < max_start:
            max_start = start
        end = datetime.strptime(end, "%d/%m/%Y")
        if end > max_end:
            max_end = end

    return max_start, max_end


def get_all_dates(date_start, date_end):
    today = datetime.today()
    if today < date_end:
        date_end = today

    dates_needed = []
    for i in range((date_end - date_start).days + 1):
        date = date_start + timedelta(days=i)
        date = datetime.strftime(date, "%Y%m%d")
        dates_needed.append(date)

    return dates_needed