#!/usr/bin/env python3
"""Unit tests for ClickDict.

Sublime Text itself is not importable outside the editor, so this file
installs small stand-ins for ``sublime`` and ``sublime_plugin`` before
loading the plugin module.  Run with:

    python3 tests/test_click_dict.py -v
"""

import importlib.util
import os
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_PATH = os.path.join(ROOT, "click_dict.py")
SCHEMA = """
CREATE TABLE entries (
    word        TEXT PRIMARY KEY,
    word_lower  TEXT NOT NULL,
    phonetic    TEXT NOT NULL DEFAULT '',
    translation TEXT NOT NULL,
    frq         INTEGER NOT NULL DEFAULT 0,
    collins     INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE lemmas (
    form TEXT PRIMARY KEY COLLATE NOCASE,
    lemma TEXT NOT NULL
) WITHOUT ROWID;
"""

ENTRIES = [
    ("run", "rʌn", "v. 跑\nn. 奔跑", 100, 5),
    ("study", "ˈstʌdi", "n. 学习\nv. 研究", 200, 4),
    ("use", "juːz", "v. 使用\nn. 用途", 50, 5),
    ("box", "bɒks", "n. 盒子", 300, 3),
    ("well-known", "ˌwel ˈnəʊn", "a. 众所周知的", 0, 0),
    ("don't", "dəʊnt", "不要；禁忌", 0, 0),
    ("plugin", "ˈplʌɡɪn", "n. 插件", 0, 0),
    ("China", "", "n. 中国", 10, 0),
    ("china", "", "n. 瓷器", 500, 0),
    ("long", "", "第一行\n第二行\n第三行", 0, 0),
]


class FakeRegion(object):
    def __init__(self, a, b=None):
        self.a = a
        self.b = a if b is None else b

    def begin(self):
        return min(self.a, self.b)

    def end(self):
        return max(self.a, self.b)

    def empty(self):
        return self.a == self.b


class FakeSettings(object):
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class FakeView(object):
    def __init__(self, text, file_name="/tmp/document.md"):
        self._text = text
        self._file_name = file_name
        self._selection = [FakeRegion(0, 0)]
        self.popups = []
        self.hidden = 0

    def id(self):
        return 1

    def file_name(self):
        return self._file_name

    def is_valid(self):
        return True

    def window(self):
        return object()

    def sel(self):
        return self._selection

    def set_selection(self, a, b=None):
        self._selection = [FakeRegion(a, b)]

    def line(self, point):
        start = self._text.rfind("\n", 0, point) + 1
        end = self._text.find("\n", point)
        if end == -1:
            end = len(self._text)
        return FakeRegion(start, end)

    def substr(self, region):
        return self._text[region.begin():region.end()]

    def show_popup(self, content, **kwargs):
        self.popups.append((content, kwargs))

    def hide_popup(self):
        self.hidden += 1


class FakeSublime(types.ModuleType):
    def __init__(self):
        super().__init__("sublime")
        self.settings = FakeSettings()
        self.timeouts = []
        self.status_messages = []
        self.saved_settings = []

    def load_settings(self, name):
        return self.settings

    def save_settings(self, name):
        self.saved_settings.append((name, dict(self.settings.values)))

    def set_timeout(self, callback, delay=0):
        self.timeouts.append((callback, delay))

    def status_message(self, message):
        self.status_messages.append(message)

    def run_timeouts(self):
        pending, self.timeouts = self.timeouts, []
        for callback, _delay in pending:
            callback()


fake_sublime = FakeSublime()
fake_plugin = types.ModuleType("sublime_plugin")


class EventListener(object):
    pass


class TextCommand(object):
    def __init__(self, view):
        self.view = view


class ApplicationCommand(object):
    pass


fake_plugin.EventListener = EventListener
fake_plugin.TextCommand = TextCommand
fake_plugin.ApplicationCommand = ApplicationCommand

sys.modules["sublime"] = fake_sublime
sys.modules["sublime_plugin"] = fake_plugin

spec = importlib.util.spec_from_file_location("click_dict", PLUGIN_PATH)
click_dict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(click_dict)


def create_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
        [
            (word, word.lower(), phonetic, translation, frq, collins)
            for word, phonetic, translation, frq, collins in ENTRIES
        ],
    )
    conn.executemany(
        "INSERT INTO lemmas(form, lemma) VALUES (?, ?)",
        [
            ("running", "run"),
            ("studies", "study"),
            ("used", "use"),
            ("boxes", "box"),
        ],
    )
    conn.commit()
    conn.close()


class ClickDictTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tempdir.name, "dictionary.db")
        create_database(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def setUp(self):
        fake_sublime.settings = FakeSettings(
            {
                "enabled": True,
                "enabled_extensions": [".txt", ".md", ".markdown"],
                "click_delay_ms": 0,
                "show_phonetic": True,
                "max_definition_chars": 1200,
                "dictionary_path": self.db_path,
            }
        )
        fake_sublime.timeouts = []
        fake_sublime.status_messages = []
        fake_sublime.saved_settings = []
        click_dict._dictionary = click_dict.CompactDictionary(self.db_path)
        click_dict._dictionary_path = self.db_path

    # -- word extraction -------------------------------------------------
    def test_extract_word_inside_and_at_end(self):
        self.assertEqual(click_dict.extract_word("hello world", 2), ("hello", 0))
        self.assertEqual(click_dict.extract_word("hello world", 5), ("hello", 0))
        self.assertEqual(click_dict.extract_word("hello world", 7), ("world", 6))
        self.assertEqual(click_dict.extract_word("hello world", 11), ("world", 6))

    def test_extract_word_at_returns_absolute_point(self):
        view = FakeView("first line\nsecond running here")
        view.set_selection(20)
        token, start = click_dict.extract_word_at(view, 20)
        self.assertEqual(token, "running")
        self.assertEqual(start, 18)

    def test_extract_word_hyphen_apostrophe_punctuation(self):
        self.assertEqual(click_dict.extract_word("well-known", 5), ("well-known", 0))
        self.assertEqual(click_dict.extract_word("don't", 2), ("don't", 0))
        self.assertEqual(click_dict.extract_word("hello.", 5), ("hello", 0))
        self.assertEqual(click_dict.extract_word("hello.", 6), (None, -1))
        self.assertEqual(click_dict.extract_word("", 0), (None, -1))

    def test_candidates(self):
        self.assertEqual(
            click_dict.base_candidates("well-known"),
            ["well-known", "well", "known"],
        )
        self.assertIn("run", click_dict.suffix_candidates("running"))
        self.assertIn("study", click_dict.suffix_candidates("studies"))
        self.assertIn("use", click_dict.suffix_candidates("used"))

    # -- dictionary ------------------------------------------------------
    def test_lookup_exact_and_case(self):
        self.assertEqual(click_dict.lookup_word("run")["word"], "run")
        self.assertEqual(click_dict.lookup_word("Running")["word"], "run")
        self.assertEqual(click_dict.lookup_word("China")["translation"], "n. 中国")
        self.assertEqual(click_dict.lookup_word("china")["translation"], "n. 瓷器")

    def test_lookup_lemma_and_suffix(self):
        self.assertEqual(click_dict.lookup_word("running")["word"], "run")
        self.assertEqual(click_dict.lookup_word("studies")["word"], "study")
        self.assertEqual(click_dict.lookup_word("used")["word"], "use")
        self.assertEqual(click_dict.lookup_word("boxes")["word"], "box")

    def test_lookup_missing(self):
        self.assertIsNone(click_dict.lookup_word("zzzznotaword"))
        self.assertIsNone(click_dict.lookup_word(""))

    def test_render_popup_escapes_and_truncates(self):
        entry = {
            "word": "<run>",
            "phonetic": "rʌn",
            "translation": "a < b & c",
        }
        content = click_dict.render_popup(entry)
        self.assertIn("&lt;run&gt;", content)
        self.assertIn("a &lt; b &amp; c", content)
        self.assertIn("/rʌn/", content)

        long_entry = {"word": "long", "phonetic": "", "translation": "x" * 50}
        content = click_dict.render_popup(long_entry, max_chars=10)
        self.assertIn("x" * 10 + "…", content)
        self.assertNotIn("x" * 11, content)

    # -- click handling --------------------------------------------------
    def _single_click(self, listener, view, point):
        args = {"event": {"button": 1, "x": 1, "y": 1}}
        view.set_selection(point)
        listener.on_text_command(view, "drag_select", args)
        listener.on_post_text_command(view, "drag_select", args)

    def test_single_click_shows_popup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        self.assertEqual(len(fake_sublime.timeouts), 1)
        fake_sublime.run_timeouts()
        self.assertEqual(len(view.popups), 1)
        content, kwargs = view.popups[0]
        self.assertIn("run", content)
        self.assertIn("跑", content)
        self.assertEqual(kwargs["location"], 4)

    def test_click_uses_absolute_popup_location(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("header\nsecond running here")
        self._single_click(listener, view, 16)
        fake_sublime.run_timeouts()
        self.assertEqual(len(view.popups), 1)
        self.assertEqual(view.popups[0][1]["location"], 16)

    def test_double_click_does_not_show(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        args = {"event": {"button": 1}, "by": "words"}
        view.set_selection(2, 9)
        listener.on_text_command(view, "drag_select", args)
        listener.on_post_text_command(view, "drag_select", args)
        fake_sublime.run_timeouts()
        self.assertEqual(view.popups, [])

    def test_double_click_hides_existing_popup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        fake_sublime.run_timeouts()
        self.assertEqual(len(view.popups), 1)

        args = {"event": {"button": 1}, "by": "words"}
        view.set_selection(2, 9)
        listener.on_text_command(view, "drag_select", args)
        listener.on_post_text_command(view, "drag_select", args)
        self.assertEqual(view.hidden, 1)

    def test_selection_hides_existing_popup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        fake_sublime.run_timeouts()
        self.assertEqual(len(view.popups), 1)

        view.set_selection(2, 9)
        listener.on_selection_modified(view)
        self.assertEqual(view.hidden, 1)

    def test_empty_selection_does_not_hide_popup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        fake_sublime.run_timeouts()
        view.set_selection(4)
        listener.on_selection_modified(view)
        self.assertEqual(view.hidden, 0)

    def test_drag_selection_does_not_show(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        args = {"event": {"button": 1}}
        view.set_selection(2, 9)
        listener.on_text_command(view, "drag_select", args)
        listener.on_post_text_command(view, "drag_select", args)
        self.assertEqual(fake_sublime.timeouts, [])

    def test_modified_click_is_ignored(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        args = {"event": {"button": 1, "modifiers": ["ctrl"]}}
        view.set_selection(4)
        listener.on_text_command(view, "drag_select", args)
        listener.on_post_text_command(view, "drag_select", args)
        self.assertEqual(fake_sublime.timeouts, [])

    def test_unsupported_extension_is_ignored(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.", file_name="/tmp/code.py")
        self._single_click(listener, view, 4)
        self.assertEqual(fake_sublime.timeouts, [])

    def test_typing_cancels_pending_lookup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        listener.on_modified(view)
        fake_sublime.run_timeouts()
        self.assertEqual(view.popups, [])

    def test_click_on_whitespace_hides_popup(self):
        listener = click_dict.ClickDictListener()
        view = FakeView("A running plugin.")
        self._single_click(listener, view, 4)
        fake_sublime.run_timeouts()
        self.assertEqual(len(view.popups), 1)

        self._single_click(listener, view, 1)
        fake_sublime.run_timeouts()
        self.assertEqual(view.hidden, 1)

    # -- commands --------------------------------------------------------
    def test_lookup_command(self):
        view = FakeView("A plugin.", file_name="/tmp/code.py")
        view.set_selection(2)
        click_dict.ClickDictLookupCommand(view).run(None)
        self.assertEqual(len(view.popups), 1)
        self.assertIn("插件", view.popups[0][0])

    def test_toggle_command(self):
        click_dict.ClickDictToggleCommand().run()
        self.assertFalse(fake_sublime.settings.get("enabled"))
        self.assertEqual(fake_sublime.saved_settings[0][0], "ClickDict.sublime-settings")


if __name__ == "__main__":
    unittest.main()
