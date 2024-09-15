# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from datetime import datetime
import gzip
import hashlib
from io import BytesIO
import json
import os
import requests
import sys

from PIL import Image

from ippon.config import init_config, StaticConfiguration, \
                         get_config_competitions
from ippon.utils import get_competitions_dates, get_all_dates


def sync_logic(max):

    try:
        config = init_config(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    for competition in get_config_competitions(config)[:max]:
        if competition["source"] != "football-data":
            print(f"[!] Source {competition['source']} not supported!")
            continue
        else:
            print(f"[+] Retrieving {competition['name']}")

            source_id = competition["source_id"]
            year = competition["year"]

            try:
                response = requests.get(f"https://api.football-data.org/v4/competitions/{source_id}/matches?season={year}",  # noqa: E501
                                        headers={"X-Auth-Token": config["core"]["football_data_token"]})  # noqa: E501
                data = response.content
            except requests.exceptions.RequestException as e:
                print(f"[!] Error: {e}")
                continue

            fd = gzip.open(f"{StaticConfiguration.config_data_raw_directory_path}/{competition["name"]}.json.gz", "wb") # noqa: E501
            fd.write(data)
            fd.close()


def convert_team(team_name, match, team_key, score_key):
    team = {}
    team[team_name] = {}
    team[team_name]["name"] = match[team_key]["name"]
    team[team_name]["logo"] = match[team_key]["crest"]
    team["score"] = match["score"]["fullTime"][score_key]
    team["rank"] = None
    team["goals"] = []
    return team


def convert(filename):
    if not os.path.exists(filename):
        print(f"{filename} not found", file=sys.stderr)
        return

    with gzip.open(filename, "r") as fd:
        raw_data = fd.read()
        fd.close()

    competiton = []
    data = json.loads(raw_data)

    for match in data["matches"]:
        if match["status"] != "FINISHED":
            continue

        ippon_match = {}
        ippon_match["sport"] = "Football"
        date = datetime.fromisoformat(match["utcDate"])
        ippon_match["date"] = date.strftime("%Y%m%d")

        ippon_match["competition"] = {}
        ippon_match["competition"]["name"] = match["competition"]["name"]
        ippon_match["competition"]["level"] = f"Jour #{match["matchday"]}"

        ippon_match["teams"] = []

        team1 = convert_team("team1", match, "homeTeam", "home")
        team2 = convert_team("team2", match, "awayTeam", "away")
        ippon_match["teams"] = [team1, team2]

        competiton.append(ippon_match)

    return [competiton]


def build_logic():
    """
    Convert raw scores to JSON
    """

    # Load the configuration
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    for competition in get_config_competitions(config):
        if competition["source"] != "football-data":
            print(f"[!] Source {competition['source']} not supported!")
            continue

        name = competition["name"]
        print(f"[+] {name}")
        filename = f"{StaticConfiguration.config_data_raw_directory_path}/{name}.json.gz"  # noqa: E501
        data_ippon = convert(filename)

        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")  # noqa: E501
        fd = gzip.open(competition_filepath, "w")
        fd.write(json.dumps(data_ippon).encode())
        fd.close()


def logo_logic():
    """
    Download logos
    """

    # Load the configuration
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        print(f"[+] {name}")
        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")  # noqa: E501
        if not os.path.exists(competition_filepath):
            continue
        fd = gzip.open(competition_filepath, "r")
        data = fd.read()
        fd.close()
        competitions = json.loads(data)
        for competition in competitions:
            for match in competition:
                for team in match["teams"]:
                    for team_name in team:
                        if team_name == "team1" or team_name == "team2":
                            logo_url = team[team_name]["logo"]
                            logo_filename = hashlib.md5(logo_url.encode()).hexdigest() + ".png"  # noqa: E501
                            logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)  # noqa: E501
                            if not os.path.exists(logo_filepath):
                                print(f"  [+] Downloading {logo_url}")
                                r = requests.get(logo_url)
                                img = Image.open(BytesIO(r.content))
                                img = img.resize((24, 24))
                                img.save(logo_filepath)