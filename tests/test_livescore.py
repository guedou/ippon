# SPDX-License-Identifier: GPL-2.0+
import configparser
import copy
import gzip
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from ippon import livescore
from ippon.config import StaticConfiguration, load_configuation

sync = importlib.import_module("ippon.sync")


COMPETITION = {"name": "Ligue 1", "year": "2026", "source": "livescore",
               "source_id": "68"}
EVENT = {"Eid": "123", "Esd": 20261120194500, "Eps": "FT", "ErnInf": "11",
         "T1": [{"Nm": "Troyes", "Img": "troyes.png"}],
         "T2": [{"Nm": "Le Havre", "Img": "havre.png"}],
         "Tr1": "2", "Tr2": "1"}


def goal(kind=36, side=1, **extra):
    return {"IT": kind, "Nm": side, "Min": 19, "Fn": "Antoine",
            "Ln": "Mille", **extra}


def raw_data(incidents=None):
    return {"results": {"Stages": [{"Events": [copy.deepcopy(EVENT)]}]},
            "incidents": {"123": {"Incs": incidents or {}}}}


class LiveScoreTests(unittest.TestCase):
    def test_scores_and_nested_goals(self):
        data = raw_data({"1": [goal(side=2, Sc=[0, 1]),
                                {"Incs": [goal(Sc=[1, 1]), goal(63)]}],
                         "2": [goal(37, Min=90, MinEx=8, Sc=[2, 1]), goal(43)]})
        match, = livescore.convert(data, COMPETITION)
        self.assertEqual(match["date"], "20261120")
        self.assertEqual(match["competition"], {"name": "Ligue 1", "level": "Jour #11"})
        self.assertEqual(match["teams"][0]["score"], 2)
        self.assertEqual(match["teams"][0]["goals"],
                         [("Antoine Mille", "19’", None), ("Antoine Mille", "90’ +8", "sp")])
        self.assertEqual(len(match["teams"][1]["goals"]), 1)
        self.assertEqual(match["teams"][0]["team1"]["logo"],
                         "https://storage.lsmedia1.com/images/team/medium/troyes.png")

    def test_logo_paths_include_team_size(self):
        data = raw_data()
        event = data["results"]["Stages"][0]["Events"][0]
        event["T1"][0]["Img"] = "enet/10242.png"
        event["T2"][0]["Img"] = "teambadge/marseille-2026.png"
        match, = livescore.convert(data, COMPETITION)
        self.assertEqual(match["teams"][0]["team1"]["logo"],
                         "https://storage.lsmedia1.com/images/team/medium/enet/10242.png")
        self.assertEqual(match["teams"][1]["team2"]["logo"],
                         "https://storage.lsmedia1.com/images/team/medium/teambadge/marseille-2026.png")

    def test_own_goal_credited_to_scoring_team(self):
        data = raw_data({"1": [goal(39, side=2, Sc=[1, 0])]})
        match, = livescore.convert(data, COMPETITION)
        self.assertEqual(match["teams"][0]["goals"], [("Antoine Mille", "19’", "csc")])
        self.assertEqual(match["teams"][1]["goals"], [])

    def test_missed_penalties_and_shootouts_are_not_goals(self):
        data = raw_data({"1": [goal(38), goal(48), goal(41)]})
        match, = livescore.convert(data, COMPETITION)
        self.assertEqual(match["teams"][0]["goals"], [])

    def test_only_finished_matches_in_requested_season(self):
        data = raw_data()
        events = data["results"]["Stages"][0]["Events"]
        events.extend([{**EVENT, "Eid": "live", "Eps": "45"},
                       {**EVENT, "Eid": "old", "Esd": 20260630200000},
                       {**EVENT, "Eid": "next", "Esd": 20270701200000}])
        self.assertEqual(len(livescore.convert(data, COMPETITION)), 1)

    @patch("ippon.livescore.get_json")
    def test_retrieve_includes_incidents(self, get_json):
        data = raw_data()
        get_json.side_effect = [data["results"], data["incidents"]["123"]]
        self.assertEqual(livescore.retrieve(COMPETITION), data)
        self.assertEqual(get_json.call_args_list[0].args, ("competition/68/results-w/0",))
        self.assertEqual(get_json.call_args_list[0].kwargs, {"limit": 1000})
        self.assertEqual(get_json.call_args_list[1].args, ("incidents/soccer/123",))

    @patch("ippon.livescore.get_json")
    def test_unavailable_season_is_reported(self, get_json):
        get_json.return_value = raw_data()["results"]
        with self.assertRaisesRegex(ValueError, "current-season"):
            livescore.retrieve({**COMPETITION, "year": "2024"})
        get_json.assert_called_once()

    def test_config_restricts_livescore_to_ligue1(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            template = "[core]\nweather_refresh_seconds = 900\n[competition.fr]\nname = Ligue 1\nyear = 2026\nsource = livescore\nsource_id = {}\n"
            path.write_text(template.format(68))
            self.assertEqual(load_configuation(path)["competition.fr"]["source"], "livescore")
            path.write_text(template.format(65))
            with self.assertRaisesRegex(ValueError, "only for Ligue 1"):
                load_configuation(path)

    def test_mixed_sync_and_build(self):
        config = configparser.ConfigParser()
        config.read_dict({"core": {"football_data_token": "token"},
                          "competition.fr": COMPETITION,
                          "competition.en": {"name": "Premier League", "year": "2026",
                                             "source": "football-data", "source_id": "PL"}})
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(StaticConfiguration, "config_data_raw_directory_path", directory),
              patch.object(StaticConfiguration, "config_competitions_directory_path", directory),
              patch("ippon.sync.init_config", return_value=config),
              patch("ippon.livescore.retrieve", return_value=raw_data()) as retrieve,
              patch("ippon.sync.requests.get") as get):
            get.return_value.content = b'{"matches": []}'
            sync.sync_logic(-1)
            retrieve.assert_called_once()
            self.assertIn("/PL/matches", get.call_args.args[0])
            sync.build_logic()
            with gzip.open(Path(directory) / "Ligue 1.json.gz", "rt") as fd:
                self.assertEqual(json.load(fd)[0][0]["teams"][0]["score"], 2)
            self.assertTrue((Path(directory) / "Premier League.json.gz").exists())

    def test_mixed_legacy_build_keeps_livescore_output(self):
        config = configparser.ConfigParser()
        config.read_dict({"competition.fr": COMPETITION,
                          "competition.legacy": {"name": "Legacy", "year": "2024",
                                                 "start": "01/01/2024", "end": "01/01/2024"}})
        with tempfile.TemporaryDirectory() as directory:
            with gzip.open(Path(directory) / "Ligue 1.livescore.json.gz", "wt") as fd:
                json.dump(raw_data(), fd)
            with (patch.object(StaticConfiguration, "config_data_raw_directory_path", directory),
                  patch.object(StaticConfiguration, "config_data_json_directory_path", directory),
                  patch.object(StaticConfiguration, "config_competitions_directory_path", directory),
                  patch("ippon.sync.init_config", return_value=config)):
                sync.build_logic()
            with gzip.open(Path(directory) / "Ligue 1.json.gz", "rt") as fd:
                self.assertEqual(len(json.load(fd)), 1)
            self.assertTrue((Path(directory) / "Legacy.json.gz").exists())

    def test_sync_limit_is_shared_between_json_providers(self):
        config = configparser.ConfigParser()
        config.read_dict({"competition.fr": COMPETITION,
                          "competition.en": {"name": "Premier League", "year": "2026",
                                             "source": "football-data", "source_id": "PL"}})
        with (patch("ippon.sync.init_config", return_value=config),
              patch("ippon.sync.sync_livescore") as retrieve,
              patch("ippon.sync.requests.get") as get):
            sync.sync_logic(1)
            retrieve.assert_called_once_with(config, 1)
            get.assert_not_called()

    def test_failed_sync_preserves_cached_results(self):
        config = configparser.ConfigParser()
        config.read_dict({"competition.fr": COMPETITION})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Ligue 1.livescore.json.gz"
            path.write_bytes(b"previous cache")
            with (patch.object(StaticConfiguration, "config_data_raw_directory_path", directory),
                  patch("ippon.livescore.retrieve", side_effect=requests.Timeout)):
                sync.sync_livescore(config, -1)
            self.assertEqual(path.read_bytes(), b"previous cache")

    def test_zero_limit_does_not_retrieve(self):
        config = configparser.ConfigParser()
        config.read_dict({"competition.fr": COMPETITION})
        with patch("ippon.livescore.retrieve") as retrieve:
            sync.sync_livescore(config, 0)
            retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
