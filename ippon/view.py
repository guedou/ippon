# SPDX-License-Identifier: GPL-2.0+
"""800x480 touch viewer; the same logical canvas runs on macOS and the Pi."""

from collections import OrderedDict
from copy import deepcopy
import configparser
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import logging
import math
import re
import sys
import time

from ippon.config import StaticConfiguration
from ippon.display import DisplayMode
from ippon.ui_model import (NavigationState, ScoresService, all_goals,
                            format_match_date, latest_match, school_date,
                            sorted_rounds)

LOG = logging.getLogger(__name__)
WIDTH, HEIGHT = 800, 480
ASSETS = Path(__file__).parent / 'assets'
DAYS = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
          'août', 'septembre', 'octobre', 'novembre', 'décembre')
PALETTE = {'paper': 'f6f4ed', 'card': 'fffefa', 'ink': '182b2a',
           'muted': '52665d', 'green': '163d37', 'soft': 'e8ebdf',
           'line': 'd7dcd0', 'amber': '9a481f', 'pale': 'c5d8c9',
           'warning': 'f4e0d5'}


def get_weather_refresh_interval(config):
    try:
        return max(60, config.getint('core', 'weather_refresh_seconds', fallback=900))
    except (ValueError, configparser.Error, AttributeError):
        return 900


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'div', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = _PlainText()
    parser.feed(str(value or ''))
    return unescape(''.join(parser.parts)).strip()


def wrap_pixels(text, width, measure):
    """Wrap without dropping long words or imposing a character count."""
    lines = []
    for paragraph in str(text).replace('\r\n', '\n').split('\n'):
        if not paragraph.strip():
            lines.append('')
            continue
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if measure(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ''
            for char in word:
                if line and measure(line + char) > width:
                    lines.append(line)
                    line = ''
                line += char
        if line:
            lines.append(line)
    return lines or ['']


def contains(box, point):
    x, y, w, h = box
    return x <= point[0] < x + w and y <= point[1] < y + h


class PointerTracker:
    """One activation on release, cancelled by a drag or a different target."""
    def __init__(self):
        self.down = False
        self.start = None
        self.target = None
        self.cancelled = False

    def update(self, point, down, buttons, pressed=False, released=False):
        # Preserve a short tap when the backend reports both edges in one
        # frame. Events already discarded by raylib cannot be reconstructed.
        if pressed and released and not self.down:
            self.update(point, True, buttons)
            return self.update(point, False, buttons)
        if released:
            down = False
        elif pressed:
            down = True
        hit = next((b for b in reversed(buttons)
                    if not b[3] and contains(b[0], point)), None)
        result = None
        if down and not self.down:
            self.start = point
            self.target = hit
            self.cancelled = False
        if self.start is not None and (down or self.down):
            self.cancelled |= math.dist(self.start, point) > 24
            if self.target is not None and (hit is None or hit[1:3] != self.target[1:3]):
                self.cancelled = True
        if self.down and not down:
            if (not self.cancelled and self.target is not None and hit is not None
                    and hit[1:3] == self.target[1:3]):
                result = hit[1:3]
            self.start = self.target = None
        self.down = down
        return result


class Painter:
    def __init__(self, rl):
        self.r = rl
        self.colors = {k: rl.Color(*bytes.fromhex(v), 255) for k, v in PALETTE.items()}
        self.buttons = []
        self.pressed = None
        self.widths = {}
        self.textures = OrderedDict()
        self.fonts = {}
        glyphs = list(range(32, 384)) + [8211, 8212, 8216, 8217, 8220, 8221,
                                       8226, 8230, 8242, 8592, 8594, 9662, 215]
        # pyray 5.0 takes the address of an array argument, producing int(*)[].
        # Pass an explicit int* and keep its backing allocation alive until both
        # fonts have been loaded.
        codepoint_buffer = rl.ffi.new('int[]', glyphs)
        codepoints = rl.ffi.cast('int *', codepoint_buffer)
        try:
            for bold, name in ((False, 'NotoSans-Regular.ttf'),
                               (True, 'NotoSans-Bold.ttf')):
                font = rl.load_font_ex(str(ASSETS / 'fonts' / name), 64,
                                       codepoints, len(glyphs))
                if not font.texture.id:
                    raise RuntimeError('Impossible de charger la police embarquée.')
                rl.set_texture_filter(font.texture, rl.TEXTURE_FILTER_BILINEAR)
                self.fonts[bold] = font
        except Exception:
            self.close()
            raise

    def color(self, name):
        return self.colors[name]

    def rect(self, box):
        return self.r.Rectangle(*box)

    def card(self, box, color='card', border=True):
        self.r.draw_rectangle_rounded(self.rect(box), .13, 8, self.color(color))
        if border:
            x, y, w, h = box
            # Nested rounded rectangles avoid API differences in outline functions.
            self.r.draw_rectangle_rounded(self.rect(box), .13, 8, self.color('line'))
            self.r.draw_rectangle_rounded(self.rect((x+1, y+1, w-2, h-2)), .13, 8,
                                          self.color(color))

    def measure(self, text, size, bold=False):
        key = (str(text), size, bold)
        if key not in self.widths:
            if len(self.widths) > 4096:
                self.widths.clear()
            # Noto Sans has no arrow glyphs in some distributions. Measure
            # those symbols as vector icons, consistently with text().
            self.widths[key] = sum(
                size*.9 if part in ('→','←') else
                self.r.measure_text_ex(self.fonts[bold], part, size, 0).x
                for part in re.split('([→←])', str(text)) if part)
        return self.widths[key]

    def text(self, text, x, y, size=24, color='ink', bold=False):
        for part in re.split('([→←])', str(text)):
            if not part:
                continue
            if part in ('→','←'):
                self.icon('right' if part=='→' else 'left',x,y+size*.1,color,size*.8)
                x += size*.9
            else:
                self.r.draw_text_ex(self.fonts[bold], part, self.r.Vector2(x,y),
                                    size,0,self.color(color))
                x += self.measure(part,size,bold)

    def lines(self, text, box, size=24, color='ink', bold=False,
              max_lines=None, center=False):
        x, y, w, h = box
        lines = wrap_pixels(text, w, lambda s: self.measure(s, size, bold))
        line_height = size * 1.25
        limit = max_lines or max(1, int(h // line_height))
        if len(lines) > limit:
            lines = lines[:limit]
            while lines[-1] and self.measure(lines[-1] + '…', size, bold) > w:
                lines[-1] = lines[-1][:-1]
            lines[-1] += '…'
        for i, line in enumerate(lines):
            offset = max(0, (w - self.measure(line, size, bold)) / 2) if center else 0
            self.text(line, x+offset, y+i*line_height, size, color, bold)
        return len(lines)

    def icon(self, kind, x, y, color='ink', size=26):
        r, c = self.r, self.color(color)
        def line(a, b, d, e):
            r.draw_line_ex(r.Vector2(x+a*size, y+b*size),
                           r.Vector2(x+d*size, y+e*size), 2, c)
        if kind in ('left', 'right'):
            direction = -1 if kind == 'left' else 1
            line(.18, .5, .82, .5)
            tip = .18 if direction < 0 else .82
            line(tip, .5, .5, .18)
            line(tip, .5, .5, .82)
        elif kind == 'down':
            line(.2, .35, .5, .65); line(.5, .65, .8, .35)
        elif kind == 'home':
            line(.1, .45, .5, .1); line(.5, .1, .9, .45)
            line(.22, .35, .22, .9); line(.78, .35, .78, .9)
            line(.22, .9, .78, .9)
        elif kind == 'football':
            r.draw_circle_lines(int(x+size/2), int(y+size/2), size*.42, c)
            r.draw_circle(int(x+size/2), int(y+size/2), size*.12, c)
        elif kind == 'school':
            line(.05,.35,.5,.1); line(.5,.1,.95,.35)
            line(.05,.35,.5,.6); line(.5,.6,.95,.35)
            line(.25,.5,.25,.85); line(.25,.85,.75,.85); line(.75,.85,.75,.5)
        else:
            for dx in (.2, .5, .8):
                r.draw_circle(int(x+dx*size), int(y+.5*size), 2, c)

    def button(self, box, label, action, value=None, primary=False,
               disabled=False, sub=None, icon=None, align='center'):
        self.buttons.append((box, action, value, disabled))
        active = self.pressed == (action, value) and not disabled
        background = 'green' if primary else 'line' if active else 'soft'
        color = 'pale' if disabled and primary else 'muted' if disabled else 'card' if primary else 'ink'
        self.card(box, background, border=False)
        x, y, w, h = box
        if icon and not label:
            self.icon(icon, x+(w-30)/2, y+(h-30)/2, color, 30)
            return
        if label:
            size = 23
            self.lines(label, (x+14, y+(16 if sub else 25), w-28, 50), size,
                       color, primary, max_lines=1 if sub else 2, center=align=='center')
        if sub:
            self.lines(sub, (x+12, y+47, w-24, 27), 19,
                       'pale' if primary else 'muted', max_lines=1,
                       center=align=='center')

    def logo(self, team, box):
        url = str(team.get('logo') or '')
        if url.startswith('demo:'):
            name = url[5:]
            path = ASSETS / 'logos' / (name + '.png') if re.fullmatch(r'[a-z0-9_-]+', name) else None
        else:
            path = (Path(StaticConfiguration.config_logos_directory_path) /
                    (hashlib.md5(url.encode()).hexdigest()+'.png')) if url else None
        key = str(path) if path else ''
        now = time.monotonic()
        entry = self.textures.get(key)
        if entry is None or entry[0] is None and now-entry[1] > 30:
            texture = None
            if path and path.is_file():
                try:
                    loaded = self.r.load_texture(str(path))
                    if loaded.id:
                        texture = loaded
                        self.r.set_texture_filter(texture, self.r.TEXTURE_FILTER_BILINEAR)
                except (OSError, RuntimeError):
                    LOG.warning('Logo non lisible dans le cache.')
            entry = (texture, now)
            self.textures[key] = entry
        self.textures.move_to_end(key)
        while len(self.textures) > 24:
            _, (old, _) = self.textures.popitem(last=False)
            if old is not None:
                self.r.unload_texture(old)
        texture = entry[0]
        x, y, w, h = box
        if texture is not None:
            scale = min(w/texture.width, h/texture.height)
            width, height = texture.width*scale, texture.height*scale
            self.r.draw_texture_pro(texture, self.r.Rectangle(0, 0, texture.width, texture.height),
                                    self.r.Rectangle(x+(w-width)/2, y+(h-height)/2, width, height),
                                    self.r.Vector2(0, 0), 0, self.r.WHITE)
        else:
            name = str(team.get('name') or '?')
            initials = ''.join(word[0] for word in name.split() if word)[:3].upper() or '?'
            self.card(box, 'soft', border=False)
            self.lines(initials, (x+2, y+(h-16)/2, w-4, 24), 16, bold=True,
                       max_lines=1, center=True)

    def close(self):
        for texture, _ in self.textures.values():
            if texture is not None:
                self.r.unload_texture(texture)
        for font in self.fonts.values():
            self.r.unload_font(font)
        self.textures.clear()
        self.fonts.clear()


class Viewer:
    def __init__(self, painter, demo=False, demo_scenario='normal'):
        self.p = painter
        self.state = NavigationState()
        self.services = {}
        self.config_error = None
        self.data = {'football': {'competitions': {}}, 'school': {'days': {}}, 'weather': None}
        self.statuses = {}
        self._detail_snapshot = None
        self.demo = demo
        self.last_refresh = -math.inf
        self.today = date.today()
        if demo:
            from ippon.demo import demo_data
            data = demo_data(demo_scenario)
            self.data = {'football': data['scores'], 'school': data['school'], 'weather': data['weather']}
            self.statuses = data['statuses']
        else:
            try:
                # Validate each source independently: an incomplete Pronote
                # section must not disable valid football caches or the weather.
                config = configparser.ConfigParser(interpolation=None)
                if not config.read(StaticConfiguration.config_file_path, encoding='utf-8'):
                    raise FileNotFoundError(StaticConfiguration.config_file_path)
            except (OSError, ValueError, UnicodeError, configparser.Error):
                config = configparser.ConfigParser(interpolation=None)
                self.config_error = 'Configuration absente ou invalide.'
                LOG.warning(self.config_error)
            from ippon.pronote import PronoteService
            from ippon.weather import WeatherService
            self.services = {'football': ScoresService(config),
                             'school': PronoteService(config),
                             'weather': WeatherService(refresh_interval=get_weather_refresh_interval(config))}
            self.refresh(force=True)
        self.reconcile()

    @property
    def competitions(self):
        return (self.data['football'] or {}).get('competitions', {})

    @property
    def games(self):
        return self.competitions.get(self.state.competition, {}).get(self.state.round, [])

    @property
    def match(self):
        return self.games[self.state.match_index] if self.games else None

    def refresh(self, force=False):
        changed = False
        today = date.today()
        if today != self.today:
            self.today = today
            self.state.selected_day = None
            self.state.school_pages = {'courses': 0, 'homework': 0}
            if self.state.detail == 'homework':
                self.state.detail = None
                self.state.detail_page = 0
            if self.state.panel == 'day':
                self.state.panel_page = 0
            changed = True
        if self.demo or not force and time.monotonic()-self.last_refresh < .5:
            if changed:
                self.reconcile()
            return changed
        self.last_refresh = time.monotonic()
        for key, service in self.services.items():
            service.refresh()
            snapshot, status = service.get_snapshot(), service.status()
            if self.data[key] != snapshot or self.statuses.get(key) != status:
                self.data[key], self.statuses[key] = snapshot, status
                changed = True
        self.reconcile()
        return changed

    def reconcile(self):
        s = self.state
        if s.competition not in self.competitions:
            s.competition = next((name for name, rounds in self.competitions.items()
                                  if any(rounds.values())),
                                 next(iter(self.competitions), None))
        competition_rounds = self.competitions.get(s.competition, {})
        rounds = sorted_rounds(competition_rounds)
        if s.round not in rounds:
            latest = latest_match(self.competitions, s.competition)
            s.round = next((name for name, matches in competition_rounds.items()
                            if any(match is latest for match in matches)),
                           rounds[-1] if rounds else None)
            s.match_index = 0
        s.match_index = max(0, min(s.match_index, len(self.games)-1))
        if s.selected_day not in self.school_days():
            s.selected_day = self.today.isoformat()
            s.school_pages = {'courses': 0, 'homework': 0}
            if s.detail == 'homework':
                s.detail = None
                s.detail_page = 0
        items = self.school_items()
        s.school_pages[s.school_section] = max(0, min(s.school_pages[s.school_section], (len(items)-1)//2))
        if s.detail == 'goals' and not self.match:
            s.detail = None
            s.detail_page = 0
        if s.detail == 'homework' and s.detail_index >= len(self.school_items('homework')):
            s.detail = None
            s.detail_page = 0
        # Indices are not identities: a new snapshot can reorder/remove rows
        # while the user reads a detail. Return to its list rather than silently
        # displaying a different homework item or another match's scorers.
        if s.detail == 'homework':
            context = (s.detail, s.selected_day, s.detail_index,
                       self.school_items('homework'))
        elif s.detail == 'goals':
            context = (s.detail, s.competition, s.round, s.match_index, self.games)
        else:
            context = None
        if context is None:
            self._detail_snapshot = None
        elif self._detail_snapshot is None:
            self._detail_snapshot = deepcopy(context)
        elif context != self._detail_snapshot:
            s.detail = None
            s.detail_page = 0
            self._detail_snapshot = None

    def school_days(self):
        """Start at today even when only an old Pronote cache is available."""
        today = self.today.isoformat()
        days = (self.data['school'] or {}).get('days', {})
        return [today] + sorted(day for day in days if day > today)

    def school_items(self, section=None):
        key = 'lessons' if (section or self.state.school_section) == 'courses' else 'homework'
        return (self.data['school'] or {}).get('days', {}).get(self.state.selected_day, {}).get(key, [])

    def source_state(self, source):
        return self.statuses.get(source, {}).get('state', 'loading')

    def stamp(self, source):
        status = self.statuses.get(source, {})
        stamp = status.get('cache_updated_at') if source == 'football' else status.get('last_success')
        if stamp is None:
            stamp = (self.data[source] or {}).get('updated_at')
        prefix = 'Cache' if self.source_state(source) == 'cached' else 'Fichiers' if source == 'football' else 'Mise à jour'
        if stamp is None:
            return prefix+' · date inconnue'
        try:
            return prefix+' · '+datetime.fromtimestamp(stamp).strftime('%d/%m %H:%M')
        except (ValueError, OSError, OverflowError, TypeError):
            return prefix+' · date inconnue'

    def heading(self, title, subtitle=None, back=True):
        if back:
            self.p.button((16, 48, 80, 80), None, 'back', icon='left')
        self.p.lines(title, (112 if back else 20, 61 if subtitle else 75,
                            660 if back else 740, 62), 26, bold=True,
                     max_lines=1 if subtitle else 2)
        if subtitle:
            self.p.lines(subtitle, (112 if back else 20, 102, 660 if back else 740, 24),
                         19, 'muted', max_lines=1)

    def pager(self, page, total, kind, caption=''):
        self.p.button((16,304,80,80),None,kind+'-prev',disabled=page==0,icon='left')
        self.p.button((704,304,80,80),None,kind+'-next',disabled=page>=total-1,icon='right')
        self.p.lines(f'Page {page+1} / {total}', (104,315,592,32), 24, center=True, max_lines=1)
        if caption:
            self.p.lines(caption, (104,350,592,28), 20, 'muted', max_lines=1, center=True)

    def message(self, title, description, box=(16,136,768,160)):
        self.p.card(box)
        x,y,w,h = box
        self.p.lines(title,(x+20,y+24,w-40,65),28,bold=True,max_lines=2)
        self.p.lines(description,(x+20,y+95,w-40,56),21,'muted',max_lines=2)

    def unavailable(self, source, empty_title='Aucune donnée'):
        kind = self.source_state(source)
        if kind == 'loading':
            self.message('Chargement en cours', 'Les autres rubriques restent accessibles.')
        elif kind == 'unconfigured':
            self.message('Source non configurée', 'Ajoutez cette source dans la configuration d’Ippon.')
        elif kind == 'error':
            self.message('Données indisponibles',
                         self.statuses.get(source,{}).get('error') or
                         'Aucune donnée conservée pour cette source.')
        else:
            self.message(empty_title, 'Aucun contenu pour cette sélection.')
        self.p.lines(self.stamp(source), (24,329,752,40), 20, 'muted', max_lines=1)

    def draw(self):
        p,s = self.p,self.state
        p.buttons = []
        p.r.clear_background(p.color('paper'))
        now = datetime.now()
        p.text('ippon',20,8,25,bold=True)
        p.text('.',86,8,25,'amber',True)
        p.text(f'{DAYS[now.weekday()][:3]}. {now.day} {MONTHS[now.month-1]}',225,11,21)
        clock_text = now.strftime('%H:%M:%S')
        clock_x = WIDTH-20-p.measure(clock_text,26,True)
        if s.auto != 'off':
            label = 'Auto' if s.auto == 'running' else 'Auto en pause'
            p.text(label,clock_x-14-p.measure(label,17),15,17,'muted')
        p.text(clock_text,clock_x,7,26,bold=True)
        p.r.draw_line(0,47,800,47,p.color('line'))
        if s.panel:
            self.draw_selector()
        elif s.sources:
            self.draw_sources()
        elif s.detail == 'goals':
            self.draw_goals()
        elif s.detail == 'homework':
            self.draw_homework()
        elif s.page == 'home':
            self.draw_home()
        elif s.page == 'football':
            self.draw_football()
        elif s.page == 'school':
            self.draw_school()
        else:
            self.draw_options()
        p.r.draw_line(0,384,800,384,p.color('line'))
        for index,(page,label) in enumerate((('home','Accueil'),('football','Football'),('school','École'),('options','Options'))):
            # 3 * 213.33 + 104 + 3 * 8 = 768.
            x = 16+index*(640/3+8) if index < 3 else 680
            width = 640/3 if index < 3 else 104
            p.button((x,392,width,80), label if page!='options' else None, 'nav',page,
                     primary=s.page==page)
            if page=='options':
                p.icon('options',x+39,402,'card' if s.page==page else 'ink')
                p.text('Options',x+18,441,18,'card' if s.page==page else 'ink')

    def home_match(self):
        return latest_match(self.competitions, self.state.competition)

    def draw_home(self):
        p,s = self.p,self.state
        hero = (16,64,448,304)
        p.buttons.append((hero,'home-school' if s.show_school_home else 'home-football',None,False))
        p.card(hero,'green',False)
        school = self.data['school'] or {}
        chosen = school_date(school,self.today)
        if chosen is None or chosen < self.today.isoformat():
            chosen = self.today.isoformat()
        day = school.get('days',{}).get(chosen,{})
        first = next((x for x in day.get('lessons',[]) if not x.get('canceled')
                      and (chosen != self.today.isoformat()
                           or x.get('start','') >= datetime.now().strftime('%H:%M'))),None)
        pending = sum(not x.get('done') for x in day.get('homework',[]))
        state = self.source_state('school')
        show_school = s.show_school_home and state != 'unconfigured'
        if not show_school:
            # The entire hero remains an explicit, discoverable football target.
            p.buttons[-1] = (hero, 'home-football', None, False)
            title,detail,foot='Côté terrain.','Retrouvez les résultats et leurs buteurs.','Ouvrir Football →'
            label='LES RÉSULTATS À PORTÉE DE MAIN'
        elif state in ('loading','error','unconfigured'):
            title={'loading':'Chargement…','error':'Indisponible','unconfigured':'École'}[state]
            detail='Récupération de l’emploi du temps.' if state=='loading' else 'Aucun emploi du temps disponible.'
            foot='Ouvrir École →';label='ÉCOLE'
        elif chosen not in school.get('days',{}):
            label=self.day_label(chosen).upper()
            title='À actualiser'
            detail='Aucune donnée pour aujourd’hui.'
            foot='Ouvrir École →'
        else:
            label=self.day_label(chosen).upper()
            title=(('Prochain à ' if chosen == self.today.isoformat() else 'Début à ')
                   +str(first.get('start',''))) if first else 'Pas de cours'
            detail=(str(first.get('subject',''))+'\n'+str(first.get('classroom',''))) if first else 'Aucun cours prévu pour ce jour.'
            foot=f'{pending} devoir'+('s' if pending>1 else '')+' à faire →'
        p.lines(label,(36,83,408,48),19,'pale',True,max_lines=2)
        p.lines(title,(36,145,408,60),40,'card',True,max_lines=1)
        p.lines(detail,(36,209,408,82),25,'card',max_lines=2)
        p.lines(foot,(36,302,408,34),23,'card',max_lines=1)
        p.lines(self.stamp('school' if show_school else 'football'),(36,337,408,24),18,'pale',max_lines=1)
        weather = self.data['weather']
        p.card((476,64,308,146))
        p.text('PARIS · MÉTÉO',492,76,19,'muted',True)
        if not weather:
            p.lines('Chargement…' if self.source_state('weather')=='loading' else 'Indisponible',
                    (492,116,276,60),24,'muted',max_lines=2)
        else:
            p.text(str(weather.get('temperature','—'))+'°',492,107,42,bold=True)
            p.lines(weather.get('description',''),(590,112,178,52),20,'muted',max_lines=2)
            bottom = (self.stamp('weather') if self.source_state('weather') == 'cached' else
                      f"{weather.get('minimum','—')}–{weather.get('maximum','—')}° · pluie {weather.get('rain_chance','—')} %")
            p.lines(bottom,(492,176,276,26),19,'muted',max_lines=1)
        box=(476,222,308,146)
        p.buttons.append((box,'home-football',None,False));p.card(box)
        p.text('DERNIER RÉSULTAT',492,235,19,'muted',True)
        match=self.home_match()
        if match:
            t1,t2 = self.teams(match)
            p.logo(t1[0],(492,275,40,40));p.logo(t2[0],(728,275,40,40))
            p.lines(f'{t1[1]}–{t2[1]}',(540,270,180,48),36,bold=True,center=True,max_lines=1)
            p.lines(format_match_date(match.get('date')),(492,326,276,28),20,'muted',max_lines=1)
        else:
            p.lines('Chargement…' if self.source_state('football')=='loading' else 'Aucun résultat',
                    (492,279,276,60),25,'muted',max_lines=2)

    @staticmethod
    def teams(match):
        teams=match.get('teams',[]) if match else []
        result=[]
        for i in range(2):
            item=teams[i] if i<len(teams) else {}
            result.append((item.get('team'+str(i+1),{'name':'Équipe inconnue'}),item.get('score','—')))
        return result

    def draw_football(self):
        p,s=self.p,self.state
        p.button((16,48,468,80),s.competition or 'Compétition','select-competition',
                 sub='CHOISIR LA COMPÉTITION',align='left')
        p.button((492,48,292,80),s.round or 'Journée','select-round',sub='CHOISIR LA JOURNÉE')
        if not self.match:
            self.unavailable('football','Aucun résultat chargé');return
        p.card((16,136,768,160))
        t1,t2=self.teams(self.match)
        for x,team in ((28,t1),(508,t2)):
            p.logo(team[0],(x+92,143,56,56))
            p.lines(team[0].get('name',''),(x,205,264,82),23,bold=False,max_lines=3,center=True)
        p.lines(f'{t1[1]}–{t2[1]}',(303,150,194,76),62,bold=True,max_lines=1,center=True)
        p.lines('Terminé',(303,227,194,28),20,'muted',center=True,max_lines=1)
        p.lines(format_match_date(self.match.get('date')),(299,260,202,28),19,'muted',center=True,max_lines=1)
        p.button((16,304,80,80),None,'match-prev',disabled=s.match_index==0,icon='left')
        p.button((704,304,80,80),None,'match-next',disabled=s.match_index>=len(self.games)-1,icon='right')
        p.button((104,304,592,80),'Buteurs →','goals',primary=True,sub=f'Match {s.match_index+1} / {len(self.games)}')

    def draw_goals(self):
        p,s=self.p,self.state
        goals=all_goals(self.match or {})
        self.heading('Buteurs',format_match_date((self.match or {}).get('date')))
        if not goals:
            self.message('Aucun but','Ce match s’est terminé sans but.')
            p.lines(self.stamp('football'),(24,329,752,30),20,'muted',max_lines=1);return
        total=max(1,math.ceil(len(goals)/2));s.detail_page=min(s.detail_page,total-1)
        p.card((16,136,768,160))
        for i,g in enumerate(goals[s.detail_page*2:s.detail_page*2+2]):
            y=136+i*80
            p.logo(g.get('team',{}),(30,y+19,42,42))
            text=g.get('name','')
            p.lines(text,(88,y+7,560,56),22,max_lines=2)
            kind=g.get('kind')
            if kind in ('sp','csc'):
                p.text('Sur penalty' if kind=='sp' else 'Contre son camp',88,y+58,18,'muted')
            p.lines(g.get('minute',''),(655,y+23,111,35),23,bold=True,max_lines=1,center=True)
        self.pager(s.detail_page,total,'detail',self.stamp('football'))

    @staticmethod
    def day_label(value):
        try:
            d=date.fromisoformat(value)
            return f'{DAYS[d.weekday()]} {d.day} {MONTHS[d.month-1]}'
        except (TypeError,ValueError):
            return 'Aucune journée chargée'

    def draw_school(self):
        p,s=self.p,self.state
        label=self.day_label(s.selected_day)
        p.button((16,48,312,80),label,'select-day',align='left')
        p.button((336,48,220,80),'Cours','section','courses',primary=s.school_section=='courses')
        p.button((564,48,220,80),'Devoirs','section','homework',primary=s.school_section=='homework')
        items=self.school_items()
        if not items:
            kind='Aucun cours pour ce jour' if s.school_section=='courses' else 'Aucun devoir pour ce jour'
            if self.source_state('school') in ('loading','error','unconfigured'):
                self.unavailable('school',kind)
            elif s.selected_day not in (self.data['school'] or {}).get('days',{}):
                self.message('Journée non chargée',
                             self.statuses.get('school',{}).get('error') or
                             'Aucune donnée disponible pour cette date.')
                p.lines(self.stamp('school'),(24,329,752,40),20,'muted',max_lines=1)
            else:
                self.message(kind,'Journée reçue · '+label)
                p.lines(self.stamp('school'),(24,329,752,40),20,'muted',max_lines=1)
            return
        page=s.school_pages[s.school_section];total=math.ceil(len(items)/2)
        p.card((16,136,768,160))
        for i,item in enumerate(items[page*2:page*2+2]):
            y=136+i*80
            if s.school_section=='courses':
                p.text(item.get('start',''),30,y+10,24)
                p.text('→ '+str(item.get('end','')),30,y+43,20,'muted')
                width=490 if item.get('canceled') else 600
                p.lines(item.get('subject',''),(174,y+7,width,54),22,bold=True,max_lines=2)
                p.lines(item.get('classroom',''),(174,y+58,width,22),18,'muted',max_lines=1)
                if item.get('canceled'):
                    p.card((677,y+22,92,36),'warning',False);p.text('Annulé',686,y+30,18,'amber',True)
            else:
                p.buttons.append(((16,y,768,80),'homework',page*2+i,False))
                p.lines(item.get('subject',''),(30,y+7,610,35),23,bold=True,max_lines=1)
                preview=' '.join(plain_text(item.get('description','')).split())
                p.lines(preview,(30,y+46,610,28),20,'muted',max_lines=1)
                if item.get('done'):
                    p.text('Fait',670,y+26,20,'green',True)
                p.icon('right',738,y+27)
        self.pager(page,total,'school',self.stamp('school'))

    def homework_pages(self):
        items=self.school_items('homework')
        if not items or self.state.detail_index>=len(items):
            return ['Aucun texte disponible.']
        text=plain_text(items[self.state.detail_index].get('description',''))
        lines=wrap_pixels(text,732,lambda x:self.p.measure(x,24))
        return ['\n'.join(lines[i:i+4]) for i in range(0,len(lines),4)] or ['Aucun texte disponible.']

    def draw_homework(self):
        p,s=self.p,self.state
        items=self.school_items('homework')
        if s.detail_index>=len(items):
            s.detail=None;self.draw_school();return
        item=items[s.detail_index]
        self.heading(item.get('subject','Devoir'),self.day_label(s.selected_day))
        pages=self.homework_pages();s.detail_page=min(s.detail_page,len(pages)-1)
        p.card((16,136,768,160))
        # Pagination has already measured every line; do not ellipsize the reading page.
        for index,line in enumerate(pages[s.detail_page].split('\n')):
            p.text(line,32,148+index*32,24)
        self.pager(s.detail_page,len(pages),'detail','Texte complet du devoir'+(' · déjà fait' if item.get('done') else ''))

    def draw_options(self):
        p,s=self.p,self.state
        self.heading('Options',back=False)
        p.button((552,48,232,80),'Plein écran','fullscreen')
        p.card((16,136,768,160))
        for index,(label,sub,action,on) in enumerate((
            ('Rotation automatique','En pause · reprendre' if s.auto=='paused' else 'Activée' if s.auto=='running' else 'Arrêtée · activer','auto',s.auto!='off'),
            ('École sur l’accueil','Résumé affiché' if s.show_school_home else 'Résumé masqué','privacy',s.show_school_home))):
            y=136+80*index
            p.buttons.append(((16,y,768,80),action,None,False))
            p.text(label,32,y+10,25,bold=True);p.text(sub,32,y+47,20,'muted')
            p.card((705,y+24,56,32),'green' if on else 'line',False)
            p.r.draw_circle(745 if on else 721,y+40,12,p.color('card'))
        p.button((16,304,376,80),'État des sources →','sources')
        p.button((400,304,384,80),'Arrêter la rotation','auto-off',disabled=s.auto=='off')

    def draw_sources(self):
        p=self.p
        self.heading('État des sources',self.config_error)
        p.card((16,136,768,160))
        labels={'ready':'Disponible','cached':'Données conservées','loading':'Chargement',
                'empty':'Aucun contenu','error':'Indisponible','unconfigured':'Non configurée'}
        for i,(key,label) in enumerate((('football','Football'),('school','École'),('weather','Météo'))):
            y=142+i*52
            p.text(label,32,y+6,23,bold=True)
            state=self.source_state(key)
            label = ('Échec · données conservées' if self.statuses.get(key,{}).get('error')
                     and state=='cached' else labels.get(state,state))
            p.lines(label,(200,y,560,26),21,'amber' if state in ('error','cached') else 'muted',max_lines=1)
            p.lines(self.stamp(key),(200,y+28,560,22),18,'muted',max_lines=1)
        p.lines(self.statuses.get('school',{}).get('error') or
                ('Une source n’a pas pu être actualisée. Les données connues restent affichées.'
                if any(status.get('error') for status in self.statuses.values()) else
                'Les autres rubriques restent accessibles si une source échoue.'),
                (24,324,752,56),21,'muted',max_lines=2)

    def selector_values(self):
        s=self.state
        if s.panel=='competition':
            return [(name,name) for name in self.competitions]
        if s.panel=='round':
            return [(value,value) for value in reversed(sorted_rounds(self.competitions.get(s.competition,{})))]
        return [(value,self.day_label(value)) for value in self.school_days()]

    def draw_selector(self):
        p,s=self.p,self.state
        titles={'competition':'Choisir la compétition','round':'Choisir la journée','day':'Choisir le jour'}
        self.heading(titles[s.panel])
        values=self.selector_values()
        if not values:
            self.message('Aucun choix disponible','Les données n’ont pas encore été chargées.');return
        total=math.ceil(len(values)/2);s.panel_page=min(s.panel_page,total-1)
        for i,(value,label) in enumerate(values[s.panel_page*2:s.panel_page*2+2]):
            p.button((16,136+i*80,768,80),label,'choose',value,align='left')
        self.pager(s.panel_page,total,'panel')

    def dispatch(self, action, value=None):
        s=self.state
        s.interact()
        if action=='nav':
            s.navigate(value)
        elif action=='back':
            s.back()
        elif action=='home-school':
            s.navigate('school');s.selected_day=school_date(self.data['school'] or {},date.today())
            s.school_pages={'courses':0,'homework':0}
        elif action=='home-football':
            match=self.home_match();s.navigate('football')
            if match:
                for name,rounds in self.competitions.items():
                    for level,games in rounds.items():
                        if match in games:
                            s.competition,s.round,s.match_index=name,level,games.index(match)
        elif action.startswith('select-'):
            s.panel=action[7:];s.panel_page=0
        elif action=='choose':
            if s.panel=='competition':
                s.competition=value;s.round=None;s.match_index=0
            elif s.panel=='round':
                s.round=value;s.match_index=0
            else:
                s.selected_day=value;s.school_pages={'courses':0,'homework':0}
            s.panel=None
        elif action=='section':
            s.school_section=value
        elif action=='match-prev':
            s.match_index=max(0,s.match_index-1)
        elif action=='match-next':
            s.match_index=min(len(self.games)-1,s.match_index+1)
        elif action=='goals':
            s.detail='goals';s.detail_page=0
        elif action=='homework':
            s.detail='homework';s.detail_index=value;s.detail_page=0
        elif action in ('detail-prev','detail-next'):
            s.detail_page=max(0,s.detail_page+(1 if action.endswith('next') else -1))
        elif action in ('school-prev','school-next'):
            s.school_pages[s.school_section]=max(0,s.school_pages[s.school_section]+(1 if action.endswith('next') else -1))
        elif action in ('panel-prev','panel-next'):
            s.panel_page=max(0,s.panel_page+(1 if action.endswith('next') else -1))
        elif action=='privacy':
            s.show_school_home=not s.show_school_home
        elif action=='auto':
            s.set_auto(True,time.monotonic());s.navigate('home')
        elif action=='auto-off':
            s.set_auto(False,time.monotonic())
        elif action=='sources':
            s.sources=True
        self.reconcile()


def window_logic(demo=False,demo_scenario='normal',fullscreen=None,screenshot=None,frames=None):
    import pyray as rl
    rl.set_trace_log_level(rl.LOG_WARNING)
    flags = rl.FLAG_WINDOW_RESIZABLE
    if sys.platform == 'darwin':
        flags |= rl.FLAG_WINDOW_HIGHDPI
    rl.set_config_flags(flags)
    rl.init_window(WIDTH,HEIGHT,'ippon — démo' if demo else 'ippon')
    painter=target=None
    try:
        rl.set_window_min_size(400,240)
        rl.set_target_fps(30)
        rl.set_exit_key(rl.KEY_NULL)
        display = DisplayMode(rl, fullscreen)
        display.start()
        painter=Painter(rl)
        target=rl.load_render_texture(WIDTH,HEIGHT)
        if not target.id:
            raise RuntimeError('Impossible de créer le canevas graphique.')
        rl.set_texture_filter(target.texture,rl.TEXTURE_FILTER_BILINEAR)
        viewer=Viewer(painter,demo,demo_scenario)
        pointer=PointerTracker()
        dirty=True;clock=None;count=0
        while not rl.window_should_close():
            if rl.is_key_pressed(rl.KEY_Q):
                break
            if rl.is_key_pressed(rl.KEY_F):
                viewer.state.interact();display.toggle();dirty=True
                pointer.cancelled = True
            if rl.is_key_pressed(rl.KEY_ESCAPE):
                viewer.state.interact();viewer.state.back();dirty=True
                pointer.cancelled = True
            width,height=rl.get_screen_width(),rl.get_screen_height()
            scale=max(.01,min(width/WIDTH,height/HEIGHT))
            ox,oy=(width-WIDTH*scale)/2,(height-HEIGHT*scale)/2

            # Use the same raylib mouse stream as main. X11 and raylib map the
            # touchscreen to it; mixing its state with raw touch counts can
            # retain a press after the finger has already been released.
            pos=rl.get_mouse_position()
            down=rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT)
            press=rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)
            release=rl.is_mouse_button_released(rl.MOUSE_BUTTON_LEFT)
            # Pause automatic navigation before it can change the target under
            # a finger arriving on the exact rotation deadline.
            if (down or press) and not pointer.down:
                viewer.state.interact();dirty=True

            if viewer.refresh():
                dirty=True
            if viewer.state.tick(time.monotonic()):
                pointer.cancelled = True
                dirty=True
            second=datetime.now().strftime('%Y%m%d%H%M%S')
            if clock!=second:
                clock=second;dirty=True
            # Build hit targets before processing the very first tap, and use
            # the current layout when a source refreshes during a press.
            if dirty:
                rl.begin_texture_mode(target)
                viewer.draw()
                rl.end_texture_mode()
                dirty=False

            point=((pos.x-ox)/scale,(pos.y-oy)/scale)
            action=pointer.update(point,down,painter.buttons,pressed=press,released=release)
            pressed=pointer.target[1:3] if pointer.down and not pointer.cancelled and pointer.target else None
            if painter.pressed!=pressed:
                painter.pressed=pressed;dirty=True
            if action:
                if action[0]=='fullscreen':
                    display.toggle()
                else:
                    viewer.dispatch(*action)
                dirty=True
            if dirty:
                rl.begin_texture_mode(target)
                viewer.draw()
                rl.end_texture_mode()
                dirty=False
            rl.begin_drawing()
            rl.clear_background(painter.color('ink'))
            rl.draw_texture_pro(target.texture,rl.Rectangle(0,0,WIDTH,-HEIGHT),
                                rl.Rectangle(ox,oy,WIDTH*scale,HEIGHT*scale),
                                rl.Vector2(0,0),0,rl.WHITE)
            rl.end_drawing()
            count+=1
            if frames and count>=frames:
                break
        if screenshot:
            path=Path(screenshot).expanduser()
            path.parent.mkdir(parents=True,exist_ok=True)
            rl.take_screenshot(str(path))
            if not path.is_file():
                raise RuntimeError('La capture n’a pas été enregistrée.')
    finally:
        if target is not None:
            rl.unload_render_texture(target)
        if painter is not None:
            painter.close()
        rl.close_window()
