# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import gzip
import hashlib
import json
import locale
import os
import sys
import time

from cffi import FFI
from pyray import *

from ippon.config import StaticConfiguration, get_config_competitions, init_config
from ippon.pronote import PronoteService
from ippon.weather import WeatherService


def load_scores():

    scores = {}

    # Load the configuration
    try:
        config = init_config(StaticConfiguration.config_file_path)
    except FileNotFoundError:
        print(f"{StaticConfiguration.config_file_path} not found!",
              file=sys.stderr)
        return {}, None

    competitions = get_config_competitions(config)
    for competition in competitions:
        name = competition["name"]
        competition_filepath = os.path.join(StaticConfiguration.config_competitions_directory_path, f"{name}.json.gz")
        if not os.path.exists(competition_filepath):
            continue
        with gzip.open(competition_filepath, "rb") as fd:
            data = fd.read()

        competition_scores = {}
        for games in json.loads(data):
            for game in games:
                level = game["competition"]["level"]
                competition_scores[level] = competition_scores.get(level, []) + [game["teams"]]
        if competition_scores:
            scores[name] = competition_scores

    return scores, config


def get_weather_refresh_interval(config):
    if not config or not config.has_section("core"):
        return 15 * 60
    try:
        return max(60, config.getint("core", "weather_refresh_seconds",
                                     fallback=15 * 60))
    except ValueError:
        print("Invalid weather_refresh_seconds; using 900 seconds.",
              file=sys.stderr)
        return 15 * 60


def draw_date_time():
    try:
        locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
    except locale.Error:
        pass
    draw_text(time.strftime("%a %d %b %Y %H:%M:%S", time.localtime()), 800 - 300, 480 - 40, 20, BLACK)


def draw_weather(weather):
    weather_text = weather.text()
    if weather_text:
        for index, line in enumerate(weather_text.splitlines()):
            draw_text(line, 20, 480 - 60 + index * 22, 20, BLACK)


def shorten_text(text, maximum=32):
    return text if len(text) <= maximum else f"{text[:maximum - 3]}..."


def wrap_text(text, maximum=32, maximum_lines=4):
    lines = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > maximum and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > maximum_lines:
        lines = lines[:maximum_lines]
        lines[-1] = f"{shorten_text(lines[-1], maximum - 3)}..."
    return lines


def draw_pronote_compact(snapshot, selected_day):
    day = snapshot.get("days", {}).get(selected_day)
    if not day:
        return
    draw_text("EMPLOI DU TEMPS", 20, 260, 16, BLACK)
    for index, lesson in enumerate(day["lessons"]):
        text = f"{lesson['start']} {lesson['subject']}"
        draw_text(shorten_text(text), 20, 280 + index * 18, 16, BLACK)
    homework_lines = []
    for homework in day["homework"]:
        text = f"{homework['subject']}: {homework['description']}"
        homework_lines.extend(wrap_text(text))
    draw_text("A FAIRE", 410, 260, 16, BLACK)
    for index, line in enumerate(homework_lines):
        draw_text(line, 410, 280 + index * 18, 16, BLACK)


def draw_pronote(snapshot, selected_day):
    day = snapshot.get("days", {}).get(selected_day,
                                        {"lessons": [], "homework": []})
    draw_text("EMPLOI DU TEMPS", 20, 90, 20, BLACK)
    draw_text("A FAIRE", 410, 90, 20, BLACK)
    for index, lesson in enumerate(day["lessons"][:4]):
        status = " ANNULE" if lesson["canceled"] else ""
        text = f"{lesson['start']} {lesson['subject']}{status}"
        draw_text(shorten_text(text), 20, 120 + index * 26, 20, BLACK)
    homework_y = 120
    for homework in day["homework"][:3]:
        text = f"{homework['subject']}: {homework['description']}"
        for line in wrap_text(text):
            draw_text(line, 410, homework_y, 20, BLACK)
            homework_y += 24


def window_logic():

    all_scores, config = load_scores()
    if not all_scores:
        print("No scores available. Run 'ippon sync' and 'ippon build' first.",
              file=sys.stderr)
        return

    weather = WeatherService(
        refresh_interval=get_weather_refresh_interval(config)
    )
    weather.refresh()
    pronote = PronoteService(config) if config.has_section("pronote") else None
    if pronote:
        pronote.refresh()

    DRAW_GRID = False
    ROTATE_TIME = time.time()
    LAST_INTERACTION_TIME = time.time()
    ROTATE_DELAY = 10
    ROTATE_BACKOFF = 30

    ffi = FFI()

    init_window(800, 480, "ippon")

    FONT_SIZE = 30
    BOX_HEIGHT = 30

    edit_box = False
    value = ffi.new("int *", 1 if pronote else 0)

    day_edit_box = False
    day_value = len(next(iter(all_scores.values()))) - 1
    day_value_dropbox = ffi.new("int *")

    game_id = ffi.new("int *", 1)

    current_team1_logo = None
    current_team2_logo = None
    current_team1_texture = None
    current_team2_texture = None

    set_trace_log_level(LOG_NONE)

    while not window_should_close():
        weather.refresh()
        if pronote:
            pronote.refresh()
        begin_drawing()
        set_target_fps(10)

        if is_key_pressed(KEY_F):
            LAST_INTERACTION_TIME = time.time()
            toggle_fullscreen()

        if is_key_pressed(KEY_D):
            LAST_INTERACTION_TIME = time.time()
            DRAW_GRID = ~DRAW_GRID

        clear_background(WHITE)

        if is_mouse_button_down(MOUSE_BUTTON_LEFT):
            LAST_INTERACTION_TIME = time.time()

        if is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
            position = get_mouse_position()
            if 480 <= position.x <= 520 and 440 <= position.y <= 480:
                toggle_fullscreen()

        if DRAW_GRID:
            draw_fps(20, 480 - 100)
            for i in range(0, 480, 10):
                draw_line(0, i, 800, i, GRAY)

            for i in range(0, 800, 10):
                draw_line(i, 0, i, 480, GRAY)

        competitions_keys = list(all_scores)
        if pronote:
            competitions_keys.insert(0, "Pronote")
        value[0] = min(max(value[0], 0), len(competitions_keys) - 1)
        competition_key = competitions_keys[value[0]]

        if competition_key == "Pronote":
            if (not edit_box and not day_edit_box
                    and (time.time() - LAST_INTERACTION_TIME) > ROTATE_BACKOFF
                    and (time.time() - ROTATE_TIME) > ROTATE_DELAY):
                ROTATE_TIME = time.time()
                value[0] = (value[0] + 1) % len(competitions_keys)
            pronote_days = list(pronote.snapshot.get("days", {}))
            if not pronote_days:
                pronote_days = [time.strftime("%Y-%m-%d")]
            day_value = min(max(day_value, 0), len(pronote_days) - 1)
            pronote_day = pronote_days[day_value]
            draw_pronote(pronote.snapshot, pronote_day)
            draw_date_time()
            draw_weather(weather)

            competitions_str = ";".join(competitions_keys)
            if gui_dropdown_box(Rectangle(20, 20, 200, BOX_HEIGHT),
                                competitions_str, value, edit_box):
                edit_box = not edit_box
                if competitions_keys[value[0]] == "Pronote":
                    day_value = 0
                else:
                    day_value = len(all_scores[competitions_keys[value[0]]]) - 1
                ROTATE_TIME = time.time()

            day_value_dropbox[0] = day_value
            days_str = ";".join(pronote_days)
            if gui_dropdown_box(Rectangle(240, 20, 200, BOX_HEIGHT), days_str,
                                day_value_dropbox, day_edit_box):
                day_edit_box = not day_edit_box
                day_value = day_value_dropbox[0]
                ROTATE_TIME = time.time()
            end_drawing()
            continue

        games = all_scores[competition_key]
        if (pronote and pronote.snapshot.get("days")
                and is_mouse_button_pressed(MOUSE_BUTTON_LEFT)):
            position = get_mouse_position()
            if 280 <= position.y <= 400:
                value[0] = 0
                pronote_days = list(pronote.snapshot["days"])
                today = time.strftime("%Y-%m-%d")
                day_value = pronote_days.index(today) if today in pronote_days else 0
                ROTATE_TIME = time.time()
                end_drawing()
                continue
        day_value = min(max(day_value, 0), len(games) - 1)
        day_key = list(games)[day_value]
        game_id[0] = min(max(game_id[0], 1), len(games[day_key]))

        if False:
            print(value[0], "-", competition_key, "|", day_value[0], "-", day_key, "|", game_id[0], "-", len(games[day_key]))

        gui_spinner(Rectangle(20 + 200 + 20 + 200 + 20, 20, 200, BOX_HEIGHT),
                    f"{len(games[day_key])} ", game_id, 1,
                    len(games[day_key]), False)

        if (not edit_box and not day_edit_box
                and (time.time() - LAST_INTERACTION_TIME) > ROTATE_BACKOFF
                and (time.time() - ROTATE_TIME) > ROTATE_DELAY):
            ROTATE_TIME = time.time()
            value[0] = (value[0] + 1) % len(competitions_keys)
            competition_key = competitions_keys[value[0]]
            day_value = (0 if competition_key == "Pronote"
                         else len(all_scores[competition_key]) - 1)
            game_id[0] = 1

        # Retrieve game information
        team1 = games[day_key][game_id[0] - 1][0]["team1"]["name"]
        team2 = games[day_key][game_id[0] - 1][1]["team2"]["name"]

        team1_score = games[day_key][game_id[0] - 1][0]["score"]
        team2_score = games[day_key][game_id[0] - 1][1]["score"]

        team1_logo = games[day_key][game_id[0] - 1][0]["team1"]["logo"]
        team2_logo = games[day_key][game_id[0] - 1][1]["team2"]["logo"]

        logo_filename = hashlib.md5(team1_logo.encode()).hexdigest() + ".png"
        logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)
        if os.path.exists(logo_filepath):
            team1_logo = logo_filepath
        else:
            team1_logo = None
        logo_filename = hashlib.md5(team2_logo.encode()).hexdigest() + ".png"
        logo_filepath = os.path.join(StaticConfiguration.config_logos_directory_path, logo_filename)
        if os.path.exists(logo_filepath):
            team2_logo = logo_filepath
        else:
            team2_logo = None

        team1_goals = []
        for goal in games[day_key][game_id[0] - 1][0]["goals"]:
            goal_type = ""
            if goal[2]:
                goal_type = " " + goal[2]
            goal_time = (goal[1] or "").replace("’", "'")
            team1_goals.append(goal[0] + " " + goal_time + goal_type)

        team2_goals = []
        for goal in games[day_key][game_id[0] - 1][1]["goals"]:
            goal_type = ""
            if goal[2]:
                goal_type = " " + goal[2]
            goal_time = (goal[1] or "").replace("’", "'")
            team2_goals.append(goal[0] + " " + goal_time + goal_type)

        score_text = f"{team1_score:>3} - {team2_score:<3}"
        x = measure_text(score_text, FONT_SIZE)
        draw_text(score_text,
                  400 - int(x / 2), int(480 / 4),
                  FONT_SIZE, BLACK)

        team1_len = measure_text(team1, FONT_SIZE)
        draw_text(team1, 400 - int(x / 2) - team1_len - 20,
                  int(480 / 4), FONT_SIZE, BLACK)

        if current_team1_logo != team1_logo:
            if current_team1_texture:
                unload_texture(current_team1_texture)
            current_team1_logo = team1_logo
            current_team1_texture = None
            if team1_logo:
                team1_image = load_image(team1_logo)
                current_team1_texture = load_texture_from_image(team1_image)
                unload_image(team1_image)
        if current_team1_texture:
            draw_texture(current_team1_texture,
                         400 - int(x / 2) - team1_len - 20 - 40,
                         int(480 / 4), WHITE)

        y = measure_text(team2, FONT_SIZE)
        draw_text(team2, 400 + int(x / 2) + 20, int(480 / 4),
                  FONT_SIZE, BLACK)

        if current_team2_logo != team2_logo:
            if current_team2_texture:
                unload_texture(current_team2_texture)
            current_team2_logo = team2_logo
            current_team2_texture = None
            if team2_logo:
                team2_image = load_image(team2_logo)
                current_team2_texture = load_texture_from_image(team2_image)
                unload_image(team2_image)
        if current_team2_texture:
            draw_texture(current_team2_texture, 400 + int(x / 2) + y + 40,
                         int(480 / 4), WHITE)

        for i in range(len(team1_goals)):
            goal_len = measure_text(team1_goals[i], 20)
            draw_text(team1_goals[i], 400 - int(x / 2) - goal_len - 20,
                      int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1),
                      20, BLACK)

        for i in range(len(team2_goals)):
            goal_len = measure_text(team2_goals[i], 20)
            draw_text(team2_goals[i],
                      400 + int(x / 2) + 20, int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1),
                      20, BLACK)

        if pronote:
            draw_pronote_compact(pronote.snapshot, pronote.display_date)
        draw_date_time()
        draw_weather(weather)

        # Draw the competitions dropdown box
        competitions_str = ";".join(c for c in all_scores)
        if gui_dropdown_box(Rectangle(20, 20, 200, BOX_HEIGHT), competitions_str, value, edit_box):
            edit_box = not edit_box
            competition_key = competitions_keys[value[0]]
            day_value = (0 if competition_key == "Pronote"
                         else len(all_scores[competition_key]) - 1)
            game_id[0] = 1
            ROTATE_TIME = time.time()

        if competition_key == "Pronote":
            end_drawing()
            continue

        # Draw the days dropdown box
        competitions_keys = list(all_scores)
        if pronote:
            competitions_keys.insert(0, "Pronote")
        competition_key = competitions_keys[value[0]]

        # Adjust the dropbox view
        tmp_day_value = day_value
        tmp_day_value = max(tmp_day_value, 5)
        min_day_value_dropbox = tmp_day_value - 5
        max_day_value_dropbox = tmp_day_value + 4
        day_value_dropbox[0] = day_value - min_day_value_dropbox

        days_str = ";".join([c for c in all_scores[competition_key]][min_day_value_dropbox:max_day_value_dropbox])
        if gui_dropdown_box(Rectangle(20 + 200 + 20, 20, 200, BOX_HEIGHT), days_str, day_value_dropbox, day_edit_box):
            day_edit_box = not day_edit_box
            day_value = min_day_value_dropbox + day_value_dropbox[0]
            game_id[0] = 1
            ROTATE_TIME = time.time()

        end_drawing()

    if current_team1_texture:
        unload_texture(current_team1_texture)
    if current_team2_texture:
        unload_texture(current_team2_texture)
    close_window()
