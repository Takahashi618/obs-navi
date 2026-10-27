# -*- coding: utf-8 -*-
"""ソース設定（プロパティ）の表と、その純ロジック。

obs-websocket にはプロパティの「スキーマ」を返すAPIが無い。
（GetInputPropertiesListPropertyItems は「名前が分かっている1項目」の
選択肢しか返さない）。そのため、扱う項目はここで種別ごとに手で定義する。

方針:
- 実測またはOBSのソースで確認できたキーだけを載せる。推測でキーを書くと
  overlay=True で「誰も読まない設定キー」を書き込む事故になる。
- 表に無い種別は UI 側で「このアプリでは変えられません」に縮退し、
  OBS本体のプロパティ画面へ逃がす（機能が黙って消える状態を作らない）。
このモジュールは wx にも obsws にも依存しない（テストしやすさのため）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .i18n import tr

# メディア操作（TriggerMediaInputAction に渡す完全な識別子）。
# 誤った文字列は 400 InvalidRequestField になるため定数化しておく。
MEDIA_PLAY = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
MEDIA_PAUSE = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
MEDIA_STOP = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
MEDIA_RESTART = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"

# メディア操作を持つ種別（再生・一時停止などの行を足す）
MEDIA_KINDS = {"ffmpeg_source"}

# 音声モニタリング（自分の耳に返すか）。
# OBSの既定は NONE＝「配信・録画には乗るが、自分には聞こえない」。
# BGMを入れたのに聞こえない、の原因はたいていこれ。
MONITOR_NONE = "OBS_MONITORING_TYPE_NONE"
MONITOR_ONLY = "OBS_MONITORING_TYPE_MONITOR_ONLY"
MONITOR_AND_OUTPUT = "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT"
MONITOR_CHOICES = [MONITOR_NONE, MONITOR_ONLY, MONITOR_AND_OUTPUT]
# 内部名ではなく「何が起きるか」で読ませる（用語だけでは判断できないため）
MONITOR_JP = {
    MONITOR_NONE: tr("オフ、配信に乗るが自分には聞こえない", "Off, sent to the stream but you do not hear it"),
    MONITOR_ONLY: tr("自分だけ聞く、配信には乗らない", "Monitor only, not sent to the stream"),
    MONITOR_AND_OUTPUT: tr("自分も聞く、配信にも乗る", "Monitor and output, you hear it and it is sent to the stream"),
}
# 設定値ではなく専用APIで扱うので、キーは他と衝突しない名前にしておく
MONITOR_KEY = "__monitor__"

GAME_CAPTURE_KIND = "game_capture"
APP_AUDIO_KIND = "wasapi_process_output_capture"
MEDIA_KIND = "ffmpeg_source"
CAMERA_KIND = "dshow_input"
# ★バージョン付きの識別子に注意。実機（OBS 32.2.2）の GetInputKindList で
#   確認した値。text は v3、color と slideshow は v2/v3 が現役。
WINDOW_CAPTURE_KIND = "window_capture"
MONITOR_CAPTURE_KIND = "monitor_capture"
IMAGE_KIND = "image_source"
TEXT_KIND = "text_gdiplus_v3"
BROWSER_KIND = "browser_source"
COLOR_KIND = "color_source_v3"

# カラーソースの色。OBSは 0xAABBGGRR の順で持つ（RGBではない）。
# 実測で 4278190335 = 0xFF0000FF が赤になることを確認している。
# 色そのものは読み上げても分からないので、名前で選べるようにする。
COLOR_CHOICES = (
    (4278190080, tr("黒", "Black")),
    (4294967295, tr("白", "White")),
    (4278190335, tr("赤", "Red")),
    (4278255360, tr("緑", "Green")),
    (4294901760, tr("青", "Blue")),
    (4278255615, tr("黄", "Yellow")),
    (4278222848, tr("クロマキー用の緑", "Chroma key green")),
)

# 一致方式(priority)の値。★並び順と値が一致しないので必ず値で扱う
#   タイトル一致=1 / 種類(クラス)一致=0 / 実行ファイル一致=2
PRIORITY_TITLE = 1
PRIORITY_CLASS = 0
PRIORITY_EXE = 2

# UWP系のウィンドウクラス。これらは OBS 側の照合が常にタイトル一致を要求する
# ため、実行ファイル優先(priority=2)にすると逆に条件が狭まる。よって
# priority を送らない（OBSの既定に任せる）。
UWP_CLASSES = {
    "Windows.UI.Core.CoreWindow",
    "WinUIDesktopWin32WindowClass",
    "ApplicationFrameWindow",
}


@dataclass(frozen=True)
class PropSpec:
    """編集できる設定項目1つの定義。"""

    key: str            # OBSのsettingsキー
    label: str          # 日本語ラベル（そのまま読み上げ名になる）
    # "list"（OBSから選択肢を引く） | "bool" | "int" | "file" |
    # "text"（自由入力） | "choice"（このファイルの表から選ぶ）
    type: str
    # 選択肢の itemEnabled=false を「今は起動していません」と読むか
    running_flag: bool = False
    min_value: int = 0
    max_value: int = 0
    unit: str = ""
    # type="file" のときに開くファイル選択の種類（"audio" | "image"）
    file_kind: str = "audio"
    # type="choice" のときの選択肢。(OBSに渡す値, 読み上げ用の日本語)
    # ★ラベルに読点を入れないこと（一覧が「ラベル、値」の形なので、
    #   値の読点が項目の区切りに聞こえる）
    choices: tuple = ()


PROP_TABLE: dict[str, list[PropSpec]] = {
    GAME_CAPTURE_KIND: [
        # 使用頻度順。ゲームを変えるとき触るのは window なので先頭に置く。
        PropSpec("window", tr("対象ウィンドウ", "Window"), "list", running_flag=True),
        PropSpec("capture_mode", tr("取り込み方法", "Capture method"), "list"),
        PropSpec("priority", tr("一致の優先", "Window match priority"), "list"),
        PropSpec("capture_cursor", tr("マウスカーソルを含める", "Capture cursor"), "bool"),
        PropSpec("capture_audio", tr("ゲーム音も取り込む", "Capture audio"), "bool"),
    ],
    APP_AUDIO_KIND: [
        PropSpec("window", tr("対象アプリ", "Application"), "list", running_flag=True),
        PropSpec("priority", tr("一致の優先", "Window match priority"), "list"),
    ],
    "wasapi_input_capture": [
        PropSpec("device_id", tr("録音デバイス", "Recording device"), "list", running_flag=True),
        PropSpec("use_device_timing", tr("デバイスのタイミングを使う", "Use device timestamps"), "bool"),
    ],
    "wasapi_output_capture": [
        PropSpec("device_id", tr("再生デバイス", "Playback device"), "list", running_flag=True),
        PropSpec("use_device_timing", tr("デバイスのタイミングを使う", "Use device timestamps"), "bool"),
    ],
    # 映像キャプチャデバイス（ウェブカメラ・キャプチャーボード）。
    # ★有効・無効(active)はここに載せない。設定として書いても
    #   デバイスは止まらないため（実測。core/camera.py の冒頭を参照）。
    #   切り替えは専用のボタン操作でしか行わない＝誤って「設定で止めた
    #   つもり」を作らないよう、構造的に選べないようにしてある。
    CAMERA_KIND: [
        PropSpec("video_device_id", tr("カメラ", "Camera"), "list", running_flag=True),
        PropSpec("buffering", tr("バッファリング", "Buffering"), "bool"),
        PropSpec("deactivate_when_not_showing", tr("映していないときは止める", "Deactivate when not showing"),
                 "bool"),
    ],
    MEDIA_KIND: [
        PropSpec("local_file", tr("音楽ファイル", "Music file"), "file"),
        PropSpec("looping", tr("繰り返し再生", "Loop"), "bool"),
        PropSpec("restart_on_activate", tr("シーン切り替えで最初から", "Restart playback when source becomes active"), "bool"),
        PropSpec("clear_on_media_end", tr("再生が終わったら消す", "Hide source when playback ends"), "bool"),
        PropSpec("speed_percent", tr("再生速度", "Speed"), "int",
                 min_value=1, max_value=200, unit=tr("パーセント", " percent")),
    ],
    # ここから下は 0.12.0 でソースを作れるようにしたときに足した種別。
    # ★キーはすべて実機で「投げて読み戻せる」ことを確認済み。
    #   既定設定に現れないキー（image_source の file、text の text）が
    #   あるので、既定を見るだけでは足りない。
    WINDOW_CAPTURE_KIND: [
        PropSpec("window", tr("対象ウィンドウ", "Window"), "list", running_flag=True),
        PropSpec("cursor", tr("マウスカーソルを含める", "Capture cursor"), "bool"),
        PropSpec("client_area", tr("枠を除いて取り込む", "Client area only"), "bool"),
    ],
    MONITOR_CAPTURE_KIND: [
        PropSpec("monitor_id", tr("モニター", "Display"), "list", running_flag=True),
        PropSpec("capture_cursor", tr("マウスカーソルを含める", "Capture cursor"), "bool"),
    ],
    IMAGE_KIND: [
        PropSpec("file", tr("画像ファイル", "Image file"), "file", file_kind="image"),
        PropSpec("unload", tr("映していないときは読み込まない", "Unload image when not showing"), "bool"),
    ],
    TEXT_KIND: [
        PropSpec("text", tr("文字", "Text"), "text"),
    ],
    BROWSER_KIND: [
        PropSpec("url", tr("アドレス", "URL"), "text"),
        PropSpec("width", tr("幅", "Width"), "int",
                 min_value=1, max_value=7680, unit=tr("ピクセル", " pixels")),
        PropSpec("height", tr("高さ", "Height"), "int",
                 min_value=1, max_value=4320, unit=tr("ピクセル", " pixels")),
    ],
    COLOR_KIND: [
        PropSpec("color", tr("色", "Color"), "choice", choices=COLOR_CHOICES),
        PropSpec("width", tr("幅", "Width"), "int",
                 min_value=1, max_value=7680, unit=tr("ピクセル", " pixels")),
        PropSpec("height", tr("高さ", "Height"), "int",
                 min_value=1, max_value=4320, unit=tr("ピクセル", " pixels")),
    ],
}

# 値→日本語ラベル。OBSが返す itemName は読点まじりで長い
# （例「タイトルに一致、そうでなければ同じ実行可能ファイルのウィンドウを見つける」）。
# 一覧の行は「ラベル、値」の形なので、値に読点が入ると区切りが分からなくなる。
# ★キーは itemValue（並び順ではない）
PRIORITY_JP = {
    PRIORITY_TITLE: tr("タイトルが一致", "Match title"),
    PRIORITY_CLASS: tr("種類が一致", "Match type"),
    PRIORITY_EXE: tr("実行ファイルが一致", "Match executable"),
}
CAPTURE_MODE_JP = {
    "any_fullscreen": tr("全画面のゲーム", "Any fullscreen application"),
    "window": tr("特定のウィンドウ", "Specific window"),
    "hotkey": tr("ホットキーで前面", "Foreground window by hotkey"),
}


MONITOR_SPEC = PropSpec(MONITOR_KEY, tr("音声モニタリング", "Audio monitoring"), "monitor")


def monitor_label(mon_type: str) -> str:
    """モニタリング設定を読み上げ用の日本語にする。"""
    return MONITOR_JP.get(mon_type, tr("不明", "unknown"))


def specs_for_kind(kind: str) -> list[PropSpec]:
    """種別の編集できる項目一覧。未対応なら空リスト。"""
    return PROP_TABLE.get(kind, [])


def spec_by_key(kind: str, key: str) -> PropSpec | None:
    """種別とキーから項目定義を引く。無ければ None。"""
    for spec in specs_for_kind(kind):
        if spec.key == key:
            return spec
    return None


def is_media_kind(kind: str) -> bool:
    """メディア操作（再生・一時停止）を持つ種別か。"""
    return kind in MEDIA_KINDS


def merge_settings(defaults: dict | None, current: dict | None) -> dict:
    """既定値の上に現在値を重ねる。

    GetInputSettings は「明示的に保存されている値」しか返さない
    （既定のままの項目は入っていない）。そのため現在値の表示には
    必ず既定値とのマージが要る。
    """
    out: dict = dict(defaults or {})
    out.update(current or {})
    return out


def diff_settings(before: dict | None, after: dict | None) -> dict:
    """after のうち before と違うキーだけを返す。

    set_input_settings には常にこの差分だけを渡す。全キーを送ると
    「表に載せていない設定」まで巻き込んで書き込んでしまう。
    """
    before = before or {}
    out: dict = {}
    for key, value in (after or {}).items():
        if key not in before or before[key] != value:
            out[key] = value
    return out


def parse_window_class(window_value: str) -> str:
    """window 文字列 "タイトル:クラス:実行ファイル" のクラス部分。

    タイトル内の ':' は OBS 側で "#3A" にエスケープされるので、区切りの
    ':' はちょうど2個。末尾から2つに割って真ん中を取る。
    """
    if not window_value:
        return ""
    parts = window_value.rsplit(":", 2)
    if len(parts) < 3:
        return ""
    return parts[1]


def window_priority_for(window_value: str) -> int | None:
    """window 値に対して送るべき priority。送らない方がよければ None。

    通常は実行ファイル一致(2)。ゲームはタイトルが変わることが多いので、
    タイトルに縛らないほうが追従する。ただし UWP 系ウィンドウは OBS 側の
    照合が常にタイトル一致を要求するため、実行ファイル優先にすると
    「実行ファイル一致 かつ タイトル完全一致」と逆に狭くなる。
    """
    if not window_value:
        return None
    if parse_window_class(window_value) in UWP_CLASSES:
        return None
    return PRIORITY_EXE


def dedupe_items(items) -> list[dict]:
    """選択肢を itemValue で重複除去する（順序は保つ）。

    実測で同じウィンドウが複数回現れることがある（Spotify 等）。
    """
    seen: set = set()
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        value = it.get("itemValue")
        if value in seen:
            continue
        seen.add(value)
        out.append(it)
    return out


def sort_window_items(items) -> list[dict]:
    """起動中(itemEnabled=True)を先に、そうでないものを後ろにする。

    OBSは「今設定されている対象が一覧に無いとき」だけ、その対象を
    itemEnabled=false のプレースホルダとして挿入する。つまり false は
    「今は起動していない」を意味する。選びたいのはたいてい起動中の方
    なので前に出す。群の中の並びはOBSの順を保つ（安定ソート）。
    """
    real = [it for it in items or [] if isinstance(it, dict)]
    return sorted(real, key=lambda it: 0 if it.get("itemEnabled", True) else 1)


def first_running_index(items, current_value: str = "") -> int:
    """一覧の初期選択に使う位置。

    現在の設定値をそのまま初期選択にすると、その対象が起動していない
    ときに（＝末尾に並ぶので）矢印を最大件数ぶん押す羽目になる。
    切り替えたいのは「今起動している別のもの」なので、起動中で今の設定
    とは違うものを先に選んでおく。無ければ先頭。
    """
    real = [it for it in items or [] if isinstance(it, dict)]
    for idx, it in enumerate(real):
        if not it.get("itemEnabled", True):
            continue
        if current_value and it.get("itemValue") == current_value:
            continue
        return idx
    return 0


def index_of_value(items, value: str) -> int:
    """itemValue が一致する位置。無ければ -1。"""
    for idx, it in enumerate(items or []):
        if isinstance(it, dict) and it.get("itemValue") == value:
            return idx
    return -1


# 「今まさに音が出ている（出ようとしている）」とみなす再生状態。
# 読み込み中(OPENING/BUFFERING)も、放っておけば鳴り出すのでこちら側に入れる。
MEDIA_PLAYING_STATES = {
    "OBS_MEDIA_STATE_PLAYING",
    "OBS_MEDIA_STATE_OPENING",
    "OBS_MEDIA_STATE_BUFFERING",
}


def is_media_playing(state: str) -> bool:
    """メディアが鳴っている（鳴り出す）状態か。

    「ミュートしても自分には聞こえ続けます」のような、音が出ていることを
    前提にした案内を出してよいかの判定に使う。停止・一時停止中に言うと
    嘘になるため。
    """
    return state in MEDIA_PLAYING_STATES


def media_action_for_state(state: str) -> str:
    """今の再生状態から「再生・一時停止」ボタンで送るべき操作を決める。

    ★STOP の後に PLAY を送っても何も起きない（OBS側で停止時は内部の
    active が False になり、再生/一時停止の切り替えが効かないため）。
    停止・終了・未再生からは必ず RESTART を送る。
    """
    if is_media_playing(state):
        return MEDIA_PAUSE
    if state == "OBS_MEDIA_STATE_PAUSED":
        return MEDIA_PLAY
    return MEDIA_RESTART


def file_stem(path: str) -> str:
    """パスからファイル名の本体だけを取り出す（読み上げ用）。

    フルパスは記号だらけで読み上げに向かないので、拡張子もフォルダも
    落とす。Windowsの区切りに合わせるが、テストのため両方の区切りを見る。
    """
    if not path:
        return ""
    base = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return os.path.splitext(base)[0]


def value_label(kind: str, key: str, raw, item_label: str | None = None) -> str:
    """設定値を読み上げ用の短い日本語にする。

    item_label はOBSの選択肢一覧から引いた表示名（あれば優先度は低い：
    まず自前の対応表を見る。OBSの itemName は読点まじりで長いため）。
    """
    if key == "priority":
        try:
            return PRIORITY_JP.get(int(raw), item_label or str(raw))
        except (TypeError, ValueError):
            return item_label or str(raw)
    if key == "capture_mode":
        return CAPTURE_MODE_JP.get(str(raw), item_label or str(raw))
    return item_label or str(raw)


def choice_label(spec: PropSpec, raw) -> str:
    """spec 自身が持つ選択肢から読み上げ用の日本語を引く。

    OBSから選択肢を引けない項目（色など）のためのもの。
    無ければ値そのままを返す。
    """
    for value, label in spec.choices:
        if value == raw:
            return label
    return str(raw)


def format_value(
    spec: PropSpec, kind: str, raw, item_label: str | None = None
) -> str:
    """項目1つの現在値を読み上げ用の文字列にする。"""
    if spec.type == "bool":
        return tr("オン", "on") if bool(raw) else tr("オフ", "off")
    if spec.type == "int":
        try:
            return f"{int(raw)}{spec.unit}"
        except (TypeError, ValueError):
            return f"{raw}{spec.unit}"
    if spec.type == "file":
        stem = file_stem(str(raw or ""))
        return stem if stem else tr("未設定", "not set")
    if spec.type == "choice":
        return choice_label(spec, raw) if raw is not None else tr("未設定", "not set")
    if spec.type == "text":
        # 長い本文をそのまま読むと聞き終わらないので、頭だけ読む。
        # 全文は OBS 側か、変更時の読み上げで確かめられる
        text = " ".join(str(raw or "").split())
        if not text:
            return tr("未設定", "not set")
        return text if len(text) <= 30 else text[:30] + tr(" 以下略", " and so on")
    if raw is None or raw == "":
        return tr("未設定", "not set")
    return value_label(kind, spec.key, raw, item_label)
