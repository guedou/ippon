# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import gzip
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from typing import ClassVar

import requests
from bs4 import BeautifulSoup, Tag

from ippon.config import StaticConfiguration, get_config_competitions, init_config
from ippon.utils import get_all_dates, get_competitions_dates


class Lequipe:
    # Retrieved from Firefox
    headers: ClassVar[dict[str, str]] = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Connection': 'keep-alive',
    }

    def __init__(self, directory_data):
        self.directory_data = directory_data
        self.sport = "Football"
        self.content = None
        self.date = None

    def retrieve(self, date):
        """
        Retrieve raw results
        """
        url = f"https://www.lequipe.fr/{self.sport}/Directs/{date}"
        response = requests.get(url, headers=self.headers, timeout=20)
        response.raise_for_status()
        self.content = response.content
        self.date = date

        filename = f"{self.directory_data}/{self.date}.{self.sport}.html.gz"
        with gzip.open(filename, "wb") as fd:
            fd.write(self.content)

    def exists(self, date):
        filename = f"{self.directory_data}/{date}.{self.sport}.html.gz"
        return os.path.exists(filename)

    def load(self, date):
        """
        Load raw results from disk
        """
        if self.exists(date):
            filename = f"{self.directory_data}/{date}.{self.sport}.html.gz"
            with gzip.open(filename, "rb") as fd:
                self.content = fd.read()
            self.date = date

    def _football_extract_goal(self, goals_text):
        # Goal type
        goal_type = None
        p = re.compile(r"\((\w+)\)")
        m = p.search(goals_text)
        if m:
            goal_type = m.group(1)

        # Scorer name
        goal_scorer = None
        p = re.compile(r"((\s?([A-ZÀ-Ÿ]([a-zA-Z\.\-À-ÿ\'])+))+)")
        m = p.search(goals_text)
        if m:
            goal_scorer = m.group(0)

        # Goal time
        goal_time = None
        p = re.compile(r"(\d+’( \+\d+)?)")
        m = p.search(goals_text)
        if m:
            goal_time = m.group(0)

        return (goal_scorer, goal_time, goal_type)

    def parse(self):
        competitions = []
        if self.content is None:
            return competitions
        soup = BeautifulSoup(self.content, "html.parser")

        for live in soup.find_all("div", class_="Lives__section"):
            for competition in live.find_all("div", class_="Lives__compet"):

                titles = competition.find_all("span", class_="Lives__competTitle")
                if not titles:
                    continue

                for title in titles:
                    # Extract the competition title and level
                    competition_title = title.find("h3", class_="Lives__title")
                    if not competition_title:
                        continue
                    competition_level = title.find("span", class_="Lives__competNiveau")
                    if not competition_level:
                        continue
                    competition_title = competition_title.text
                    competition_level = competition_level.text

                    for team_score in competition.find_all("div", class_="TeamScore is-over"):
                        if not type(team_score) is Tag:
                            continue

                        # Extract goals
                        team1_goals = []
                        team2_goals = []
                        if self.sport == "Football":
                            tmp_team1_goals = team_score.find("div", class_="TeamScore__goalList is-home")
                            if not tmp_team1_goals:
                                continue
                            tmp_team2_goals = team_score.find("div", class_="TeamScore__goalList is-away")
                            if not tmp_team2_goals:
                                continue

                            for goals in tmp_team1_goals.find_all("div", class_="TeamScore__goal"):
                                tmp_goal = self._football_extract_goal(goals.text)
                                if not tmp_goal[0] is None:
                                    team1_goals += [tmp_goal]

                            for goals in tmp_team2_goals.find_all("div", class_="TeamScore__goal"):
                                tmp_goal = self._football_extract_goal(goals.text)
                                if not tmp_goal[0] is None:
                                    team2_goals += [tmp_goal]

                        # Extract team names
                        team1 = team_score.find("div", class_="MatchScore__team MatchScore__home")
                        if not team1:
                            continue
                        team2 = team_score.find("div", class_="MatchScore__team MatchScore__away")
                        if not team2:
                            continue
                        team1_name = re.sub(r"\s+", " ", team1.find("div", class_="MatchScore__teamName").text)
                        team2_name = re.sub(r"\s+", " ", team2.find("div", class_="MatchScore__teamName").text)

                        # Extract team logos div
                        team1_logo = team_score.find("div", class_="MatchScore__logo--home")
                        if not team1_logo:
                            continue
                        team2_logo = team_score.find("div", class_="MatchScore__logo--away")
                        if not team2_logo:
                            continue

                        # Get the team logos URL
                        team1_logo_img = team1_logo.find("img")
                        if not team1_logo_img:
                            continue
                        team2_logo_img = team2_logo.find("img")
                        if not team2_logo_img:
                            continue

                        team1_logo_src = team1_logo_img.get("src")
                        team2_logo_src = team2_logo_img.get("src")
                        if not team1_logo_src or not team2_logo_src:
                            continue
                        if team1_logo_src.startswith("//"):
                            team1_logo_url = "https:" + team1_logo_src
                        elif team1_logo_src.startswith("/"):
                            team1_logo_url = "https://www.lequipe.fr" + team1_logo_src
                        else:
                            team1_logo_url = team1_logo_src
                        if team2_logo_src.startswith("//"):
                            team2_logo_url = "https:" + team2_logo_src
                        elif team2_logo_src.startswith("/"):
                            team2_logo_url = "https://www.lequipe.fr" + team2_logo_src
                        else:
                            team2_logo_url = team2_logo_src

                        # Extract the scores
                        team_scores = []
                        for match_score in team_score.find_all("div", class_="MatchScore__result"):
                            if not type(match_score) is Tag:
                                continue

                            for team_score in match_score.find_all("div", class_="MatchScore__score"):
                                if not team_score:
                                    continue

                                tmp = re.sub(r"\s+", " ", team_score.text)
                                team_scores.append(tmp)

                        # Process team ranks
                        team_ranks = [team1_name, team2_name]
                        if '(' in team1_name:
                            for i in range(len(team_ranks)):
                                p = re.compile(r"(\d+)")
                                m = p.search(team_ranks[i])
                                if m:
                                    team_ranks[i] = int(m.group(0))
                        else:
                            team_ranks = [None, None]

                        # Process team names
                        teams = [team1_name, team2_name]
                        for i in range(len(teams)):
                            p = re.compile(r"([a-zA-Z]+(\W[a-zA-Z]+)*)")
                            m = p.search(teams[i])
                            if m:
                                teams[i] = m.group(0)

                        # Process teams scores
                        for i in range(len(team_scores)):
                            p = re.compile(r"(\d+)")
                            m = p.search(team_scores[i])
                            if m:
                                team_scores[i] = int(m.group(0))

                        # Competition level
                        p = re.compile(r"(([\w]+,?\s?)+)")
                        m = p.search(competition_level)
                        if m:
                            competition_level = m.group(0)

                        if len(team_scores) != 2:
                            continue

                        competitions.append({"sport": self.sport,
                                             "date": self.date,
                                             "competition": {"name": competition_title, "level": competition_level},
                                             "teams": [{"team1": {"name": teams[0], "logo": team1_logo_url}, "score": team_scores[0],
                                                        "rank": team_ranks[0], "goals": team1_goals},
                                                       {"team2": {"name": teams[1], "logo": team2_logo_url}, "score": team_scores[1],
                                                        "rank": team_ranks[1], "goals": team2_goals}],
                                             })

        return competitions


def sync_logic(max):

    try:
        config = init_config(StaticConfiguration.config_file_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return

    max_start, max_end = get_competitions_dates(config)
    today = datetime.now()
    max_end = min(max_end, today)

    dates_needed = get_all_dates(max_start, max_end)

    dates_retrieved = set()
    years = {date[:4] for date in dates_needed}
    for year in years:
        directory = os.path.join(StaticConfiguration.config_data_raw_directory_path, year)
        os.makedirs(directory, exist_ok=True)
        for filename in os.listdir(directory):
            if filename.endswith(".html.gz"):
                dates_retrieved.add(filename.split(".", 1)[0])

    dates_needed = sorted(set(dates_needed) - dates_retrieved)
    dates_to_retrieve = dates_needed if max < 0 else dates_needed[:max]

    for date in dates_to_retrieve:
        directory = os.path.join(StaticConfiguration.config_data_raw_directory_path,
                                 date[:4])
        scores_source = Lequipe(directory)
        if not scores_source.exists(date):
            print(f"[+] Retrieving {date}")
            try:
                scores_source.retrieve(date)
            except requests.RequestException as exc:
                print(f"[!] Unable to retrieve {date}: {exc}", file=sys.stderr)


def build_logic():
    """
    Convert raw scores to JSON
    """

    # Load the configuration
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return

    max_start, max_end = get_competitions_dates(config)
    today = datetime.now()
    max_end = min(max_end, today)

    dates_needed = get_all_dates(max_start, max_end)

    # Convert raw scores to JSON
    if dates_needed:
        print("[+] Converting raw scores to JSON")
        for date in dates_needed:
            year = date[:4]
            filename_html = f"{date}.Football.html.gz"
            filename_json = f"{date}.Football.json.gz"
            directory = os.path.join(StaticConfiguration.config_data_json_directory_path,
                                     year)
            os.makedirs(directory, exist_ok=True)
            filepath_json = os.path.join(directory, filename_json)
            directory = os.path.join(StaticConfiguration.config_data_raw_directory_path,
                                     year)
            filepath_html = os.path.join(directory, filename_html)
            if os.path.exists(filepath_html) and not os.path.exists(filepath_json):
                scores_source = Lequipe(directory)
                scores_source.load(date)
                competitions = scores_source.parse()
                if competitions:
                    with gzip.open(filepath_json, "wb") as fd:
                        fd.write(json.dumps(competitions).encode())

    # Build the competitions JSON files
    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        print(f"[+] {name}")
        competition_levels = {}
        for date in dates_needed:
            year = date[:4]
            filename_json = f"{date}.Football.json.gz"
            directory = os.path.join(StaticConfiguration.config_data_json_directory_path,
                                     year)
            filepath_json = os.path.join(directory, filename_json)

            if not os.path.exists(filepath_json):
                continue

            with gzip.open(filepath_json, "rb") as fd:
                competitions = json.loads(fd.read())
            competitions = [c for c in competitions if c["competition"]["name"] == name]

            for competition in competitions:
                level = competition["competition"]["level"]
                competition_levels[level] = competition_levels.get(level, [])
                competition_levels[level] += [competition]

        competition_data = []
        for level, level_competitions in competition_levels.items():
            level_dates = sorted(int(c["date"]) for c in level_competitions)
            competition_data.append({"date": level_dates[0],
                                     "data": level_competitions})

        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")
        competition_data = sorted(competition_data, key=lambda c: c["date"])
        with gzip.open(competition_filepath, "wb") as fd:
            fd.write(json.dumps([e["data"] for e in competition_data]).encode())


def logo_logic():
    """
    Download logos
    """

    # Load the configuration
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return

    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        print(f"[+] {name}")
        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")
        if not os.path.exists(competition_filepath):
            continue
        with gzip.open(competition_filepath, "rb") as fd:
            competitions = json.loads(fd.read())
        for competition in competitions:
            for match in competition:
                for team in match["teams"]:
                    for team_name in team:
                        if team_name == "team1" or team_name == "team2":
                            logo_url = team[team_name]["logo"]
                            logo_filename = hashlib.md5(logo_url.encode()).hexdigest() + ".png"
                            logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)
                            if not os.path.exists(logo_filepath):
                                print(f"  [+] Downloading {logo_url}")
                                try:
                                    response = requests.get(logo_url, timeout=20)
                                    response.raise_for_status()
                                except requests.RequestException as exc:
                                    print(f"  [!] Unable to download {logo_url}: {exc}",
                                          file=sys.stderr)
                                    continue
                                with open(logo_filepath, "wb") as fd:
                                    fd.write(response.content)
