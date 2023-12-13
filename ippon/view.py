# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import gzip
import hashlib
import json
import locale
import os
import sys
import time

from ippon.config import init_config, StaticConfiguration, \
                         get_config_competitions

from cffi import FFI
from pyray import *


def load_scores():

    scores = {}

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
        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")  # noqa: E501
        if not os.path.exists(competition_filepath):
            continue
        fd = gzip.open(competition_filepath, "r")
        data = fd.read()
        fd.close()

        scores[name] = scores.get(name, {})
        for games in json.loads(data):
            for game in games:
                level = game["competition"]["level"]
                scores[name][level] = scores[name].get(level, []) + [game["teams"]]

    return scores


def draw_date_time():
    locale.setlocale(locale.LC_TIME, "fr_FR")
    draw_text(time.strftime("%a %d %b %Y %H:%M:%S", time.localtime()), 800 - 300, 480 - 40, 20, BLACK) # noqa: E501


def window_logic():

    all_scores = load_scores()

    DRAW_GRID = False

    ffi = FFI()

    init_window(800, 480, "ippon")

    FONT_SIZE = 30

    edit_box = False
    value = ffi.new("int *")

    day_edit_box = False
    day_value = ffi.new("int *")

    tmp1 = ffi.new("int *")
    yyy = 0

    game_id = ffi.new("int *")

    team1_logo = load_image("/Users/guedou/.config/ippon/logos/f4508ee2dfa0362d36538b2371940994.png")
    team1_texture = load_texture_from_image(team1_logo)

    team2_logo = load_image("/Users/guedou/.config/ippon/logos/167c7f4bf8968065ba3f0f0a1173a7e9.png")
    team2_texture = load_texture_from_image(team2_logo)

    scores = [[], []]
    scores[0].append("Marseille 3 - 0 Le_Havre")
    scores[0].append("Lyon 3 - 3 Lorient")
    #scores[0].append("Brest 1 - 1 Toulouse")

    goals = []
    goals.append("A. Sangante 18' csc")
    goals.append("P. Aubameyang 21'")
    goals.append("I. Sarr 84'")

    scores[1].append("Brighton 2 - 2 Liverpool")
    scores[1].append("West_Ham 2 - 2 Newcastle")
    scores[1].append("Wolverhampton 1 - 1 Aston_Villa")

    while not window_should_close():
        begin_drawing()
        clear_background(WHITE)

        if DRAW_GRID:
            for i in range(0, 480, 10):
                draw_line(0, i, 800, i, GRAY)

            for i in range(0, 800, 10):
                draw_line(i, 0, i, 480, GRAY)


        competitions_keys = [c for c in all_scores.keys()]
        competition_key = competitions_keys[value[0]]
        games = all_scores[competition_key]
        day_key = [d for d in all_scores[competition_key].keys()][day_value[0]]

        new_scores = games[day_key]

        print(value[0], "-", competition_key, "|", day_value[0], "-", day_key, "|", game_id[0], "-", len(games[day_key]))

        gui_spinner(Rectangle(20 + 200 + 20 + 200 + 20, 20, 200, 20), "%d " % len(games[day_key]), game_id, 1, len(games[day_key]), False)

        # Retrieve game information
        team1 = games[day_key][game_id[0] - 1][0]["team1"]["name"]
        team2 = games[day_key][game_id[0] - 1][1]["team2"]["name"]

        team1_score = games[day_key][game_id[0] - 1][0]["score"]
        team2_score = games[day_key][game_id[0] - 1][1]["score"]

        team1_logo = games[day_key][game_id[0] - 1][0]["team1"]["logo"]
        team2_logo = games[day_key][game_id[0] - 1][1]["team2"]["logo"]

        logo_filename = hashlib.md5(team1_logo.encode()).hexdigest() + ".png"  # noqa: E501
        logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)  # noqa: E501
        if os.path.exists(logo_filepath):
            team1_logo = logo_filepath
        else:
            team1_logo = None
        logo_filename = hashlib.md5(team2_logo.encode()).hexdigest() + ".png"  # noqa: E501
        logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)  # noqa: E501
        if os.path.exists(logo_filepath):
            team2_logo = logo_filepath
        else:
            team2_logo = None

        team1_goals = []
        for goal in games[day_key][game_id[0] - 1][0]["goals"]:
            goal_type = ""
            if goal[2]:
                goal_type = " " + goal[2]
            goal[1] = goal[1].replace("’", "'")
            team1_goals.append(goal[0] + " " + goal[1] + goal_type)

        team2_goals = []
        for goal in games[day_key][game_id[0] - 1][1]["goals"]:
            goal_type = ""
            if goal[2]:
                goal_type = " " + goal[2]
            goal[1] = goal[1].replace("’", "'")
            team2_goals.append(goal[0] + " " + goal[1] + goal_type)

        x = measure_text("%+3s - %-3s" % (team1_score, team2_score), FONT_SIZE)
        draw_text("%+3s - %-3s" % (team1_score, team2_score), 400 - int(x / 2), int(480 / 4), FONT_SIZE, BLACK)

        team1_len = measure_text(team1, FONT_SIZE)
        draw_text(team1, 400 - int(x / 2) - team1_len - 20, int(480 / 4), FONT_SIZE, BLACK)

        if team1_logo:
            team1_logo = load_image(team1_logo)
            team1_texture = load_texture_from_image(team1_logo)
            draw_texture(team1_texture, 400 - int(x / 2) - team1_len - 20 - 40, int(480 / 4), WHITE)

        y = measure_text(team2, FONT_SIZE)
        draw_text(team2, 400 + int(x / 2) + 20, int(480 / 4), FONT_SIZE, BLACK)

        if team2_logo:
            team2_logo = load_image(team2_logo)
            team2_texture = load_texture_from_image(team2_logo)
            draw_texture(team2_texture, 400 + int(x / 2) + y + 40, int(480 / 4), WHITE)

        for i in range(len(team1_goals)):
            goal_len = measure_text(team1_goals[i], 20)
            draw_text(team1_goals[i], 400 - int(x / 2) - goal_len - 20, int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1), 20, BLACK)

        for i in range(len(team2_goals)):
            goal_len = measure_text(team2_goals[i], 20)
            draw_text(team2_goals[i], 400 + int(x / 2) + 20, int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1), 20, BLACK)

        draw_date_time()

        # Draw the competitions dropdown box
        competitions_str = ";".join(c for c in all_scores.keys())
        if gui_dropdown_box(Rectangle(20, 20, 200, 20), competitions_str, value, edit_box):
            edit_box = not edit_box
            game_id[0] = 0

        # Draw the days dropdown box
        competitions_keys = [c for c in all_scores.keys()]
        competition_key = competitions_keys[value[0]]
        days_str = ";".join(c for c in all_scores[competition_key].keys())
        if gui_dropdown_box(Rectangle(20 + 200 + 20, 20, 200, 20), days_str, day_value, day_edit_box):
            day_edit_box = not day_edit_box

        end_drawing()

    close_window()
