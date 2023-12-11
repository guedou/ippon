# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

from datetime import datetime
import gzip
import hashlib
import json
import os
import re
import requests
import sys

from ippon.config import init_config, StaticConfiguration, \
                         get_config_competitions
from ippon.utils import get_competitions_dates, get_all_dates

from bs4 import BeautifulSoup, Tag


class Lequipe(object):
    # Retrieved from Firefox
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0',  # noqa: E501
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',  # noqa: E501
        'Accept-Language': 'en-US,en;q=0.5',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Connection': 'keep-alive',
    }

    content = None
    date = None

    def __init__(self, directory_data):
        self.directory_data = directory_data
        self.sport = "Football"

    def retrieve(self, date):
        """
        Retrieve raw results
        """
        url = f"https://www.lequipe.fr/{self.sport}/Directs/{date}"
        self.content = requests.get(url, headers=self.headers).content
        self.date = date

        fd = gzip.open(f"{self.directory_data}/{self.date}.{self.sport}.html.gz", "w")  # noqa: E501
        fd.write(self.content)
        fd.close()

    def exists(self, date):
        filename = f"{self.directory_data}/{date}.{self.sport}.html.gz"
        return os.path.exists(filename)

    def load(self, date):
        """
        Load raw results from disk
        """
        if self.exists(date):
            filename = f"{self.directory_data}/{date}.{self.sport}.html.gz"
            fd = gzip.open(filename, "r")
            self.content = fd.read()
            self.date = date
            fd.close()

    def _football_extract_goal(self, goals_text):
        # Goal type
        goal_type = None
        p = re.compile(r"\((\w+)\)")
        m = p.search(goals_text)
        if m:
            goal_type = m.group(1)

        # Scorer name
        goal_scorer = None
        p = re.compile(r"(\w+\. \w+)")
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

                titles = competition.find_all("span", class_="Lives__competTitle")  # noqa: E501
                if not titles:
                    continue

                for title in titles:
                    # Extract the competition title and level
                    competition_title = title.find("h3", class_="Lives__title")
                    if not competition_title:
                        continue
                    competition_level = title.find("span", class_="Lives__competNiveau")  # noqa: E501
                    if not competition_level:
                        continue
                    competition_title = competition_title.text
                    competition_level = competition_level.text

                    for team_score in competition.find_all("div", class_="TeamScore is-over"):  # noqa: E501
                        if not type(team_score) is Tag:
                            continue

                        # Extract goals
                        team1_goals = []
                        team2_goals = []
                        if self.sport == "Football":
                            tmp_team1_goals = team_score.find("div", class_="TeamScore__goalList is-home")  # noqa: E501
                            if not tmp_team1_goals:
                                continue
                            tmp_team2_goals = team_score.find("div", class_="TeamScore__goalList is-away")  # noqa: E501
                            if not tmp_team2_goals:
                                continue

                            for goals in tmp_team1_goals.find_all("div", class_="TeamScore__goal"):  # noqa: E501
                                tmp_goal = self._football_extract_goal(goals.text)  # noqa: E501
                                if not tmp_goal[0] is None:
                                    team1_goals += [tmp_goal]

                            for goals in tmp_team2_goals.find_all("div", class_="TeamScore__goal"):  # noqa: E501
                                tmp_goal = self._football_extract_goal(goals.text)  # noqa: E501
                                if not tmp_goal[0] is None:
                                    team2_goals += [tmp_goal]

                        # Extract team names
                        team1 = team_score.find("div", class_="MatchScore__team MatchScore__home")  # noqa: E501
                        if not team1:
                            continue
                        team2 = team_score.find("div", class_="MatchScore__team MatchScore__away")  # noqa: E501
                        if not team2:
                            continue
                        team1_name = re.sub("\s+", " ", team1.find("div", class_="MatchScore__teamName").text)  # noqa: E501,W605
                        team2_name = re.sub("\s+", " ", team2.find("div", class_="MatchScore__teamName").text)  # noqa: E501,W605

                        # Extract team logos div
                        team1_logo = team_score.find("div", class_="MatchScore__logo--home")  # noqa: E501
                        if not team1_logo:
                            continue
                        team2_logo = team_score.find("div", class_="MatchScore__logo--away")  # noqa: E501
                        if not team2_logo:
                            continue

                        # Get the team logos URL
                        team1_logo_img = team1_logo.find("img")
                        if not team1_logo_img:
                            continue
                        team2_logo_img = team2_logo.find("img")
                        if not team2_logo_img:
                            continue

                        team1_logo_url = "https://" + team1_logo_img.attrs["src"][2:]  # noqa: E501
                        team2_logo_url = "https://" + team2_logo_img.attrs["src"][2:]  # noqa: E501

                        # Extract the scores
                        team_scores = []
                        for match_score in team_score.find_all("div", class_="MatchScore__result"):  # noqa: E501
                            if not type(match_score) is Tag:
                                continue

                            for team_score in match_score.find_all("div", class_="MatchScore__score"):  # noqa: E501
                                if not team_score:
                                    continue

                                tmp = re.sub("\s+", " ", team_score.text)  # GV: test the returned value  # noqa: E501,W605
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
                        if m.groups():
                            competition_level = m.group(0)

                        competitions.append({"sport": self.sport,
                                             "date": self.date,
                                             "competition": {"name": competition_title, "level": competition_level},  # noqa: E501
                                             "teams": [{"team1": {"name": teams[0], "logo": team1_logo_url}, "score": team_scores[0],  # noqa: E501
                                                        "rank": team_ranks[0], "goals": team1_goals},  # noqa: E501
                                                       {"team2": {"name": teams[1], "logo": team2_logo_url}, "score": team_scores[1],  # noqa: E501
                                                        "rank": team_ranks[1], "goals": team2_goals}],  # noqa: E501
                                             })

        return competitions


def sync_logic(max):

    try:
        config = init_config(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return

    max_start, max_end = get_competitions_dates(config)
    today = datetime.today()
    if today < max_end:
        max_end = today

    dates_needed = get_all_dates(max_start, max_end)

    dates_retrieved = set()
    for year in [max_start.year, max_end.year]:
        directory = os.path.join(StaticConfiguration.config_data_raw_directory_path, f"{year}")  # noqa: E501
        if not os.path.exists(directory):
            os.makedirs(directory)
            continue
        for filename in os.listdir(directory):
            if filename.endswith(".html.gz"):
                date = filename.split(".")[0]
                dates_retrieved.add(date)

    dates_needed = list(set(dates_needed) - set(dates_retrieved))

    years_needed = set()
    for date in dates_needed:
        years_needed.add(date[:4])

    dates_needed.sort()

    for year in years_needed:
        directory = os.path.join(StaticConfiguration.config_data_raw_directory_path, f"{year}")  # noqa: E501
        for date in dates_needed[:max]:
            scores_source = Lequipe(directory)
            if not scores_source.exists(date):
                print(f"[+] Retrieving {date}")
                scores_source.retrieve(date)


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

    max_start, max_end = get_competitions_dates(config)
    today = datetime.today()
    if today < max_end:
        max_end = today

    dates_needed = get_all_dates(max_start, max_end)

    # Convert raw scores to JSON
    if dates_needed:
        print("[+] Converting raw scores to JSON")
        for date in dates_needed:
            year = date[:4]
            filename_html = f"{date}.Football.html.gz"
            filename_json = f"{date}.Football.json.gz"
            directory = os.path.join(StaticConfiguration.config_data_json_directory_path,  # noqa: E501
                                     year)
            filepath_json = os.path.join(directory, filename_json)
            directory = os.path.join(StaticConfiguration.config_data_raw_directory_path,  # noqa: E501
                                     year)
            filepath_html = os.path.join(directory, filename_html)
            if os.path.exists(filepath_html) and not os.path.exists(filepath_json):  # noqa: E501
                scores_source = Lequipe(directory)
                scores_source.load(date)
                competitions = scores_source.parse()
                if len(competitions):
                    fd = gzip.open(filepath_json, "w")
                    fd.write(json.dumps(competitions).encode())
                    fd.close()

    # Build the competitions JSON files
    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        print(f"[+] {name}")
        competition_levels = {}
        for date in dates_needed:
            year = date[:4]
            filename_json = f"{date}.Football.json.gz"
            directory = os.path.join(StaticConfiguration.config_data_json_directory_path,  # noqa: E501
                                     year)
            filepath_json = os.path.join(directory, filename_json)

            if not os.path.exists(filepath_json):
                continue

            fd = gzip.open(filepath_json, "r")
            data = fd.read()
            fd.close()
            competitions = json.loads(data)
            competitions = [c for c in competitions if c["competition"]["name"] == name]  # noqa: E501

            for competition in competitions:
                level = competition["competition"]["level"]
                competition_levels[level] = competition_levels.get(level, [])
                competition_levels[level] += [competition]

        competition_data = []
        for level in competition_levels:
            level_dates = [int(c["date"]) for c in competition_levels[level]]
            level_dates.sort()
            level_date = level_dates[0]

            competition_data.append({"date": level_date, "data": competition_levels[level]})  # noqa: E501

        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")  # noqa: E501
        competition_data = sorted(competition_data, key=lambda c: c["date"])
        fd = gzip.open(competition_filepath, "w")
        fd.write(json.dumps([e["data"] for e in competition_data]).encode())
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
                                fd = open(logo_filepath, "wb")
                                fd.write(r.content)
                                fd.close()
