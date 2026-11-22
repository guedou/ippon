# SPDX-License-Identifier: GPL-2.0+
"""Self-contained, fictional data for UI development; no I/O or network access."""

from datetime import date, timedelta
import time


SCENARIOS = ("normal", "long", "offline", "empty", "loading", "error")


def _match(competition, round_name, day, home, away, goals_home, goals_away):
    return {
        "sport": "Football",
        "date": day.strftime("%Y%m%d"),
        "competition": {"name": competition, "level": round_name},
        "teams": [
            {"team1": {"name": home[0], "logo": "demo:" + home[1]},
             "score": len(goals_home), "rank": None, "goals": goals_home},
            {"team2": {"name": away[0], "logo": "demo:" + away[1]},
             "score": len(goals_away), "rank": None, "goals": goals_away},
        ],
    }


def demo_data(scenario="normal"):
    """Return independent data snapshots using the same shapes as live services.

    Every call creates new containers. Dates are relative to the local date, so
    the demo remains usable after midnight and never needs an account or cache.
    All results, lessons and homework are invented, including player names.
    ``offline`` retains data; ``loading``/``empty``/``error`` have no old cache.
    """
    if scenario not in SCENARIOS:
        raise ValueError("Unknown demo scenario: " + str(scenario))
    today = date.today()
    now = time.time()
    updated_at = now - (3 * 86400 if scenario == "offline" else 1800)
    long = scenario == "long"
    psg = ("Paris Saint-Germain Football Club" if long else "Paris SG", "psg")
    lyon = ("Olympique Lyonnais — équipe première" if long else "Lyon", "ol")
    lens = ("Racing Club de Lens", "lens")
    marseille = ("Olympique de Marseille", "om")
    lille = ("Lille Olympique Sporting Club", "lille")
    monaco = ("Association Sportive de Monaco Football Club" if long else "Monaco", "monaco")
    home_goals = [["Joueur Démo A", "12’", None],
                  ["Joueur Démo B", "54’", "sp"],
                  ["Joueur Démo C", "81’", None]]
    if long:
        home_goals += [["Alexandre Démonstration-Longueville", "84’", None],
                       ["Jean-Baptiste Exemple", "89’", None],
                       ["Joueur Démo F", "90’ +2", "csc"],
                       ["Joueur Démo G", "90’ +6", None]]
    away_goals = [["Joueur Démo Z", "68’", None]]
    competitions = {}
    for competition in ("Ligue 1", "Coupe de démonstration"):
        rounds = {}
        for number, age in ((11, 8), (12, 1)):
            round_name = "Journée " + str(number)
            day = today - timedelta(days=age)
            rounds[round_name] = [
                _match(competition, round_name, day, psg, lyon,
                       [list(goal) for goal in home_goals],
                       [list(goal) for goal in away_goals]),
                _match(competition, round_name, day, lens, marseille,
                       [["Joueur Démo H", "35’", None]], []),
                _match(competition, round_name, day, lille, monaco, [], []),
            ]
        competitions[competition] = rounds

    days = {}
    for offset in range(7):
        selected = today + timedelta(days=offset)
        # Deliberately include today's fictional schedule even on a weekend:
        # the date selector and next-lesson state remain inspectable every day.
        lessons = []
        subjects = ["Mathématiques", "Français", "Anglais",
                    "Histoire-géographie", "Sciences de la vie et de la Terre",
                    "Physique-chimie", "Éducation physique et sportive", "Arts plastiques"]
        for index, subject in enumerate(subjects):
            hour = 8 + index
            lessons.append({
                "start": f"{hour:02d}:30", "end": f"{hour + 1:02d}:20",
                "subject": subject,
                "classroom": str(204 + index),
                "canceled": index == 2,
                "status": "Professeur absent" if index == 2 else "",
            })
        long_description = (
            "Lire le chapitre 3 puis relever les passages qui décrivent le lieu, "
            "les personnages et leurs intentions. Pour chaque extrait, indiquer "
            "la page et expliquer en quelques phrases ce que l'on apprend. "
            "Préparer ensuite un résumé sans recopier le texte du livre. "
            "Apporter le cahier, le livre et une feuille pour la mise en commun. "
            "Exemple de mot très long : "
            "anticonstitutionnellementsupercalifragilisticexpialidocious. "
            "La dernière consigne doit rester accessible en fin de pagination."
        )
        homework = [
            {"subject": "Mathématiques", "description": "Exercices 4 et 5, page 42.", "done": False},
            {"subject": "Français", "description": long_description if long else "Lire le chapitre 3 et préparer un résumé de dix lignes.", "done": False},
            {"subject": "Anglais", "description": "Réviser le vocabulaire de la leçon 2.", "done": True},
            {"subject": "Histoire-géographie", "description": "Compléter la carte et apprendre les repères.", "done": False},
            {"subject": "Physique-chimie", "description": "Relire le protocole de l'expérience et répondre aux questions.", "done": False},
            {"subject": "Sciences de la vie et de la Terre", "description": "Légender le schéma distribué en classe.", "done": False},
        ]
        # Empty future day demonstrates a legitimate 'no lessons' state too.
        days[selected.isoformat()] = {
            "lessons": lessons if offset < 5 else [],
            "homework": homework if offset < 5 else [],
        }

    state = "cached" if scenario == "offline" else "ready"
    error = "Connexion indisponible (démonstration)." if scenario == "offline" else None
    if scenario in {"empty", "loading", "error"}:
        state = scenario
        competitions = {}
        days = {}
        updated_at = None
        if scenario == "error":
            error = "Source indisponible (démonstration)."
    weather = {
        "temperature": 12, "feels_like": 10, "description": "Nuageux",
        "minimum": 8, "maximum": 13, "rain_chance": 30,
        "updated_at": updated_at,
    }
    if scenario in {"empty", "loading", "error"}:
        weather = None
    return {
        "scores": {"competitions": competitions, "updated_at": updated_at},
        "school": {"days": days, "updated_at": updated_at},
        "weather": weather,
        "statuses": {
            source: {"state": state, "last_success": updated_at, "error": error}
            for source in ("football", "school", "weather")
        },
    }
