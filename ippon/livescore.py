# SPDX-License-Identifier: GPL-2.0+
"""LiveScore's undocumented JSON API, restricted to French Ligue 1."""

from datetime import datetime

import requests

from ippon.football_rounds import resolve_round

API_URL = "https://prod-cdn-public-api.lsmedia1.com/v1/api/app"
IMAGE_URL = "https://storage.lsmedia1.com/images/team/medium/"
# 38/48 are missed penalties; 41 belongs to penalty shoot-outs.
GOAL_TYPES = {36: None, 37: "sp", 39: "csc", 47: None, 50: None,
              51: None, 57: "sp", 66: None, 70: "csc"}


def get_json(path, **params):
    response = requests.get(f"{API_URL}/{path}",
                            params={"locale": "fr", **params}, timeout=20)
    response.raise_for_status()
    return response.json()


def season_events(data, year):
    """The results endpoint serves the current season, not historical seasons."""
    for stage in data["Stages"]:
        for event in stage.get("Events", []):
            date = datetime.strptime(str(event["Esd"]), "%Y%m%d%H%M%S")
            if (event.get("Eps") in {"FT", "AET", "AP"}
                    and datetime(int(year), 7, 1) <= date < datetime(int(year) + 1, 7, 1)):
                yield event


def retrieve(competition):
    data = get_json("competition/68/results-w/0", limit=1000)
    events = list(season_events(data, competition["year"]))
    if not events and any(stage.get("Events") for stage in data["Stages"]):
        raise ValueError(f"No Ligue 1 results for season {competition['year']}; "
                         "LiveScore serves current-season results only.")
    incidents = {}
    for event in events:
        event_id = str(event["Eid"])
        incidents[event_id] = get_json(f"incidents/soccer/{event_id}")
    return {"results": data, "incidents": incidents}


def walk_incidents(incidents):
    for incident in incidents:
        if "Incs" in incident:
            yield from walk_incidents(incident["Incs"])
        else:
            yield incident


def convert(data, competition):
    matches = []
    for event in season_events(data["results"], competition["year"]):
        goals = {1: [], 2: []}
        details = data["incidents"][str(event["Eid"])]
        previous_score = [0, 0]
        for period in details.get("Incs", {}).values():
            for incident in walk_incidents(period):
                kind = incident.get("IT")
                if kind not in GOAL_TYPES or incident.get("Nm") not in goals:
                    continue
                name = " ".join(filter(None, [incident.get("Fn"), incident.get("Ln")]))
                name = name or incident["Pn"]
                minute = f"{incident['Min']}’"
                if incident.get("MinEx"):
                    minute += f" +{incident['MinEx']}"
                side = incident["Nm"]
                score = incident.get("Sc")
                if score and len(score) == 2:
                    score = [int(value) for value in score]
                    increases = [i + 1 for i in range(2) if score[i] > previous_score[i]]
                    if len(increases) == 1:
                        side = increases[0]
                    previous_score = score
                goals[side].append((name, minute, GOAL_TYPES[kind]))
        teams = []
        for side in (1, 2):
            team = event[f"T{side}"][0]
            teams.append({
                f"team{side}": {"name": team["Nm"],
                                "logo": IMAGE_URL + team["Img"]},
                "score": int(event[f"Tr{side}"]), "rank": None,
                "goals": goals[side],
            })
        matches.append({
            "sport": "Football", "date": str(event["Esd"])[:8],
            "competition": {"name": competition["name"],
                            "level": resolve_round(event.get("ErnInf"),
                                                   teams[0]["team1"]["name"],
                                                   teams[1]["team2"]["name"],
                                                   competition["year"])},
            "teams": teams,
        })
    return sorted(matches, key=lambda match: match["date"])
