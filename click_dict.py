"""ClickDict - click an English word in Sublime Text to see its Chinese meaning.

The plugin is intentionally small: no network, no audio, no vocabulary
notebook.  It listens for a plain single left click in text/Markdown
views, finds the word under the click, looks it up in a bundled SQLite
dictionary, and shows a popup next to the word.
"""

import html
import os
import re
import sqlite3

import sublime
import sublime_plugin

SETTINGS_FILE = "ClickDict.sublime-settings"
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(PACKAGE_DIR, "dictionary.db")

# A clickable token: letters, with internal apostrophes/hyphens/dots.
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’.\-]*[A-Za-z]|[A-Za-z]")
SUFFIX_RE = re.compile(r"^[A-Za-z]+$")

ENTRY_SQL = """
SELECT word, phonetic, translation
FROM entries
WHERE word_lower = ?
ORDER BY (word = ?) DESC,
         CASE WHEN frq > 0 THEN 0 ELSE 1 END,
         frq ASC,
         collins DESC
LIMIT 1
"""

LEMMA_SQL = "SELECT lemma FROM lemmas WHERE form = ? COLLATE NOCASE LIMIT 1"


# ---------------------------------------------------------------------------
# Word extraction


def extract_word(text, column):
    """Return (word, start) for the token at ``column`` in ``text``.

    Clicks at the end of a word still select that word; clicks on
    surrounding punctuation return ``(None, -1)``.
    """
    if not text:
        return None, -1
    column = max(0, min(column, len(text)))

    for match in TOKEN_RE.finditer(text):
        if match.start() <= column < match.end():
            return match.group(0), match.start()
        if column == match.end():
            return match.group(0), match.start()
    return None, -1


def extract_word_at(view, point):
    line = view.line(point)
    text = view.substr(line)
    word, offset = extract_word(text, point - line.begin())
    if word is None:
        return None, -1
    # show_popup() expects an absolute buffer point, not a line offset.
    return word, line.begin() + offset


# ---------------------------------------------------------------------------
# Lookup candidates


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        value = (value or "").strip().strip("'-.")
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def base_candidates(token):
    """Literal spellings worth trying before any morphological guessing."""
    token = (token or "").strip().replace("’", "'")
    values = [token]
    lower = token.lower()
    if lower.endswith("'s"):
        values.append(token[:-2])
    if lower.endswith("s'"):
        values.append(token[:-2])
    if "-" in token:
        values.extend(part for part in token.split("-") if part)
    return _dedupe(values)


def suffix_candidates(token):
    """Conservative suffix stripping used only when literal forms fail."""
    word = (token or "").strip().replace("’", "'")
    if not SUFFIX_RE.match(word):
        return []
    lower = word.lower()
    values = []
    if len(lower) > 4 and lower.endswith("ies"):
        values.append(lower[:-3] + "y")
    if len(lower) > 4 and lower.endswith("ied"):
        values.append(lower[:-3] + "y")
    if len(lower) > 4 and lower.endswith("ves"):
        values.append(lower[:-3] + "f")
        values.append(lower[:-3] + "fe")
    if len(lower) > 7 and lower.endswith("ization"):
        values.append(lower[:-7] + "ize")
    if len(lower) > 7 and lower.endswith("isation"):
        values.append(lower[:-7] + "ise")
    if len(lower) > 4 and lower.endswith("ing"):
        stem = lower[:-3]
        values.append(stem + "e")
        values.append(stem)
        if len(stem) > 2 and stem[-1] == stem[-2]:
            values.append(stem[:-1])
    if len(lower) > 3 and lower.endswith("ed"):
        stem = lower[:-2]
        values.append(stem + "e")
        if len(stem) >= 3:
            values.append(stem)
            if len(stem) > 2 and stem[-1] == stem[-2]:
                values.append(stem[:-1])
    if len(lower) > 3 and lower.endswith("es"):
        values.append(lower[:-2])
        values.append(lower[:-1])
    if len(lower) > 2 and lower.endswith("s") and not lower.endswith("ss"):
        values.append(lower[:-1])
    if len(lower) > 4 and lower.endswith("ly"):
        values.append(lower[:-2])
    if len(lower) > 4 and lower.endswith("er"):
        values.append(lower[:-2])
        values.append(lower[:-1])
    if len(lower) > 5 and lower.endswith("est"):
        values.append(lower[:-3])
        values.append(lower[:-2])
    return _dedupe(values)


# ---------------------------------------------------------------------------
# SQLite dictionary


class CompactDictionary(object):
    def __init__(self, path):
        self.path = path
        self._conn = None
        self._error = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        if not os.path.isfile(self.path):
            raise IOError("dictionary not found: {}".format(self.path))
        # ST may run plugins on a legacy Python whose sqlite3 lacks uri=.
        conn = sqlite3.connect(self.path, timeout=1.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    def _query(self, word):
        if not word:
            return None
        conn = self._connect()
        return conn.execute(ENTRY_SQL, (word.lower(), word)).fetchone()

    def lookup(self, token):
        if not token:
            return None
        try:
            for candidate in base_candidates(token):
                row = self._query(candidate)
                if row is not None:
                    return row

            # Explicit inflected-form -> lemma mappings from ECDICT.
            for candidate in base_candidates(token):
                conn = self._connect()
                row = conn.execute(LEMMA_SQL, (candidate,)).fetchone()
                if row is not None:
                    result = self._query(row["lemma"])
                    if result is not None:
                        return result

            for candidate in suffix_candidates(token):
                row = self._query(candidate)
                if row is not None:
                    return row
        except (sqlite3.Error, IOError) as exc:
            self._error = str(exc)
            return None
        return None


_dictionary = None
_dictionary_path = None


def _settings():
    return sublime.load_settings(SETTINGS_FILE)


def _configured_dictionary_path():
    configured = _settings().get("dictionary_path") or ""
    configured = os.path.expanduser(str(configured).strip())
    if not configured:
        return DEFAULT_DB_PATH
    if not os.path.isabs(configured):
        configured = os.path.join(PACKAGE_DIR, configured)
    return configured


def get_dictionary():
    global _dictionary, _dictionary_path
    path = _configured_dictionary_path()
    if _dictionary is None or path != _dictionary_path:
        _dictionary = CompactDictionary(path)
        _dictionary_path = path
    return _dictionary


def lookup_word(token):
    return get_dictionary().lookup(token)


# ---------------------------------------------------------------------------
# Rendering and view helpers


def render_popup(entry, max_chars=1200, show_phonetic=True):
    translation = (entry["translation"] or "").replace("\\n", "\n").strip()
    if len(translation) > max_chars:
        translation = translation[:max_chars].rstrip() + "…"

    lines = [html.escape(line) for line in translation.splitlines() if line.strip()]
    body = "<br>".join(lines)
    head = "<b>{}</b>".format(html.escape(entry["word"]))

    phonetic = (entry["phonetic"] or "").strip()
    if show_phonetic and phonetic:
        head += ' <span style="color:color(var(--foreground) a(0.65));">/{}/</span>'.format(
            html.escape(phonetic.strip("/"))
        )

    return (
        '<div style="padding:6px 10px; color:var(--foreground); background-color:var(--background);">'
        + '<div style="font-size:1.25rem; font-weight:bold;">'
        + head
        + "</div>"
        + '<div style="font-size:1.05rem; margin-top:4px;">'
        + body
        + "</div></div>"
    )


def _normalized_extensions(settings):
    values = settings.get("enabled_extensions") or [".txt", ".md", ".markdown"]
    result = set()
    for value in values:
        value = str(value).strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = "." + value
        result.add(value)
    return result


def is_supported_view(view):
    if not _settings().get("enabled", True):
        return False
    name = view.file_name()
    if not name:
        return False
    extension = os.path.splitext(name)[1].lower()
    return extension in _normalized_extensions(_settings())


def _show_definition(view, entry, location):
    settings = _settings()
    content = render_popup(
        entry,
        max_chars=int(settings.get("max_definition_chars", 1200) or 1200),
        show_phonetic=bool(settings.get("show_phonetic", True)),
    )
    view.show_popup(
        content,
        location=location,
        max_width=520,
        max_height=360,
    )


# ---------------------------------------------------------------------------
# Click handling


class ClickDictListener(sublime_plugin.EventListener):
    def __init__(self):
        # Per-view generation counters invalidate stale click timers.
        self._generation = {}
        self._popup_views = set()

    def _bump(self, view):
        view_id = view.id()
        generation = self._generation.get(view_id, 0) + 1
        self._generation[view_id] = generation
        return generation

    def _hide(self, view):
        try:
            view.hide_popup()
        except Exception:
            pass
        self._popup_views.discard(view.id())

    def _hide_if_ours(self, view):
        if view.id() in self._popup_views:
            self._hide(view)

    def on_text_command(self, view, command_name, args):
        # A new press always invalidates an older pending lookup.
        if command_name == "drag_select":
            self._bump(view)

    def on_post_text_command(self, view, command_name, args):
        if command_name != "drag_select":
            return

        event = args.get("event") or {}
        if event.get("button") not in (None, 1):
            return
        if event.get("modifiers"):
            return
        if args.get("by"):
            self._hide_if_ours(view)
            return
        if not is_supported_view(view):
            return

        selection = view.sel()
        if len(selection) != 1:
            return
        if not selection[0].empty():
            # A drag or double-click selected text; never cover it.
            self._hide(view)
            return

        generation = self._bump(view)
        try:
            delay = int(_settings().get("click_delay_ms", 220) or 0)
        except Exception:
            delay = 220
        sublime.set_timeout(
            lambda: self._lookup_click(view, generation),
            max(0, delay),
        )

    def _lookup_click(self, view, generation):
        if self._generation.get(view.id()) != generation:
            return
        if not view.is_valid() or not is_supported_view(view):
            return

        # Read the cursor only after the delay, once Sublime has finished
        # updating the selection for the click.
        selection = view.sel()
        if len(selection) != 1 or not selection[0].empty():
            return
        point = selection[0].b

        token, _start = extract_word_at(view, point)
        if not token:
            self._hide(view)
            return

        entry = lookup_word(token)
        if entry is None:
            self._hide(view)
            return

        # Anchor at the click itself, not the word start, so the popup
        # appears next to the cursor even for long words.
        try:
            _show_definition(view, entry, point)
        except Exception:
            return
        self._popup_views.add(view.id())

    def on_selection_modified(self, view):
        # A drag selection or double-click must never leave our popup over it.
        if any(not region.empty() for region in view.sel()):
            self._bump(view)
            self._hide_if_ours(view)

    def on_modified(self, view):
        # Typing invalidates a click lookup that has not fired yet.
        self._bump(view)

    def on_close(self, view):
        view_id = view.id()
        self._generation.pop(view_id, None)
        self._popup_views.discard(view_id)


# ---------------------------------------------------------------------------
# Commands


class ClickDictLookupCommand(sublime_plugin.TextCommand):
    """Look up the word at the cursor, including in code files."""

    def run(self, edit):
        view = self.view
        selection = view.sel()
        point = selection[0].b if len(selection) else 0
        token, _start = extract_word_at(view, point)
        if not token:
            sublime.status_message("ClickDict: 光标处没有英文单词")
            return
        entry = lookup_word(token)
        if entry is None:
            sublime.status_message("ClickDict: 词典中未找到 “{}”".format(token))
            return
        _show_definition(view, entry, point)


class ClickDictToggleCommand(sublime_plugin.ApplicationCommand):
    """Toggle single-click lookups on or off."""

    def run(self):
        settings = _settings()
        enabled = not bool(settings.get("enabled", True))
        settings.set("enabled", enabled)
        sublime.save_settings(SETTINGS_FILE)
        sublime.status_message(
            "ClickDict: 单击查词已{}".format("开启" if enabled else "关闭")
        )

