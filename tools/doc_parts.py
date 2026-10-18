# -*- coding: utf-8 -*-
"""配布する文書のうち「コードから作る部分」を作り直す。

    python -X utf8 tools/doc_parts.py           docs の文書を今のコードに合わせる
    python -X utf8 tools/doc_parts.py --check   合わせる必要があるかだけ調べる
                                                （あれば 1 で終わる。書き換えない）

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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# 版の番号だけを合わせる文書と、印の節まで作り直す文書
MANUAL = DOCS / "manual.html"
TESTER = DOCS / "tester.html"

# ★speech は読み込んだ時点で無音かどうかを決めるので、import より先に置く
os.environ["OBSNAVI_SILENT"] = "1"
sys.path.insert(0, str(ROOT))

from core import filters, keymap, sources  # noqa: E402
from core.config import Config  # noqa: E402
from version import VERSION  # noqa: E402

MARK_RE = re.compile(
    r"(<!-- gen:(?P<name>[a-z_]+) -->)(?P<body>.*?)(<!-- /gen:(?P=name) -->)",
    re.S)
VERSION_SPAN_RE = re.compile(r'(<span class="version">)[^<]*(</span>)')
TITLE_RE = re.compile(r"(<title>[^<]*?)\d+\.\d+\.\d+([^<]*</title>)")


def esc(text) -> str:
    return html.escape(str(text), quote=False)


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
            m = re.search(r"\(&(\w)\)", title)
            menus.append({
                "title": re.sub(r"\(&\w\)", "", title),
                "mnemonic": m.group(1) if m else "",
                "items": _menu_items(bar.GetMenu(i)),
            })
        popups = []
        for name, lst in (("シーン一覧", frame.scene_list),
                          ("ソース一覧", frame.item_list),
                          ("音声入力一覧", frame.input_list),
                          ("フィルター一覧", frame.filter_list)):
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
    quoted = [f"「{h}」" for h in head]
    cols = ("と".join(quoted) if len(quoted) == 2
            else "、".join(quoted))
    lines = [f"<p>{esc(caption)}表は{len(rows)}行で、列は{cols}の"
             f"{len(head)}つです。</p>",
             "<table>", "<thead><tr>"]
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
        _table("OBSナビの画面にいるときだけ効くキーです。",
               ("キー", "動作"), window),
        f"<h3>{esc(keymap.SCOPE_LABEL[keymap.SCOPE_GLOBAL])}</h3>",
        _table("ゲームやほかのアプリを使っている間も効くキーです。",
               ("キー", "動作"), glob),
    ])


def _item_text(item: dict) -> str:
    text = item["label"]
    notes = []
    if item["accel"]:
        notes.append(item["accel"])
    if item["check"]:
        notes.append("チェック項目。選ぶたびにオンとオフが切り替わります")
    return f"{text}（{'。'.join(notes)}）" if notes else text


def part_menus(menus: list[dict]) -> str:
    names = "、".join(m["title"] for m in menus)
    lines = [f"<p>メニューは{len(menus)}つで、左から順に{esc(names)}です。"
             "項目の後ろのかっこの中は、その項目のキーです。</p>"]
    for m in menus:
        head = f"{m['title']}メニュー"
        if m["mnemonic"]:
            head += f"（Alt+{m['mnemonic']} で直接開けます）"
        lines.append(f"<h3>{esc(head)}</h3>")
        lines.append(f"<p>{len(m['items'])}項目です。</p>")
        lines.append("<ul>")
        lines += [f"<li>{esc(_item_text(it))}</li>" for it in m["items"]]
        lines.append("</ul>")
    return "\n".join(lines)


def part_popups(popups: list[dict]) -> str:
    lines = ["<ul>"]
    for p in popups:
        labels = "、".join(it["label"] for it in p["items"])
        lines.append(
            f"<li>{esc(p['list'])}では、{esc(labels)}"
            f"（{len(p['items'])}項目）</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def part_source_kinds() -> str:
    rows = [(k.label, k.hint) for k in sources.CREATABLE_KINDS]
    return _table("作れるソースの種類です。上から、選ぶ画面に並ぶ順です。",
                  ("種類", "何のためのものか"), rows)


def part_filter_kinds() -> str:
    rows = [(k.label, k.hint) for k in filters.AUDIO_FILTER_KINDS]
    return _table("追加できる音声フィルターの種類です。上から、選ぶ画面に"
                  "並ぶ順です。",
                  ("種類", "何のためのものか"), rows)


def _dig(cfg: Config, dotted: str):
    obj = cfg
    for part in dotted.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


def _sr_value(value) -> str:
    return "、".join(f"{s['name']}（キー {s.get('key', 'なし')}）"
                     for s in value)


# 設定ファイルの主な項目。既定値は Config() から引く（書き写さない）。
# ★項目の名前を変えたら、ここが KeyError で止まって気づける
CONFIG_DOCS = (
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


def part_config(cfg: Config) -> str:
    rows = []
    for dotted, meaning in CONFIG_DOCS:
        value = _dig(cfg, dotted)
        if dotted == "sr_sources":
            shown = _sr_value(value)
        else:
            shown = json.dumps(value, ensure_ascii=False)
        rows.append((dotted, shown, meaning))
    return _table("設定ファイルの主な項目です。項目の名前のうち、点で"
                  "区切ってあるものは「点の前の項目の中にある」という"
                  "意味です（例えば record.disk_warn_mb は record の中の "
                  "disk_warn_mb）。",
                  ("項目", "既定値", "意味"), rows)


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
    """docs の文書を合わせる。変わった（変わるべき）文書を返す。"""
    parts = build_parts()
    changed = []
    for path in (MANUAL, TESTER):
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
    changed = update_docs(check_only=check_only)
    for path in changed:
        verb = "作り直しが必要" if check_only else "作り直しました"
        print(f"{verb}: {path.relative_to(ROOT)}")
    if not changed:
        print("文書は今のコードと合っています")
    return 1 if (check_only and changed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
