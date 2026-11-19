# ClickDict

English | [简体中文](README.md)

A tiny, fully offline English–Chinese dictionary popup for Sublime Text. Click any English word in a Markdown or plain-text file and see its Chinese meaning next to the cursor.

## Features

- Click an English word → a popup shows the word, phonetic transcription, and Chinese definition
- Only active in `.txt`, `.md`, and `.markdown` files, so it stays out of the way while coding
- No popup for double-clicks, drag selections, or modifier-clicks
- About 400,000 English headwords from ECDICT, including common technical vocabulary
- No error dialog when a word is not found

## Installation

Clone the repository directly into Sublime Text's `Packages/ClickDict` directory (macOS example):

```bash
git clone https://github.com/bing9393/sublime-clickdict.git \
  "$HOME/Library/Application Support/Sublime Text/Packages/ClickDict"
```

On other platforms, clone it into the equivalent `Packages/ClickDict` directory used by Sublime Text.

Then restart Sublime Text. `Preferences → Browse Packages…` opens the Packages directory.

> The repository contains a ~39 MB offline dictionary (`dictionary.db`), so the first clone may take a moment.

## Usage

1. Open an English `.md` or `.txt` file.
2. Single-click an English word.
3. The definition popup appears; click elsewhere or press `Esc` to close it.

You can also use the Command Palette (`Cmd+Shift+P`):

- `ClickDict: Look Up Word at Cursor` — look up the word at the cursor, including in code files
- `ClickDict: Toggle Click Lookup` — temporarily enable or disable click lookups

## Configuration

Open `Preferences → Package Settings → ClickDict → Settings`, or edit
`Packages/ClickDict/ClickDict.sublime-settings` directly:

```json
{
    "enabled": true,
    "enabled_extensions": [".txt", ".md", ".markdown"],
    "click_delay_ms": 220,
    "show_phonetic": true,
    "max_definition_chars": 1200,
    "dictionary_path": ""
}
```

| Setting | Description |
| --- | --- |
| `enabled` | Master switch for click lookups |
| `enabled_extensions` | File extensions where lookup is active; add your own |
| `click_delay_ms` | Delay after a click before lookup, used to avoid double-clicks; higher values reduce accidental popups |
| `show_phonetic` | Show phonetic transcription |
| `max_definition_chars` | Maximum definition length; longer text is truncated |
| `dictionary_path` | Custom dictionary path; leave empty to use the bundled `dictionary.db` |

## Development and testing

```bash
python3 tests/test_click_dict.py -v
```

The tests use stubbed `sublime` / `sublime_plugin` modules, so Sublime does not need to be running.

### Rebuilding the dictionary

The dictionary is built from ECDICT by `tools/build_dictionary.py`:

```bash
# Download the ECDICT data (~22 MB)
curl -L -o tools/ecdict.tgz https://registry.npmjs.org/ecdict/-/ecdict-0.0.4.tgz
tar xzf tools/ecdict.tgz -C tools

python3 tools/build_dictionary.py \
  --csv tools/package/assets/ecdict.csv \
  --lemma tools/package/assets/lemma.en.txt \
  --out dictionary.db
```

Data source: [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT) (MIT License).

## Implementation notes

- Listens for Sublime's `drag_select` text command and confirms a plain single click in `on_post_text_command`.
- Waits `click_delay_ms`, then checks the cursor and selection again to avoid double-click and drag false positives.
- Extracts the full English word from the current line with a regex, including hyphens, apostrophes, and possessives; the popup is anchored at the mouse click position.
- Lookup order: exact word → possessive/hyphen parts → ECDICT lemma table (e.g. `running → run`) → conservative suffix stripping.
- Uses SQLite read-only queries through the `word_lower` index.
- Compatible with the Python 3.3 plugin host in Sublime Text 4.

## Known limitations

- English words only; no whole-sentence translation.
- A single click also moves the text cursor. This is Sublime Text's default behavior and the plugin does not prevent it.
- No audio pronunciation or vocabulary notebook.
- The repository does not bundle a demo article; use your own `.md` / `.txt` files.

## License

Code is released under the MIT License. See [LICENSE](LICENSE).

The offline dictionary data comes from [ECDICT](https://github.com/skywind3000/ECDICT), also released under the MIT License. `dictionary.db` in this repository is derived from that data.
