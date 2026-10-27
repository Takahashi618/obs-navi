# -*- coding: utf-8 -*-
"""配布する文書のうち「コードから作る部分」を作り直す。

    python -X utf8 tools/doc_parts.py           docs の文書を今のコードに合わせる
    python -X utf8 tools/doc_parts.py --check   合わせる必要があるかだけ調べる
                                                （あれば 1 で終わる。書き換えない）

日本語の文書（manual.html・tester.html）と英語の文書（manual.en.html・
tester.en.html）の両方を合わせる。★画面の言語は起動したときに1回だけ
決まる（core/i18n.py）ので、英語の分は別のプロセスで、英語の画面から作る
（--lang en。update_docs が自分で呼ぶ）。

キー・メニュー・作れるソースの種類・フィルターの種類・設定の既定値は、
手で書き写すと必ずずれる（キーの一覧だけが 0.13.0 のまま
取り残されたことがある）。そこで、実際の
登録に使っている定義（core/keymap.py など）と、実際に組み立てた
メニューバーから作り、文書の印の間に差し込む。

印の書き方（HTML のコメント。読み上げにも txt にも出ない）:

    <!-- gen:keys -->
    …ここが作り直される…
    <!-- /gen:keys -->

版の番号は <span class="version">…</span> と <title> の中の番号を
version.py に合わせる。

★メニューを読むために本物の MainFrame を作る。OBS には接続させず
（接続を断る）、グローバルキーも登録させず（システム全体のキーを一瞬でも
奪わないため）、設定ファイルにも書かせない（tests/smoke_ui.py と同じ
守り方）。既定の設定で作るので、テスターが最初に見るのと同じメニューになる。
"""
from __future__ import annotations

import contextlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# 言語ごとの文書
DOC_FILES = {
    "ja": (DOCS / "manual.html", DOCS / "tester.html"),
    "en": (DOCS / "manual.en.html", DOCS / "tester.en.html"),
}

# ★speech は読み込んだ時点で無音かどうかを決めるので、import より先に置く
os.environ["OBSNAVI_SILENT"] = "1"
# ★言語も import より先に決める（メニューやキーの表は import のときに
#   作られる）。--lang が無ければ日本語（build_release.py から import した
#   ときもこちら）
LANG = (sys.argv[sys.argv.index("--lang") + 1]
        if "--lang" in sys.argv[:-1] else "ja")
os.environ["OBSNAVI_LANG"] = LANG
sys.path.insert(0, str(ROOT))

from core import filters, keymap, sources  # noqa: E402
from core.i18n import tr  # noqa: E402
from core.config import Config  # noqa: E402
from version import VERSION  # noqa: E402

MARK_RE = re.compile(
    r"(<!-- gen:(?P<name>[a-z_]+) -->)(?P<body>.*?)(<!-- /gen:(?P=name) -->)",
    re.S)
VERSION_SPAN_RE = re.compile(r'(<span class="version">)[^<]*(</span>)')
TITLE_RE = re.compile(r"(<title>[^<]*?)\d+\.\d+\.\d+([^<]*</title>)")


# 英語の画面にもわざと日本語で出しているもの。英語の文書では lang="ja" を
# 付けて、読み上げが日本語の声に切り替えられるようにする
JA_IN_EN = ("表示の言語",)


def esc(text) -> str:
    out = html.escape(str(text), quote=False)
    if LANG == "en":
        for word in JA_IN_EN:
            out = out.replace(word, f'<span lang="ja">{word}</span>')
    return out


def sandbox_config() -> Config:
    """設定ファイルへ絶対に書かない、既定値の Config。"""
    cfg = Config()
    cfg._save_blocked = True
    return cfg


# ------------------------------------------------------------
# 本物のメニューを読む（wx が要る部分）
# ------------------------------------------------------------
@contextlib.contextmanager
def real_frame():
    """OBS に繋がず、キーも登録しない MainFrame を作って渡す。"""
    import wx

    import ui.main_frame as mf
    from core.connection import ObsConnectError

    def refuse(self, callbacks=None):
        raise ObsConnectError("文書を作るときは OBS に接続しない")

    saved = (mf.ObsConnection.connect, mf.MainFrame.register_global_hotkeys)
    mf.ObsConnection.connect = refuse
    mf.MainFrame.register_global_hotkeys = lambda self: None
    app = wx.App()
    frame = mf.MainFrame(sandbox_config())
    try:
        yield frame
    finally:
        frame.Destroy()
        app.Destroy()
        mf.ObsConnection.connect, mf.MainFrame.register_global_hotkeys = saved


def _menu_items(menu) -> list[dict]:
    out = []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        text, _tab, accel = item.GetItemLabel().partition("\t")
        out.append({
            "label": text.replace("&", ""),
            "accel": accel.strip(),
            "check": item.IsCheckable(),
        })
    return out


def read_menus() -> tuple[list[dict], list[dict]]:
    """(メニューバー, アプリケーションキーのメニュー) を読む。"""
    with real_frame() as frame:
        bar = frame.GetMenuBar()
        menus = []
        for i in range(bar.GetMenuCount()):
            title = bar.GetMenuLabel(i)
            # 日本語は「配信・録画(&S)」、英語は「&Stream and Record」や
            # 「Camera (&K)」の形
            m = re.search(r"&(\w)", title)
            menus.append({
                "title": re.sub(r"\s*\(&\w\)", "", title).replace("&", ""),
                "mnemonic": m.group(1).upper() if m else "",
                "items": _menu_items(bar.GetMenu(i)),
            })
        popups = []
        for name, lst in ((tr("シーン一覧", "Scene list"), frame.scene_list),
                          (tr("ソース一覧", "Source list"), frame.item_list),
                          (tr("音声入力一覧", "Audio input list"),
                           frame.input_list),
                          (tr("フィルター一覧", "Filter list"),
                           frame.filter_list)):
            menu = frame.build_list_menu(lst)
            popups.append({"list": name, "items": _menu_items(menu)})
            menu.Destroy()
    return menus, popups


# ------------------------------------------------------------
# 節を作る
# ------------------------------------------------------------
def _table(caption: str, head: tuple, rows: list[tuple]) -> str:
    """表の前に「何の表か・何行・どの列か」を段落で言う。

    ★caption は使わない。txt にすると表の行のあとに出てしまい、
    何の表かを知らないまま行を聞かされる。
    """
    if LANG == "en":
        quoted = [f"\"{h}\"" for h in head]
        cols = (" and ".join(quoted) if len(quoted) == 2
                else ", ".join(quoted[:-1]) + ", and " + quoted[-1])
        intro = (f"<p>{esc(caption)} The table has {len(rows)} rows and "
                 f"{len(head)} columns: {cols}.</p>")
    else:
        quoted = [f"「{h}」" for h in head]
        cols = ("と".join(quoted) if len(quoted) == 2
                else "、".join(quoted))
        intro = (f"<p>{esc(caption)}表は{len(rows)}行で、列は{cols}の"
                 f"{len(head)}つです。</p>")
    lines = [intro, "<table>", "<thead><tr>"]
    lines += [f'<th scope="col">{esc(h)}</th>' for h in head]
    lines += ["</tr></thead>", "<tbody>"]
    for row in rows:
        lines.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row)
                     + "</tr>")
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


def part_keys(cfg: Config) -> str:
    rows = keymap.help_rows(cfg)
    window = [(r.keys, r.action) for r in rows
              if r.scope == keymap.SCOPE_WINDOW]
    glob = [(r.keys, r.action) for r in rows
            if r.scope != keymap.SCOPE_WINDOW]
    return "\n".join([
        f"<h3>{esc(keymap.SCOPE_LABEL[keymap.SCOPE_WINDOW])}</h3>",
        _table(tr("OBSナビの画面にいるときだけ効くキーです。",
                  "These keys work only while you are in the OBS Navi "
                  "window."),
               (tr("キー", "Key"), tr("動作", "Action")), window),
        f"<h3>{esc(keymap.SCOPE_LABEL[keymap.SCOPE_GLOBAL])}</h3>",
        _table(tr("ゲームやほかのアプリを使っている間も効くキーです。",
                  "These keys work even while you are using a game or "
                  "another app."),
               (tr("キー", "Key"), tr("動作", "Action")), glob),
    ])


def _item_text(item: dict) -> str:
    text = item["label"]
    notes = []
    if item["accel"]:
        notes.append(item["accel"])
    if item["check"]:
        notes.append(tr("チェック項目。選ぶたびにオンとオフが切り替わります",
                        "a check item that turns on or off each time you "
                        "choose it"))
    if LANG == "en":
        return f"{text} ({'; '.join(notes)})" if notes else text
    return f"{text}（{'。'.join(notes)}）" if notes else text


def part_menus(menus: list[dict]) -> str:
    if LANG == "en":
        names = ", ".join(m["title"] for m in menus)
        lines = [f"<p>There are {len(menus)} menus. From left to right: "
                 f"{esc(names)}. The text in parentheses after an item is "
                 "its key.</p>"]
    else:
        names = "、".join(m["title"] for m in menus)
        lines = [f"<p>メニューは{len(menus)}つで、左から順に{esc(names)}です。"
                 "項目の後ろのかっこの中は、その項目のキーです。</p>"]
    for m in menus:
        if LANG == "en":
            head = f"{m['title']} menu"
            if m["mnemonic"]:
                head += f" (Alt+{m['mnemonic']} opens it directly)"
            count = f"{len(m['items'])} items."
        else:
            head = f"{m['title']}メニュー"
            if m["mnemonic"]:
                head += f"（Alt+{m['mnemonic']} で直接開けます）"
            count = f"{len(m['items'])}項目です。"
        lines.append(f"<h3>{esc(head)}</h3>")
        lines.append(f"<p>{count}</p>")
        lines.append("<ul>")
        lines += [f"<li>{esc(_item_text(it))}</li>" for it in m["items"]]
        lines.append("</ul>")
    return "\n".join(lines)


def part_popups(popups: list[dict]) -> str:
    lines = ["<ul>"]
    for p in popups:
        if LANG == "en":
            labels = ", ".join(it["label"] for it in p["items"])
            lines.append(
                f"<li>In the {esc(p['list'].lower())}: {esc(labels)} "
                f"({len(p['items'])} items)</li>")
            continue
        labels = "、".join(it["label"] for it in p["items"])
        lines.append(
            f"<li>{esc(p['list'])}では、{esc(labels)}"
            f"（{len(p['items'])}項目）</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def part_source_kinds() -> str:
    rows = [(k.label, k.hint) for k in sources.CREATABLE_KINDS]
    return _table(tr("作れるソースの種類です。上から、選ぶ画面に並ぶ順です。",
                     "The kinds of sources you can create, in the order "
                     "they appear in the list."),
                  (tr("種類", "Kind"), tr("何のためのものか", "What it is for")),
                  rows)


def part_filter_kinds() -> str:
    rows = [(k.label, k.hint) for k in filters.AUDIO_FILTER_KINDS]
    return _table(tr("追加できる音声フィルターの種類です。上から、選ぶ画面に"
                     "並ぶ順です。",
                     "The kinds of audio filters you can add, in the order "
                     "they appear in the list."),
                  (tr("種類", "Kind"), tr("何のためのものか", "What it is for")),
                  rows)


def _dig(cfg: Config, dotted: str):
    obj = cfg
    for part in dotted.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


def _sr_value(value) -> str:
    if LANG == "en":
        return ", ".join(f"{s['name']} (key {s.get('key', 'none')})"
                         for s in value)
    return "、".join(f"{s['name']}（キー {s.get('key', 'なし')}）"
                     for s in value)


# 設定ファイルの主な項目。既定値は Config() から引く（書き写さない）。
# ★項目の名前を変えたら、ここが KeyError で止まって気づける
# ★意味は (日本語, 英語) で並べる（CONFIG_DOCS_EN）。英語の文書を作る
#   プロセスでは英語のほうを使う
CONFIG_DOCS = (
    ("language", "表示と読み上げの言語。\"auto\" は PC の表示言語に合わせ"
     "（日本語なら日本語、それ以外は英語）、\"ja\" は日本語、\"en\" は"
     "英語。「ツール」メニューの「表示の言語」でも選べます。次に起動した"
     "ときから効きます"),
    ("auto_password", "true なら、接続のポートとパスワードを OBS の設定"
     "ファイルから読みます。ふつうは変えません"),
    ("host", "OBS が動いているパソコン。同じパソコンなら変えません"),
    ("global_hotkeys_enabled", "どこにいても効くキーを使うか。false にすると"
     "登録しません"),
    ("global_hotkey_modifier", "どこにいても効くキーの修飾キー。Ctrl・Alt・"
     "Shift・Win を + でつないで書きます。強い段はこれに1つ足したもの"
     "（Alt が入っていなければ Alt、入っていれば Shift）になります"),
    ("sr_sources", "スクリーンリーダーの声を配信に乗せる入力。名前・方式・"
     "キー（F1 から F12）を持ちます"),
    ("silence_seconds", "配信中・録画中に、この秒数だけ無音が続いたら"
     "知らせます"),
    ("silence_threshold_db", "これより小さい音を無音とみなします（デシベル）"),
    ("clip_threshold_db", "これ以上の大きさになったら音割れとして知らせます"
     "（デシベル）"),
    ("monitor_enabled", "無音と音割れの警告を出すか"),
    ("level_hold_seconds", "F6 で読むレベルは、直近この秒数の最大の値です。"
     "0 にすると押した瞬間の値を読みます"),
    ("volume_step_db", "左右キーで音量を動かす量（デシベル）"),
    ("volume_coarse_step_db", "Shift＋左右キーで音量を動かす量（デシベル）"),
    ("game_switch.video_source", "ゲーム切り替えで使う映像のソースの名前。"
     "見つからなければ、ゲームキャプチャのソースから選び直せます"),
    ("game_switch.audio_sources", "ゲーム切り替えで一緒に切り替える、"
     "「アプリの音」のソースの名前"),
    ("bgm.source_name", "BGM に使うメディアソースの名前"),
    ("record.pause_reminder_seconds", "録画を一時停止したままのとき、"
     "この秒数ごとに知らせます。0 にすると知らせません"),
    ("record.disk_warn_mb", "録画中、空き容量がこれを下回ったら知らせます"
     "（メガバイト）。0 で知らせません"),
    ("record.disk_critical_mb", "強い警告を出す空き容量（メガバイト）"),
    ("record.announce_file_name", "録画を止めたときとリプレイを保存したときに、"
     "ファイル名を読むか"),
    ("record.pause_hotkey", "録画の一時停止・再開の、どこにいても効くキー"
     "（強い段）。空にすると割り当てません"),
    ("record.chapter_hotkey", "チャプターの、どこにいても効くキー（強い段）"),
    ("camera.hotkey", "カメラの有効・無効の、どこにいても効くキー（強い段）"),
    ("camera.confirm_before_toggle", "カメラを切り替える前に確認を出すか"),
)

CONFIG_DOCS_EN = {
    "language": "The display and speech language. \"auto\" follows the "
    "Windows display language (Japanese if it is Japanese, otherwise "
    "English), \"ja\" is Japanese, and \"en\" is English. You can also "
    "choose it with Language in the Tools menu. It takes effect the next "
    "time you start OBS Navi",
    "auto_password": "If true, the port and password for the connection are "
    "read from the OBS settings file. Usually left as is",
    "host": "The computer where OBS is running. Leave it as is if it is the "
    "same computer",
    "global_hotkeys_enabled": "Whether to use the keys that work anywhere. "
    "If false, they are not registered",
    "global_hotkey_modifier": "The modifier keys for the keys that work "
    "anywhere. Join Ctrl, Alt, Shift, and Win with +. The stronger level adds "
    "one more key to this (Alt if Alt is not included, otherwise Shift)",
    "sr_sources": "The inputs that send screen reader voices to the stream. "
    "Each has a name, a method, and a key (F1 to F12)",
    "silence_seconds": "While streaming or recording, you are notified if "
    "silence continues for this many seconds",
    "silence_threshold_db": "Sound quieter than this is treated as silence "
    "(decibels)",
    "clip_threshold_db": "You are notified of clipping when the sound reaches "
    "this level (decibels)",
    "monitor_enabled": "Whether to warn about silence and clipping",
    "level_hold_seconds": "The level read with F6 is the maximum over this "
    "many recent seconds. With 0, the value at the moment you press is read",
    "volume_step_db": "How much Left and Right Arrow change the volume "
    "(decibels)",
    "volume_coarse_step_db": "How much Shift+Left and Right Arrow change the "
    "volume (decibels)",
    "game_switch.video_source": "The name of the video source used by Game "
    "switch. If it is not found, you can choose again from the game capture "
    "sources",
    "game_switch.audio_sources": "The names of the Application Audio sources "
    "switched together with Game switch",
    "bgm.source_name": "The name of the media source used for BGM",
    "record.pause_reminder_seconds": "While recording stays paused, you are "
    "reminded every this many seconds. 0 turns the reminder off",
    "record.disk_warn_mb": "While recording, you are warned when free space "
    "falls below this (megabytes). 0 turns it off",
    "record.disk_critical_mb": "Free space for the stronger warning "
    "(megabytes)",
    "record.announce_file_name": "Whether to read the file name when you stop "
    "recording or save a replay",
    "record.pause_hotkey": "The key that works anywhere for pausing and "
    "resuming recording (stronger level). Empty means no key",
    "record.chapter_hotkey": "The key that works anywhere for adding a "
    "chapter (stronger level)",
    "camera.hotkey": "The key that works anywhere for enabling or disabling "
    "the camera (stronger level)",
    "camera.confirm_before_toggle": "Whether to ask before switching the "
    "camera",
}


def part_config(cfg: Config) -> str:
    rows = []
    for dotted, meaning in CONFIG_DOCS:
        if LANG == "en":
            meaning = CONFIG_DOCS_EN[dotted]
        value = _dig(cfg, dotted)
        if dotted == "sr_sources":
            shown = _sr_value(value)
        else:
            shown = json.dumps(value, ensure_ascii=False)
        rows.append((dotted, shown, meaning))
    return _table(tr("設定ファイルの主な項目です。項目の名前のうち、点で"
                     "区切ってあるものは「点の前の項目の中にある」という"
                     "意味です（例えば record.disk_warn_mb は record の中の "
                     "disk_warn_mb）。",
                     "The main items in the settings file. A name with a dot "
                     "means the item is inside the item before the dot "
                     "(for example, record.disk_warn_mb is disk_warn_mb "
                     "inside record)."),
                  (tr("項目", "Item"), tr("既定値", "Default"),
                   tr("意味", "Meaning")), rows)


def build_parts(with_menus: bool = True) -> dict[str, str]:
    cfg = sandbox_config()
    parts = {
        "keys": part_keys(cfg),
        "source_kinds": part_source_kinds(),
        "filter_kinds": part_filter_kinds(),
        "config": part_config(cfg),
    }
    if with_menus:
        menus, popups = read_menus()
        parts["menus"] = part_menus(menus)
        parts["popups"] = part_popups(popups)
    return parts


# ------------------------------------------------------------
# 文書へ差し込む
# ------------------------------------------------------------
def apply_parts(text: str, parts: dict[str, str]) -> str:
    """印の間を作り直し、版の番号を合わせた文書を返す。

    ★文書にある印が作れない名前なら止める（綴り違いの印は、黙って
    古い中身のまま残るので）。作った節のうち文書に印が無いものは
    差し込まないだけ（文書ごとに使う節が違う）。
    """
    unknown = [m.group("name") for m in MARK_RE.finditer(text)
               if m.group("name") not in parts]
    if unknown:
        raise ValueError(f"作り方を知らない印があります: {unknown}")

    def repl(m: re.Match) -> str:
        return f"{m.group(1)}\n{parts[m.group('name')]}\n{m.group(4)}"

    text = MARK_RE.sub(repl, text)
    text = VERSION_SPAN_RE.sub(rf"\g<1>{VERSION}\g<2>", text)
    text = TITLE_RE.sub(rf"\g<1>{VERSION}\g<2>", text)
    return text


def update_docs(check_only: bool = False) -> list[Path]:
    """docs の文書を合わせる。変わった（変わるべき）文書を返す。

    この言語（LANG）の文書を合わせたあと、日本語のプロセスなら英語の
    文書を別のプロセスで合わせる。
    """
    changed = _update_own_docs(check_only)
    if LANG == "ja":
        args = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                "--lang", "en", "--list"]
        if check_only:
            args.append("--check")
        result = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8")
        if result.returncode not in (0, 1):
            raise RuntimeError("英語の文書を作れませんでした: "
                               + (result.stderr or result.stdout)[-800:])
        changed += [Path(line[len("CHANGED "):])
                    for line in result.stdout.splitlines()
                    if line.startswith("CHANGED ")]
    return changed


def _update_own_docs(check_only: bool) -> list[Path]:
    """この言語（LANG）の文書だけを合わせる。"""
    parts = build_parts()
    changed = []
    for path in DOC_FILES[LANG]:
        raw = path.read_bytes()
        # ★元の改行を保つ（git は autocrlf で作業ツリーが CRLF。LF で
        #   書き戻すと、中身が同じでも変更ありに見える）
        newline = "\r\n" if b"\r\n" in raw else "\n"
        before = raw.decode("utf-8").replace("\r\n", "\n")
        after = apply_parts(before, parts)
        if after != before:
            changed.append(path)
            if not check_only:
                path.write_text(after, encoding="utf-8", newline=newline)
    return changed


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    if "--list" in argv:
        # update_docs から呼ばれたとき。この言語の分だけ合わせ、
        # 変わった文書を1行ずつ返す
        for path in _update_own_docs(check_only):
            print(f"CHANGED {path}")
        return 0
    changed = update_docs(check_only=check_only)
    for path in changed:
        verb = "作り直しが必要" if check_only else "作り直しました"
        print(f"{verb}: {path.relative_to(ROOT)}")
    if not changed:
        print("文書は今のコードと合っています")
    return 1 if (check_only and changed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
