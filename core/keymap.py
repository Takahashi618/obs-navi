# -*- coding: utf-8 -*-
"""キー割り当ての定義（wx非依存の純データ）。

★ここが「登録」と「表示」の唯一の出どころ。
グローバルキーの登録（ui/main_frame.py の register_global_hotkeys）、
ウィンドウ内キーの振り分け（同 on_char_hook が window_bindings を読む）、
メニューに出すキー名、ヘルプの「キー操作の一覧」が、すべてこの表を読む。
片方だけ直して食い違うのを防ぐためにまとめてある。

見えない利用者にとって、どのキーが何をするかは**読み上げでしか確かめ
られない**。一覧が実際と1つでもずれていると、押しても何も起きないキーを
探し続けることになる。だから一覧は手書きせず、登録に使う定義から作る。

★キー名の検証もここが持つ（0.14.1）。設定は手編集される前提なので、
"f12"（小文字）は正規化して通し、"Delete" や英字のような使えない値は
**すべての面（登録・メニュー・一覧）からそろって除外**したうえで、
invalid_key_warnings が起動時の読み上げ用に報告する。検証をここに
置かないと「一覧には出るが登録されないキー」ができてしまう
（0.14.0 のレビューで実際に見つかった穴）。

修飾キーの段は2つ＋窓内:
  window  ウィンドウにフォーカスがあるときだけ効く
          （素押し・Ctrl+英字・Ctrl+Shift+英字）
  global  設定 global_hotkey_modifier の段（既定 Ctrl+Alt）と、
          そこに修飾キーを1つ足した段（既定 Ctrl+Alt+Shift）
"""
from __future__ import annotations

from dataclasses import dataclass

from . import hotkeys

SCOPE_WINDOW = "window"
SCOPE_GLOBAL = "global"

# ヘルプの見出しもここから作る（文言の出どころを1つにする）
SCOPE_LABEL = {
    SCOPE_WINDOW: "OBSナビの画面にいるとき",
    SCOPE_GLOBAL: "どこにいても効くキー",
}

# 設定で指定できるキー名。RegisterHotKey に渡せる（＝ui側の
# KEY_NAME_TO_WXK にある）のはファンクションキーだけ。
# ★素の英字・数字は絶対に許可しない: 窓内ではリストの頭文字ジャンプや
#   IME と衝突し、メニューのアクセラレータに載ると文字入力まで奪う。
VALID_KEY_NAMES = frozenset(f"F{n}" for n in range(1, 13))


def normalize_key_name(raw) -> str:
    """設定のキー名を正規のつづりへ寄せる。使えない値は空文字。

    "f12" や " F5 " は救う（手編集が前提なので、大文字小文字で
    黙って効かなくなるのは酷）。"Delete" "A" のような使えない値は
    空文字にして、どの面にも出さない（警告は invalid_key_warnings が出す）。
    """
    text = str(raw or "").strip().upper()
    return text if text in VALID_KEY_NAMES else ""


@dataclass(frozen=True)
class KeyRow:
    """一覧に出すキー1つ（表示用の純データ）。"""

    keys: str          # 表示用の文字列（"F5" / "Ctrl+Alt+F5"）
    action: str        # 何が起きるか
    scope: str


# ------------------------------------------------------------
# ウィンドウ内のキー（素押しと Ctrl+英字）
# ------------------------------------------------------------
# ★この表は表示だけでなく実際の振り分けにも使われる
#   （ui/main_frame.py が window_bindings() から振り分け表を作る）。
#   キーは "F5" か "Ctrl+英字1文字" か "Ctrl+Shift+英字1文字" の形。
#   ここを変えれば動作・メニュー表示・ヘルプの3つが同時に変わる。
# ★配信・録画の開始と停止（0.18.0）は「Shift を足すと停止」で対にした。
#   S＝配信（Stream）、R＝録画（Record）。開始と停止を1つのトグルに
#   しなかったのは、押す前の状態を取り違えたまま押すと、配信を
#   始めるつもりで止めてしまうため（読み上げで状態を確かめてから押す、
#   をキーの形で強制しない）。配信は開始・停止とも確認ダイアログが出る。
WINDOW_PLAN = (
    ("stream_start", "Ctrl+S", "配信を開始"),
    ("stream_stop", "Ctrl+Shift+S", "配信を停止"),
    ("record_start", "Ctrl+R", "録画を開始"),
    ("record_stop", "Ctrl+Shift+R", "録画を停止"),
    ("state", "F5", "状態読み上げ"),
    ("levels", "F6", "レベル読み上げ"),
    ("volume_prompt", "F7", "音量を数値で入力"),
    ("game", "F3", "ゲーム切り替え"),
    ("bgm", "Ctrl+B", "BGMの再生・一時停止"),
    ("video", "Ctrl+E", "映像切り替え"),
    ("record_pause", "Ctrl+P", "録画の一時停止・再開"),
    ("help", "F1", "キー操作の一覧"),
)

# 窓内の固定キーのうち、同じキーが SR 音声トグルに設定されていたら
# そちらへ譲るもの。★F1（ヘルプ）は 0.14.0 の新顔で、それ以前は空き枠
# として SR に使えた。あとから来た機能が既存の設定を奪わないようにする。
# ui/main_frame.py の on_char_hook と、下の duplicate_bindings が
# 同じこの表を見る（勝者の説明と実際がずれないように）。
WINDOW_YIELD_TO_SR = ("help",)

# キーで呼ぶのではなく、リストの上で意味を持つ操作。
# メニューには出せないが、一覧には出さないと気づけない。
CONTEXT_KEYS = (
    ("Enter", "選んでいるリストに応じた操作"
              "（配信・録画の開始と停止、シーンの切り替え、"
              "表示の切り替え、ミュート、フィルターのオン・オフ）"),
    # ★「そのままEnterで開く」とは書かない。キーボードから開いた
    #   ポップアップメニューは、どの項目も選ばれていない状態で開く
    #   （実測。MSAAで focus=なし）。Enterだけでは何も起きずに閉じる。
    ("アプリケーションキー", "選んでいるリストでできる操作の一覧を出す"
                          "（下矢印で選んでEnter。先頭は設定）"),
    # ★アプリケーションキーの無いキーボード向け。Windows 共通の代替キー
    #   なので、書いていないと「このパソコンでは出せない」と誤解される
    ("Shift＋F10", "同じく、操作の一覧を出す"
                  "（アプリケーションキーが無いキーボード用）"),
    ("左右キー", "音声入力一覧にいるとき、音量を上げ下げする"),
    ("Shift＋左右キー", "同じく、大きく上げ下げする"),
    ("Alt＋上下キー", "ソース一覧にいるとき、選んでいるソースを"
                     "前に出す・後ろに送る（重なり順。音は変わらない）"),
    ("Escape", "設定の画面を閉じる。★OBSナビは終了しない"),
    ("Alt＋F4", "OBSナビを終了する（メニューの「終了」でも同じ）"),
    ("Alt または F10", "メニューバーを開く"),
)

# ------------------------------------------------------------
# グローバルキー（基準の修飾キーの段）
# ------------------------------------------------------------
# ★並び順は登録の優先順位でもある（同じキーに2つ割り当たったとき、
#   RegisterHotKey は先に登録した方が勝つ）。SRトグルは global_bindings が
#   levels の直後＝音量・便利キーより前に差し込む。0.13.0 までの登録順と
#   同じで、利用者が設定した SR キーが固定キーに負けないようにするため
#   （0.14.0 で末尾に回ってしまい、衝突時の勝者が入れ替わっていた）。
GLOBAL_PLAN = (
    ("state", "F5", "状態読み上げ"),
    ("levels", "F6", "レベル読み上げ"),
    ("volume_down", "F1", "音量を下げる"),
    ("volume_up", "F2", "音量を上げる"),
    ("volume_next", "F4", "音量を変える対象を次へ"),
    ("stats", "F10", "統計読み上げ"),
    ("virtual_cam", "F11", "仮想カメラの切り替え"),
    ("replay", "F12", "リプレイを保存"),
    ("game", "F3", "ゲーム切り替え"),
    ("bgm", "F7", "BGMの再生・一時停止"),
)

# SRトグルをこの action_id の直後に差し込む（上の★を参照）
_SR_INSERT_AFTER = "levels"

# ------------------------------------------------------------
# 強い修飾キーの段（基準＋1）
# ------------------------------------------------------------
# 音量の粗い刻み。キー名は固定
COARSE_PLAN = (
    ("volume_down_coarse", "F1", "音量を大きく下げる"),
    ("volume_up_coarse", "F2", "音量を大きく上げる"),
)

# 設定でキー名を変えられるもの。(action_id, 設定の在りか, 説明)
# ★空文字にすると割り当てない、という約束もここが持つ
CONFIG_COARSE_PLAN = (
    ("record_pause", ("record", "pause_hotkey"), "録画の一時停止・再開"),
    ("chapter", ("record", "chapter_hotkey"), "チャプターを付ける"),
    ("camera", ("camera", "hotkey"), "カメラの有効・無効"),
)

# 配信・録画の開始と停止（0.18.2、ゲーム中でも効くように）。
# 左が開始・右が停止で、配信が F6/F7、録画が F8/F9。
# ★基準の段（Ctrl+Alt）は F1〜F12 がすべて埋まっているのでこの段。
# ★設定で変えられるキー（上の表）より**後に**登録する（0.18.3）。
#   登録は先勝ちなので、利用者が録画一時停止などを F6〜F9 に設定して
#   いたら、そちらが今までどおり効き、こちらが負ける（重複警告が読む）。
#   あとから来た機能が既存の設定を奪わない（SR キーと同じ考え方）
# ★action_id は窓内キーと同じ（同じ動作の別の入口。ui 側で、配信は
#   2回押しで確かめる処理へ振り分ける）。説明だけは「2回続けて押す」を
#   足してある。キー一覧で分からないと、1回押して案内を聞くまで
#   気づけないため。メニューの文言は窓内キーの説明（WINDOW_PLAN）を使う
OUTPUT_COARSE_PLAN = (
    ("stream_start", "F6", "配信を開始（2回続けて押す）"),
    ("stream_stop", "F7", "配信を停止（2回続けて押す）"),
    ("record_start", "F8", "録画を開始"),
    ("record_stop", "F9", "録画を停止"),
)


def _dict_of(config, section: str) -> dict:
    value = getattr(config, section, None)
    return value if isinstance(value, dict) else {}


def config_key(config, section: str, name: str) -> str:
    """設定からキー名を引く（正規化済み）。割り当てが無ければ空文字。

    使えない値も空文字になる＝どの面にも出ない。何が捨てられたかは
    invalid_key_warnings が別に報告する。
    """
    return normalize_key_name(_dict_of(config, section).get(name, ""))


def sr_toggle_label(name: str) -> str:
    """SR音声トグルの読み上げ・表示名。

    メニュー・ヘルプ・重複警告のすべてがここを使う。文言を1か所に
    しないと、同じ操作が場面ごとに別の名前で読まれてしまう。
    """
    return f"{name}の配信オン・オフ"


def sr_entries(config):
    """sr_sources を検証つきで並べる。(source辞書, 名前, キー) を返す。

    ★sr_sources の走査はここに一本化する（登録・メニュー・一覧・
    重複チェックが同じ検証を通るように）。キーは正規化済みで、
    使えない値・未設定は空文字（項目自体は返す＝キーが無くても
    メニューには出せる）。
    """
    out = []
    for source in getattr(config, "sr_sources", None) or []:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name", "") or "")
        if not name:
            continue
        out.append((source, name, normalize_key_name(source.get("key", ""))))
    return out


def base_tokens(config) -> list[str]:
    """グローバルキーの基準の修飾トークン。無効なら空リスト。"""
    if not getattr(config, "global_hotkeys_enabled", True):
        return []
    return hotkeys.parse_modifier_tokens(
        getattr(config, "global_hotkey_modifier", ""))


def coarse_tokens(config) -> list[str] | None:
    """強い段の修飾トークン。作れなければ None。"""
    base = base_tokens(config)
    if not base:
        return None
    return hotkeys.coarse_modifier_tokens(base)


def global_bindings(config) -> list[tuple[str, list[str], str, str]]:
    """グローバルに登録するもの一覧。

    返すのは (action_id, 修飾トークン, キー名, 説明) の並び。
    ui/main_frame.py の登録も、ヘルプの一覧も、ここを読む。
    ★並び順は登録の優先順位（GLOBAL_PLAN の★を参照）。SRトグルは
    levels の直後に差し込み、固定キーとの衝突では SR が勝つ。
    """
    out: list[tuple[str, list[str], str, str]] = []
    base = base_tokens(config)
    if not base:
        return out
    sr_rows = [(f"sr:{name}", base, key, sr_toggle_label(name))
               for _source, name, key in sr_entries(config) if key]
    inserted = False
    for action_id, key, desc in GLOBAL_PLAN:
        out.append((action_id, base, key, desc))
        if action_id == _SR_INSERT_AFTER and not inserted:
            out.extend(sr_rows)
            inserted = True
    if not inserted:
        out.extend(sr_rows)
    coarse = coarse_tokens(config)
    if coarse is None:
        return out
    for action_id, key, desc in COARSE_PLAN:
        out.append((action_id, coarse, key, desc))
    for action_id, (section, name), desc in CONFIG_COARSE_PLAN:
        key = config_key(config, section, name)
        if key:
            out.append((action_id, coarse, key, desc))
    for action_id, key, desc in OUTPUT_COARSE_PLAN:
        out.append((action_id, coarse, key, desc))
    return out


def parse_window_key(keys: str) -> tuple[bool, bool, str] | None:
    """窓内キーの表記を (Ctrl併用か, Shift併用か, キー名) に分解する。

    受け付けるのは "F5" のようなファンクションキーか "Ctrl+英字1文字"
    か "Ctrl+Shift+英字1文字"。それ以外は None（振り分け表に載せられない
    ＝定義の誤り）。
    """
    text = str(keys or "").strip()
    if not text:
        return None
    if text.upper() in VALID_KEY_NAMES:
        return (False, False, text.upper())
    parts = [p.strip() for p in text.split("+")]
    letter = parts[-1]
    if len(letter) != 1 or not letter.isascii() or not letter.isalpha():
        return None
    mods = [p.lower() for p in parts[:-1]]
    if mods == ["ctrl"]:
        return (True, False, letter.upper())
    if mods == ["ctrl", "shift"]:
        return (True, True, letter.upper())
    return None


def window_bindings(config) -> list[tuple[str, bool, bool, str, str]]:
    """窓内キーの振り分け一覧。(action_id, Ctrl併用か, Shift併用か, キー名, 説明)。

    ui/main_frame.py の on_char_hook はこの表から振り分け表を作る。
    ★表示（WINDOW_PLAN）と同じ出どころなので、キーを変えれば動作も
    メニューもヘルプも一緒に変わる。分解できない表記は黙って落とさず
    ValueError にする（定義の誤りは起動時に気づくべきもの）。
    """
    out: list[tuple[str, bool, bool, str, str]] = []
    for action_id, keys, desc in WINDOW_PLAN:
        parsed = parse_window_key(keys)
        if parsed is None:
            raise ValueError(f"WINDOW_PLAN のキー表記が不正です: {keys!r}")
        ctrl, shift, key_name = parsed
        out.append((action_id, ctrl, shift, key_name, desc))
    return out


def window_key_label(config, action_id: str) -> str:
    """ウィンドウ内のキーの表示名。無ければ空文字。"""
    for aid, key, _desc in WINDOW_PLAN:
        if aid == action_id:
            return key
    return ""


def global_key_label(config, action_id: str) -> str:
    """グローバルキーの表示名（"Ctrl+Alt+F5"）。無ければ空文字。"""
    for aid, tokens, key, _desc in global_bindings(config):
        if aid == action_id:
            return hotkeys.hotkey_label(tokens, key)
    return ""


def menu_accel(config, window_id: str = "", global_id: str = "") -> str:
    """メニュー項目に出すキーの表示名を決める。

    ウィンドウ内のキーがあればそちらを優先する（そのキーの方が短く、
    メニューを開いている＝画面にいる状況で実際に使えるため）。
    無ければグローバルキーを出す。どちらも無ければ空文字。
    """
    if window_id:
        label = window_key_label(config, window_id)
        if label:
            return label
    if global_id:
        return global_key_label(config, global_id)
    return ""


def action_label(action_id: str) -> str:
    """action_id の説明文（メニュー項目の文言とキー一覧の説明は同じ）。

    ★メニューのラベルを手で打ち直さない。キー一覧（F1）の説明と
    メニューの文言がずれると、耳で探している人にとっては
    「一覧に載っている項目がメニューに無い」のと同じことになる。
    """
    for plan in (WINDOW_PLAN, GLOBAL_PLAN, COARSE_PLAN, OUTPUT_COARSE_PLAN):
        for aid, _key, desc in plan:
            if aid == action_id:
                return desc
    for aid, _where, desc in CONFIG_COARSE_PLAN:
        if aid == action_id:
            return desc
    return ""


def sr_key_label(config, name: str) -> str:
    """スクリーンリーダー音声トグルの素押しキー。無ければ空文字。"""
    for _source, entry_name, key in sr_entries(config):
        if entry_name == name:
            return key
    return ""


def help_rows(config) -> list[KeyRow]:
    """ヘルプに出すキー一覧を作る。

    ★実際に登録するものと同じ定義から作るので、一覧と実際がずれない。
    並びは「画面にいるとき」→「どこでも効く」の順。探しやすさを優先し、
    段ごとにまとめる。
    """
    rows: list[KeyRow] = []
    for _aid, key, desc in WINDOW_PLAN:
        rows.append(KeyRow(key, desc, SCOPE_WINDOW))
    # スクリーンリーダー音声（素押し）
    for _source, name, key in sr_entries(config):
        if key:
            rows.append(KeyRow(key, sr_toggle_label(name), SCOPE_WINDOW))
    for key, desc in CONTEXT_KEYS:
        rows.append(KeyRow(key, desc, SCOPE_WINDOW))
    for _aid, tokens, key, desc in global_bindings(config):
        rows.append(KeyRow(
            hotkeys.hotkey_label(tokens, key), desc, SCOPE_GLOBAL))
    return rows


def help_text(config) -> str:
    """ヘルプの本文（読み上げで1行ずつ辿れる形）。

    段ごとに見出しを挟む。見出しが無いと、どのキーがどこで効くのかが
    分からなくなる（素押しのF5とCtrl+Alt+F5は別物）。
    """
    rows = help_rows(config)
    lines: list[str] = []
    window_rows = [r for r in rows if r.scope == SCOPE_WINDOW]
    global_rows = [r for r in rows if r.scope != SCOPE_WINDOW]
    if window_rows:
        lines.append(f"【{SCOPE_LABEL[SCOPE_WINDOW]}】")
        lines.extend(f"{r.keys}  {r.action}" for r in window_rows)
    if global_rows:
        if lines:
            lines.append("")
        lines.append(f"【{SCOPE_LABEL[SCOPE_GLOBAL]}】")
        lines.extend(f"{r.keys}  {r.action}" for r in global_rows)
    else:
        lines.append("")
        lines.append("グローバルキーは無効になっています。")
    return "\n".join(lines)


def duplicate_global_labels(config) -> set[str]:
    """グローバル段で2つ以上に割り当てられたキーの表示名の集合。

    登録失敗の警告から「自分の設定の重複」を除いて、本当に他のアプリと
    競合したものだけを他アプリのせいにするために使う。
    """
    seen: set[str] = set()
    dupes: set[str] = set()
    for _aid, tokens, key, _desc in global_bindings(config):
        label = hotkeys.hotkey_label(tokens, key)
        if label in seen:
            dupes.add(label)
        else:
            seen.add(label)
    return dupes


def _dupe_text(key: str, winner: str, loser: str) -> str:
    """重複の説明。★どちらが効くかを言い切る。

    「後の方は効きません」のような一般則で言ってはいけない。段ごとに
    勝つ側が違う（グローバルは先勝ち、窓内の固定キーは固定側が勝ち、
    ただし F1 は SR に譲り、SR 同士は先勝ち）ので、規則で書くと
    半分の場面で**実際と逆のことを読み上げる**（レビューで判明）。
    """
    return f"{key}（{winner} が効きます。{loser} は効きません）"


def duplicate_bindings(config) -> list[str]:
    """同じキーに2つ以上割り当てていないか、全部の段で調べる。

    ★重なると片方が黙って効かなくなる。どちらが効くかは段によって
    違うので、必ず実際に合わせて説明する（_dupe_text を参照）。
    設定でキー名を変えられるのは SRのキーと録画・カメラのキーなので、
    利用者がぶつけたときに起動時の読み上げで気づけるようにする。
    ★グローバルキーが無効でも窓内の段は調べる（0.14.0 では無効時に
    チェック全体が空振りしていた）。
    """
    dupes: list[str] = []
    # グローバル段（RegisterHotKey は先勝ち。表示名で比較するので段は
    # 自然に分かれる）
    seen: dict[str, str] = {}
    for _aid, tokens, key, desc in global_bindings(config):
        label = hotkeys.hotkey_label(tokens, key)
        if label in seen:
            dupes.append(_dupe_text(label, seen[label], desc))
        else:
            seen[label] = desc
    # 窓内の段（素押し・Ctrl+英字）。固定キーと SR キー、SR 同士。
    fixed: dict[str, tuple[str, str]] = {
        key: (aid, desc) for aid, key, desc in WINDOW_PLAN}
    sr_seen: dict[str, str] = {}
    for _source, name, key in sr_entries(config):
        if not key:
            continue
        desc = sr_toggle_label(name)
        if key in sr_seen:
            # SR 同士は振り分け表への登録が先勝ち
            dupes.append(_dupe_text(key, sr_seen[key], desc))
            continue
        sr_seen[key] = desc
        if key in fixed:
            aid, fixed_desc = fixed[key]
            if aid in WINDOW_YIELD_TO_SR:
                dupes.append(_dupe_text(key, desc, fixed_desc))
            else:
                dupes.append(_dupe_text(key, fixed_desc, desc))
    return dupes


def invalid_key_warnings(config) -> list[str]:
    """設定に書かれた使えないキー名を、場所つきで報告する。

    正規化（normalize_key_name）で救えなかった値は、登録・メニュー・
    一覧のどこにも出ない。黙って消すと「設定したのに効かない」で
    終わってしまうので、何がなぜ捨てられたかを起動時に読み上げる。
    """
    out: list[str] = []
    for _aid, (section, name), desc in CONFIG_COARSE_PLAN:
        raw = _dict_of(config, section).get(name, "")
        if raw and not normalize_key_name(raw):
            out.append(
                f"{desc}のキー {raw} は使えません。F1からF12を指定してください")
    # ★走査は sr_entries に一本化する（この関数だけ自前で回すと、
    #   有効性の判定が増えたときに登録・メニュー・一覧と食い違い、
    #   「一覧には出るのに効かない」を見つけられなくなる）
    for source, name, key in sr_entries(config):
        raw = source.get("key", "")
        if raw and not key:
            out.append(
                f"{name}のキー {raw} は使えません。F1からF12を指定してください")
    return out
