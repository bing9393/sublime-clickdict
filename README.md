# ClickDict

[English](README.en.md) | 简体中文

A tiny, fully offline English–Chinese dictionary popup for Sublime Text. Click any English word in a Markdown or plain-text file and see its Chinese meaning next to the cursor.

在 Sublime Text 里阅读英文 `.txt` / `.md` 文档时，**单击任意英文单词**，旁边会弹出悬浮窗显示中文释义。完全离线，不联网。

## 功能

- 单击英文单词 → 在单词位置显示「单词 + 音标 + 中文释义」
- 只在 `.txt`、`.md`、`.markdown` 中触发，写代码时不会误触
- 双击选词、拖拽选择、按住修饰键点击都不会弹窗
- 离线词典约 40 万个英文单词（ECDICT 数据），含常见技术词汇
- 查不到时不打扰：不弹错误窗口

## 安装

把仓库直接 clone 到 Sublime Text 的 `Packages/ClickDict`：

```bash
git clone https://github.com/bing9393/sublime-clickdict.git \
  "$HOME/Library/Application Support/Sublime Text/Packages/ClickDict"
```

然后重启 Sublime Text。菜单 `Preferences → Browse Packages…` 可以直接打开 Packages 目录。

> 仓库包含约 39 MB 的离线词典 `dictionary.db`，首次 clone 会稍慢。

## 使用

1. 打开英文 `.md` 或 `.txt` 文件。
2. 用鼠标单击一个英文单词。
3. 释义弹窗出现；单击别处或按 `Esc` 关闭。

也可以用命令面板（`Cmd+Shift+P`）执行：

- `ClickDict: Look Up Word at Cursor`：查询光标处单词（代码文件里也能用）
- `ClickDict: Toggle Click Lookup`：临时开启/关闭单击查词

## 配置

`Preferences → Package Settings → ClickDict → Settings`，或直接编辑
`Packages/ClickDict/ClickDict.sublime-settings`：

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

| 配置 | 说明 |
| --- | --- |
| `enabled` | 单击查词总开关 |
| `enabled_extensions` | 生效的文件扩展名，可自行添加 |
| `click_delay_ms` | 单击后延迟查询，用于避开双击；越大越不容易误弹 |
| `show_phonetic` | 是否显示音标 |
| `max_definition_chars` | 释义最大字符数，超出截断 |
| `dictionary_path` | 自定义词典路径，留空使用内置 `dictionary.db` |

## 开发与测试

```bash
python3 tests/test_click_dict.py -v
```

测试使用模拟的 `sublime` / `sublime_plugin` 模块，不需要启动 Sublime。

### 重新构建词典

词典由 ECDICT 构建，生成脚本在 `tools/build_dictionary.py`：

```bash
# 下载 ECDICT 数据（约 22 MB）
curl -L -o tools/ecdict.tgz https://registry.npmjs.org/ecdict/-/ecdict-0.0.4.tgz
tar xzf tools/ecdict.tgz -C tools

python3 tools/build_dictionary.py \
  --csv tools/package/assets/ecdict.csv \
  --lemma tools/package/assets/lemma.en.txt \
  --out dictionary.db
```

数据来源：[skywind3000/ECDICT](https://github.com/skywind3000/ECDICT)（MIT License）。

## 实现说明

- 监听 Sublime 的 `drag_select` 文本命令，在 `on_post_text_command` 里确认这是一次无修饰键、无选区、非双击的单击。
- 延迟 `click_delay_ms` 后再次校验光标位置与选区，避免双击/拖选误触发。
- 用正则从所在行提取完整英文单词，支持连字符、撇号、所有格；弹窗以鼠标点击位置为锚点。
- 查询顺序：原词 → 所有格/连字符拆分 → ECDICT 词形表（如 `running → run`）→ 保守后缀回退。
- SQLite 以只读查询方式使用，查询走 `word_lower` 索引。
- 兼容 Sublime Text 4 的 Python 3.3 插件宿主。

## 已知限制

- 只支持英文单词，不支持整句翻译。
- 单击会同时移动光标，这是 Sublime 的默认行为；插件不会阻止它。
- 词典不含真人发音、生词本等功能。
- 本仓库不附带演示用英文文章；请使用自己的 `.md` / `.txt` 文档测试。

## License

代码以 MIT License 发布，见 [LICENSE](LICENSE)。

离线词典数据来自 [ECDICT](https://github.com/skywind3000/ECDICT)，同样以 MIT License 发布；本仓库的 `dictionary.db` 是其衍生数据。
