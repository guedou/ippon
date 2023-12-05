# SPDX-License-Identifier: GPL-2.0+
# Guillaume Valadon <guillaume@valadon.net>

import locale
import time

from cffi import FFI
from pyray import *


def test_window():

    ffi = FFI()

    init_window(800, 480, "ippon")

    FONT_SIZE = 30

    edit_box = False
    value = ffi.new("int *")

    day_edit_box = False
    day_value = ffi.new("int *")

    tmp1 = ffi.new("int *")
    yyy = 0

    spinner_value = ffi.new("int *")

    team1_logo = load_image("marseille.png")
    team1_texture = load_texture_from_image(team1_logo)

    team2_logo = load_image("le_havre.png")
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

        if False:
            for i in range(0, 480, 10):
                draw_line(0, i, 800, i, GRAY)

            for i in range(0, 800, 10):
                draw_line(i, 0, i, 480, GRAY)

        locale.setlocale(locale.LC_TIME, "fr_FR")
        draw_text(time.strftime("%a %d %b %Y %H:%M:%S", time.localtime()), 800 - 300, 480 - 40, 20, BLACK)

        gui_spinner(Rectangle(20 + 200 + 20 + 200 + 20, 20, 200, 20), "%d " % len(scores[value[0]]), spinner_value, 1, len(scores[value[0]]), False)

        #x = measure_text(scores[value[0]][spinner_value[0] - 1], 40)
        #draw_text(scores[value[0]][spinner_value[0] - 1], 400-int(x), 120, 40, BLACK)
        #draw_text(scores[value[0]][spinner_value[0] - 1], 200, 120, 40, BLACK)

        team1_score = scores[value[0]][spinner_value[0] - 1].split(" ")[1]
        team2_score = scores[value[0]][spinner_value[0] - 1].split(" ")[3]

        x = measure_text("%+3s - %-3s" % (team1_score, team2_score), FONT_SIZE)
        draw_text("%+3s - %-3s" % (team1_score, team2_score), 400 - int(x / 2), int(480 / 4), FONT_SIZE, BLACK)

        team1 = scores[value[0]][spinner_value[0] - 1].split(" ")[0]
        team1_len = measure_text(team1, FONT_SIZE)
        draw_text(team1, 400 - int(x / 2) - team1_len - 20, int(480 / 4), FONT_SIZE, BLACK)

        draw_texture(team1_texture, 400 - int(x / 2) - team1_len - 20 - 40, int(480 / 4), WHITE)

        team2 = scores[value[0]][spinner_value[0] - 1].split(" ")[-1]
        y = measure_text(team2, FONT_SIZE)
        draw_text(team2, 400 + int(x / 2) + 20, int(480 / 4), FONT_SIZE, BLACK)

        draw_texture(team2_texture, 400 + int(x / 2) + y + 40, int(480 / 4), WHITE)

        for i in range(len(goals)):
            goal_len = measure_text(goals[i], 20)
            draw_text(goals[i], 400 - int(x / 2) - goal_len - 20, int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1), 20, BLACK)

        for i in range(len(goals)):
            goal_len = measure_text(goals[i], 20)
            draw_text(goals[i], 400 + int(x / 2) + 20, int(480 / 4) + FONT_SIZE + FONT_SIZE * (i + 1), 20, BLACK)

        if gui_dropdown_box(Rectangle(20, 20, 200, 20), "Ligue 1 Uber Eats;Championnat d'Angleterre", value, edit_box):
            edit_box = not edit_box
            spinner_value[0] = 0
            #print(type(value), value[0])

        if gui_dropdown_box(Rectangle(20 + 200 + 20, 20, 200, 20), "1ème journée;2ème journée;3ème journée;4ème journée;5ème journée;6ème journée;7ème journée", day_value, day_edit_box):
            day_edit_box = not day_edit_box

        if False:
            xxx = gui_list_view(Rectangle(20, 60, 200, 120), "8ème journée;tue;wed;thur;fri", tmp1, yyy)
            if xxx != yyy:
                yyy = xxx
                print(xxx, tmp1[0])
        end_drawing()

    close_window()
