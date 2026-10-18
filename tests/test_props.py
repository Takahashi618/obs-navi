# -*- coding: utf-8 -*-
"""ソース設定（プロパティ）まわりの純関数・コマンド層テスト。

選択肢のサンプルは、実機の OBS から取得した実データを使う。
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import commands, props, speech_format  # noqa: E402
from core.settings_op import SettingsOp  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# 実機のゲームキャプチャ window 選択肢（抜粋）。
# 先頭は「設定済みだが今は起動していない」＝itemEnabled=False
WINDOW_ITEMS = [
    {"itemEnabled": False, "itemName": "[Diablo IV.exe]: ディアブロ IV",
     "itemValue": "ディアブロ IV:Diablo IV Main Window Class:Diablo IV.exe"},
    {"itemEnabled": True, "itemName": "[SpotifyXboxGamebarWebView.exe]: Spotify Widget",
     "itemValue": "Spotify Widget:Windows.UI.Core.CoreWindow:SpotifyXboxGamebarWebView.exe"},
    {"itemEnabled": True, "itemName": "[msedge.exe]: Microsoft Edge",
     "itemValue": "Microsoft Edge:Chrome_WidgetWin_1:msedge.exe"},
    # 重複（実測で Spotify が複数出た）
    {"itemEnabled": True, "itemName": "[SpotifyXboxGamebarWebView.exe]: Spotify Widget",
     "itemValue": "Spotify Widget:Windows.UI.Core.CoreWindow:SpotifyXboxGamebarWebView.exe"},
]

DEVICE_ITEMS = [
    {"itemEnabled": True, "itemName": "既定", "itemValue": "default"},
    {"itemEnabled": True, "itemName": "Line (Steinberg UR44C)",
     "itemValue": "{0.0.1.aaa}"},
    {"itemEnabled": True, "itemName": "CABLE Output (VB-Audio Virtual Cable)",
     "itemValue": "{0.0.1.bbb}"},
]


# ------------------------------------------------------------
# props: 表と純関数
# ------------------------------------------------------------
def test_specs() -> None:
    specs = props.specs_for_kind("game_capture")
    check("game_captureに項目がある", len(specs) > 0)
    check("windowが先頭（変更頻度が高い）", specs[0].key == "window",
          specs[0].key if specs else "")
    check("未知の種別は空", props.specs_for_kind("unknown_kind") == [])
    spec = props.spec_by_key("game_capture", "priority")
    check("キーで引ける", spec is not None and spec.label == "一致の優先")
    check("無いキーはNone", props.spec_by_key("game_capture", "zzz") is None)
    check("ffmpegはメディア種別", props.is_media_kind("ffmpeg_source") is True)
    check("wasapiはメディアでない",
          props.is_media_kind("wasapi_input_capture") is False)


def test_merge_and_diff() -> None:
    defaults = {"looping": False, "speed_percent": 100}
    current = {"local_file": "C:/a.mp3", "looping": True}
    merged = props.merge_settings(defaults, current)
    check("既定に現在値を重ねる", merged["looping"] is True, str(merged))
    check("既定のみの値も残る", merged["speed_percent"] == 100, str(merged))
    check("現在値のみの値も入る", merged["local_file"] == "C:/a.mp3", str(merged))
    check("Noneでも壊れない", props.merge_settings(None, None) == {})

    d = props.diff_settings({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
    check("変わったキーだけ返す", d == {"b": 3, "c": 4}, str(d))
    check("差分無しは空", props.diff_settings({"a": 1}, {"a": 1}) == {})


def test_window_helpers() -> None:
    v = "ディアブロ IV:Diablo IV Main Window Class:Diablo IV.exe"
    check("クラスを取り出す",
          props.parse_window_class(v) == "Diablo IV Main Window Class",
          props.parse_window_class(v))
    # タイトルに ':' がエスケープされて含まれる場合でも区切りは2個
    v2 = "C#3A\\Users\\x\\python.exe:CASCADIA:WindowsTerminal.exe"
    check("エスケープ済みでもクラスを取り出す",
          props.parse_window_class(v2) == "CASCADIA",
          props.parse_window_class(v2))
    check("空文字は空", props.parse_window_class("") == "")

    check("通常は実行ファイル一致(2)",
          props.window_priority_for(v) == props.PRIORITY_EXE)
    uwp = "Spotify Widget:Windows.UI.Core.CoreWindow:Spotify.exe"
    check("UWPはpriorityを送らない",
          props.window_priority_for(uwp) is None)
    check("空はNone", props.window_priority_for("") is None)


def test_item_list_helpers() -> None:
    dedup = props.dedupe_items(WINDOW_ITEMS)
    check("重複を除く", len(dedup) == 3, str(len(dedup)))
    sorted_items = props.sort_window_items(dedup)
    check("起動中が先頭に来る",
          sorted_items[0].get("itemEnabled") is True,
          str(sorted_items[0]))
    check("起動していないものは最後",
          sorted_items[-1].get("itemEnabled") is False,
          str(sorted_items[-1]))
    # 起動中の並びはOBSの順を保つ（安定ソート）
    check("群内の順序は保たれる",
          sorted_items[0]["itemValue"].endswith("SpotifyXboxGamebarWebView.exe"),
          sorted_items[0]["itemValue"])


def test_first_running_index() -> None:
    items = props.sort_window_items(props.dedupe_items(WINDOW_ITEMS))
    current = "ディアブロ IV:Diablo IV Main Window Class:Diablo IV.exe"
    idx = props.first_running_index(items, current)
    check("起動中かつ現在値でないものを初期選択",
          items[idx].get("itemEnabled") is True and
          items[idx]["itemValue"] != current, str(idx))
    # 現在値が起動中なら、それとは違う起動中を選ぶ
    running_current = items[0]["itemValue"]
    idx2 = props.first_running_index(items, running_current)
    check("現在値は避ける", items[idx2]["itemValue"] != running_current, str(idx2))
    check("空なら0", props.first_running_index([], "") == 0)


def test_index_of_value() -> None:
    check("値の位置を返す",
          props.index_of_value(WINDOW_ITEMS, "Microsoft Edge:Chrome_WidgetWin_1:msedge.exe") == 2)
    check("無ければ-1", props.index_of_value(WINDOW_ITEMS, "無い") == -1)


def test_media_action_for_state() -> None:
    check("再生中は一時停止へ",
          props.media_action_for_state("OBS_MEDIA_STATE_PLAYING")
          == props.MEDIA_PAUSE)
    check("一時停止は再生へ",
          props.media_action_for_state("OBS_MEDIA_STATE_PAUSED")
          == props.MEDIA_PLAY)
    # 停止からPLAYを送っても効かないので必ずRESTART
    check("停止は最初から",
          props.media_action_for_state("OBS_MEDIA_STATE_STOPPED")
          == props.MEDIA_RESTART)
    check("終了は最初から",
          props.media_action_for_state("OBS_MEDIA_STATE_ENDED")
          == props.MEDIA_RESTART)
    check("空文字も最初から",
          props.media_action_for_state("") == props.MEDIA_RESTART)


def test_is_media_playing() -> None:
    """鳴っている状態の判定（ミュート時の案内を出すかの判断に使う）。"""
    check("再生中", props.is_media_playing("OBS_MEDIA_STATE_PLAYING") is True)
    check("読み込み中も鳴る側",
          props.is_media_playing("OBS_MEDIA_STATE_OPENING") is True)
    check("バッファ中も鳴る側",
          props.is_media_playing("OBS_MEDIA_STATE_BUFFERING") is True)
    check("一時停止は鳴っていない",
          props.is_media_playing("OBS_MEDIA_STATE_PAUSED") is False)
    check("停止は鳴っていない",
          props.is_media_playing("OBS_MEDIA_STATE_STOPPED") is False)
    check("終了は鳴っていない",
          props.is_media_playing("OBS_MEDIA_STATE_ENDED") is False)
    check("空文字は鳴っていない", props.is_media_playing("") is False)
    # media_action_for_state と同じ集合を見ていること（判定の一元化）
    for state in props.MEDIA_PLAYING_STATES:
        check(f"{state} は一時停止を送る状態",
              props.media_action_for_state(state) == props.MEDIA_PAUSE)


def test_file_stem_and_format() -> None:
    check("Windowsパスから本体",
          props.file_stem("C:\\Music\\夜想曲.mp3") == "夜想曲")
    check("スラッシュ区切りでも",
          props.file_stem("/home/x/song.flac") == "song")
    check("空は空", props.file_stem("") == "")

    spec_bool = props.spec_by_key("ffmpeg_source", "looping")
    check("boolはオン",
          props.format_value(spec_bool, "ffmpeg_source", True) == "オン")
    check("boolはオフ",
          props.format_value(spec_bool, "ffmpeg_source", False) == "オフ")
    spec_int = props.spec_by_key("ffmpeg_source", "speed_percent")
    check("intは単位つき",
          props.format_value(spec_int, "ffmpeg_source", 100) == "100パーセント")
    spec_file = props.spec_by_key("ffmpeg_source", "local_file")
    check("fileは名前だけ",
          props.format_value(spec_file, "ffmpeg_source", "C:\\a\\曲.mp3") == "曲")
    check("file未設定",
          props.format_value(spec_file, "ffmpeg_source", "") == "未設定")


def test_value_label() -> None:
    # priority は値と並び順が違う。必ず値で引く
    check("priority 2は実行ファイル",
          props.value_label("game_capture", "priority", 2) == "実行ファイルが一致")
    check("priority 1はタイトル",
          props.value_label("game_capture", "priority", 1) == "タイトルが一致")
    check("priority 0は種類",
          props.value_label("game_capture", "priority", 0) == "種類が一致")
    check("capture_mode window",
          props.value_label("game_capture", "capture_mode", "window")
          == "特定のウィンドウ")
    # 表に無いものは OBS のラベルにフォールバック
    check("未知は渡されたラベル",
          props.value_label("game_capture", "window", "v", "表示名") == "表示名")


# ------------------------------------------------------------
# speech_format: 新規の読み上げ整形
# ------------------------------------------------------------
def test_speech_safe() -> None:
    out = speech_format.speech_safe("ゲーム™ タイトル")
    check("cp932にない文字を落とす", "™" not in out, out)
    check("本文は残る", "ゲーム" in out and "タイトル" in out, out)
    check("空は空", speech_format.speech_safe("") == "")


def test_parse_window_item() -> None:
    title, exe = speech_format.parse_window_item("[Diablo IV.exe]: ディアブロ IV")
    check("タイトルを取り出す", title == "ディアブロ IV", title)
    check("拡張子を落とす", exe == "Diablo IV", exe)
    t2, e2 = speech_format.parse_window_item("形式が違う")
    check("形式違いは全体をタイトルに", t2 == "形式が違う" and e2 == "", f"{t2}/{e2}")


def test_window_item_label() -> None:
    label = speech_format.window_item_label("[Diablo IV.exe]: ディアブロ IV", True)
    check("タイトルと実行ファイルを読む",
          "ディアブロ IV" in label and "Diablo IV" in label, label)
    off = speech_format.window_item_label("[Diablo IV.exe]: ディアブロ IV", False)
    check("未起動を明示", "今は起動していません" in off, off)
    # 記号だらけのタイトルは読みやすく整える
    noisy = speech_format.window_item_label(
        "[x.exe]: C:\\Users\\a\\b【重要】", True)
    for ch in "\\[]【】":
        check(f"記号 {ch} を残さない", ch not in noisy, noisy)
    # 長いタイトルは切り詰める
    long_title = "[x.exe]: " + "あ" * 60
    out = speech_format.window_item_label(long_title, True)
    check("長いタイトルを切る", "ほか" in out and len(out) < 60, out)


def test_window_value_label() -> None:
    # 設定値そのもの（記号だらけ）を、一覧を引かずに読める形へ
    v = "ディアブロ IV:Diablo IV Main Window Class:Diablo IV.exe"
    out = speech_format.window_value_label(v)
    check("タイトルと実行ファイルだけ読む", out == "ディアブロ IV、Diablo IV", out)
    check("クラス名を読まない", "Main Window Class" not in out, out)
    check("コロンを残さない", ":" not in out, out)
    # エスケープされたコロンを読み上げない
    v2 = "C#3A\\Users\\x\\a.py:CASCADIA:WindowsTerminal.exe"
    out2 = speech_format.window_value_label(v2)
    check("#3Aを読まない", "#3A" not in out2 and "#" not in out2, out2)
    check("未設定は未設定", speech_format.window_value_label("") == "未設定")


def test_device_item_label() -> None:
    label = speech_format.device_item_label("Line (Steinberg UR44C)", True)
    check("括弧を読点に開く", label == "Line、Steinberg UR44C", label)
    off = speech_format.device_item_label("CABLE Output (VB)", False)
    check("使えないデバイスを明示", "今は使えません" in off, off)


def test_prop_speech() -> None:
    check("行の表示",
          speech_format.prop_row_label("対象ウィンドウ", "ディアブロ IV")
          == "対象ウィンドウ、ディアブロ IV")
    check("1件変更",
          speech_format.prop_changed_speech("ゲームキャプチャ", "対象ウィンドウ", "X")
          == "ゲームキャプチャ の 対象ウィンドウ を X にしました")
    multi = speech_format.prop_multi_changed_speech(
        "ゲームキャプチャ", [("取り込み方法", "特定のウィンドウ"), ("対象ウィンドウ", "X")])
    check("複数変更は1文", "ゲームキャプチャ を変えました" in multi, multi)
    check("0件は変更なし",
          speech_format.prop_multi_changed_speech("X", []) == "変更はありません")
    check("1件は単数形に委譲",
          speech_format.prop_multi_changed_speech("S", [("L", "V")])
          == "S の L を V にしました")
    check("未適用の警告",
          "受け付けていません"
          in speech_format.prop_unchanged_speech("S", "L"))


def test_game_switch_speech() -> None:
    s = speech_format.game_switch_speech(
        "ディアブロ IV", "ゲームキャプチャ", ["ゲーム音"], [], True)
    check("両方成功", "ディアブロ IV に切り替えました" in s and "ゲーム音" in s, s)
    s2 = speech_format.game_switch_speech(
        "ディアブロ IV", "ゲームキャプチャ", [], ["ゲーム音"], True)
    check("音声が見つからないと案内", "見つかりません" in s2 and "F3" in s2, s2)
    s3 = speech_format.game_switch_speech(
        "ディアブロ IV", "ゲームキャプチャ", ["ゲーム音"], [], False)
    check("未起動を伝える", "起動すると映ります" in s3, s3)


def test_media_speech() -> None:
    check("分秒", speech_format.fmt_media_time(80000) == "1分20秒")
    check("3分5秒", speech_format.fmt_media_time(185000) == "3分5秒")
    check("時間つき", speech_format.fmt_media_time(3723000) == "1時間2分3秒")
    check("Noneは不明", speech_format.fmt_media_time(None) == "不明")
    check("状態の日本語",
          speech_format.media_state_jp("OBS_MEDIA_STATE_PLAYING") == "再生中")
    st = speech_format.media_status_speech(
        "BGM音楽", "OBS_MEDIA_STATE_PLAYING", 80000, 185000)
    check("位置と長さを読む", "1分20秒" in st and "3分5秒" in st, st)
    st2 = speech_format.media_status_speech(
        "BGM音楽", "OBS_MEDIA_STATE_STOPPED", None, None)
    check("位置が無いときは状態だけ", st2 == "BGM音楽 停止", st2)
    # PLAY は PlaybackStarted 側で読むのでここでは空
    check("PLAYは空（二重読み回避）",
          speech_format.media_action_speech("BGM音楽", props.MEDIA_PLAY) == "")
    check("PAUSEは読む",
          "一時停止" in speech_format.media_action_speech(
              "BGM音楽", props.MEDIA_PAUSE))
    check("ファイル設定はファイル名だけ",
          speech_format.bgm_file_speech("BGM音楽", "C:\\music\\夜想曲.mp3")
          == "BGM音楽 の音楽ファイルを 夜想曲 にしました")
    check("フルパスを読まない",
          "C:" not in speech_format.bgm_file_speech("B", "C:\\music\\x.mp3"))
    check("種別違いの案内",
          "メディアソース" in speech_format.bgm_wrong_kind_speech("BGM"))


# ------------------------------------------------------------
# SettingsOp（合流器）
# ------------------------------------------------------------
def test_monitor() -> None:
    # 内部名ではなく「何が起きるか」で読ませる
    check("オフの説明",
          "聞こえない" in props.monitor_label(props.MONITOR_NONE),
          props.monitor_label(props.MONITOR_NONE))
    check("モニターのみの説明",
          "配信には乗らない" in props.monitor_label(props.MONITOR_ONLY),
          props.monitor_label(props.MONITOR_ONLY))
    check("モニターと出力の説明",
          "配信にも乗る" in props.monitor_label(props.MONITOR_AND_OUTPUT),
          props.monitor_label(props.MONITOR_AND_OUTPUT))
    check("未知は不明", props.monitor_label("なにか") == "不明")
    check("選択肢は3つ", len(props.MONITOR_CHOICES) == 3)
    check("設定キーが他と衝突しない",
          props.MONITOR_KEY.startswith("__"), props.MONITOR_KEY)
    s = speech_format.monitor_changed_speech("BGM", props.MONITOR_AND_OUTPUT)
    check("変更の読み上げ", "BGM" in s and "自分も聞く" in s, s)


def test_commands_monitor() -> None:
    class MonClient:
        def __init__(self):
            self.mon = {"BGM": props.MONITOR_NONE}
            self.sets = []

        def get_input_audio_monitor_type(self, name):
            if name not in self.mon:
                raise RuntimeError("音声を持たない入力")
            return SimpleNamespace(monitor_type=self.mon[name])

        def set_input_audio_monitor_type(self, name, mon_type):
            self.sets.append((name, mon_type))
            self.mon[name] = mon_type

    c = MonClient()
    check("現在値を取得",
          commands.fetch_monitor_type(c, "BGM") == props.MONITOR_NONE)
    # 音声を持たない入力は空文字（行を出すかの判定に使う）
    check("音声なしは空文字", commands.fetch_monitor_type(c, "映像だけ") == "")
    commands.set_monitor_type(c, "BGM", props.MONITOR_AND_OUTPUT)
    check("設定が送られる",
          c.sets == [("BGM", props.MONITOR_AND_OUTPUT)], str(c.sets))


def test_settings_op() -> None:
    op = SettingsOp(op_id=1, kind="game_switch",
                    sources=["ゲームキャプチャ", "ゲーム音"],
                    expected={"ゲームキャプチャ": {"window": "A"},
                              "ゲーム音": {"window": "B"}})
    check("最初は未完了", op.is_complete() is False)
    check("両方が未達", op.missing() == ["ゲームキャプチャ", "ゲーム音"], str(op.missing()))
    done = op.note("ゲーム音", {"window": "B"})
    check("片方だけでは完了しない", done is False)
    check("残りが分かる", op.missing() == ["ゲームキャプチャ"], str(op.missing()))
    done2 = op.note("ゲームキャプチャ", {"window": "A"})
    check("そろえば完了", done2 is True)
    # 対象外の入力は observed に記録されないこと（戻り値は既に完了して
    # いるため常に True になり、無視の検証にはならない）
    op.note("無関係", {"x": 1})
    check("対象外の入力は記録されない", "無関係" not in op.observed,
          str(op.observed))
    check("適用済みを判定", op.applied("ゲームキャプチャ", "window") is True)
    # OBSが受け付けなかった場合
    op2 = SettingsOp(op_id=2, kind="prop", sources=["S"],
                     expected={"S": {"window": "A"}})
    op2.note("S", {"window": "別の値"})
    check("値が違えば未適用", op2.applied("S", "window") is False)


# ------------------------------------------------------------
# commands: FakeClient で疎通
# ------------------------------------------------------------
class FakeClient:
    """設定まわりの呼び出しを記録するフェイク。"""

    def __init__(self) -> None:
        self.settings: dict[str, dict] = {"ゲームキャプチャ": {"window": "OLD"}}
        self.kinds: dict[str, str] = {"ゲームキャプチャ": "game_capture"}
        self.applied: list[tuple] = []
        self.created: list[tuple] = []
        self.actions: list[tuple] = []
        self.opened: list[str] = []
        self.media_state = "OBS_MEDIA_STATE_PLAYING"

    def get_input_settings(self, name):
        if name not in self.settings:
            raise RuntimeError("no such input")
        return SimpleNamespace(input_settings=dict(self.settings[name]),
                               input_kind=self.kinds.get(name, ""))

    def get_input_default_settings(self, kind):
        return SimpleNamespace(
            default_input_settings={"capture_cursor": True, "priority": 0})

    def get_input_properties_list_property_items(self, name, prop):
        return SimpleNamespace(property_items=WINDOW_ITEMS)

    def set_input_settings(self, name, settings, overlay):
        self.applied.append((name, dict(settings), overlay))
        self.settings.setdefault(name, {}).update(settings)

    def create_input(self, scene, name, kind, settings, enabled):
        self.created.append((scene, name, kind, dict(settings), enabled))

    def trigger_media_input_action(self, name, action):
        self.actions.append((name, action))

    def get_media_input_status(self, name):
        return SimpleNamespace(media_state=self.media_state,
                               media_cursor=80000, media_duration=185000)

    def open_input_properties_dialog(self, name):
        self.opened.append(name)


def test_commands_settings() -> None:
    c = FakeClient()
    s = commands.fetch_input_settings(c, "ゲームキャプチャ")
    check("設定を取得", s == {"window": "OLD"}, str(s))
    check("種別を取得",
          commands.fetch_input_kind(c, "ゲームキャプチャ") == "game_capture")
    check("無い入力の種別は空", commands.fetch_input_kind(c, "無い") == "")
    merged = commands.fetch_merged_settings(c, "ゲームキャプチャ", "game_capture")
    check("既定とマージされる", merged.get("capture_cursor") is True, str(merged))
    check("現在値が優先", merged.get("window") == "OLD", str(merged))

    items = commands.fetch_property_items(c, "ゲームキャプチャ", "window")
    check("選択肢を取得", len(items) == len(WINDOW_ITEMS), str(len(items)))


def test_commands_apply_always_overlay() -> None:
    c = FakeClient()
    commands.apply_input_settings(c, "ゲームキャプチャ", {"window": "NEW"})
    name, settings, overlay = c.applied[0]
    check("上書きマージで送る（overlay=True）", overlay is True, str(overlay))
    check("設定が渡る", settings == {"window": "NEW"}, str(settings))
    # overlay を引数に取らない＝誤って全リセットできない
    import inspect
    sig = inspect.signature(commands.apply_input_settings)
    check("overlay引数を持たない", "overlay" not in sig.parameters, str(sig))


def test_commands_media() -> None:
    c = FakeClient()
    commands.create_media_input(c, "シーン", "BGM音楽", "C:\\a\\曲.mp3")
    scene, name, kind, settings, enabled = c.created[0]
    check("メディアソースを作る", kind == "ffmpeg_source", kind)
    check("ファイルを設定", settings.get("local_file") == "C:\\a\\曲.mp3")
    check("ローカルファイル指定", settings.get("is_local_file") is True)
    # シーン切り替えで勝手に頭出しされないようにする
    check("restart_on_activateはFalse",
          settings.get("restart_on_activate") is False, str(settings))
    check("ループは有効", settings.get("looping") is True)
    check("シーンアイテムは有効", enabled is True)

    commands.trigger_media_action(c, "BGM音楽", commands.MEDIA_PAUSE)
    check("操作が送られる",
          c.actions[0] == ("BGM音楽", commands.MEDIA_PAUSE), str(c.actions))
    state, cur, dur = commands.fetch_media_status(c, "BGM音楽")
    check("状態を取得", state == "OBS_MEDIA_STATE_PLAYING", state)
    check("位置を取得", cur == 80000, str(cur))

    commands.open_properties_dialog(c, "ゲームキャプチャ")
    check("OBSのプロパティ画面を開く", c.opened == ["ゲームキャプチャ"], str(c.opened))


def test_commands_error_tolerance() -> None:
    class Broken:
        def get_input_settings(self, name):
            raise RuntimeError("boom")

        def get_input_default_settings(self, kind):
            raise RuntimeError("boom")

        def get_input_properties_list_property_items(self, name, prop):
            raise RuntimeError("boom")

        def get_media_input_status(self, name):
            raise RuntimeError("boom")

    b = Broken()
    check("種別取得は空に落ちる", commands.fetch_input_kind(b, "x") == "")
    check("既定取得は空辞書", commands.fetch_input_default_settings(b, "k") == {})
    check("選択肢取得は空リスト", commands.fetch_property_items(b, "x", "p") == [])
    check("メディア状態は空タプル",
          commands.fetch_media_status(b, "x") == ("", None, None))


def run() -> tuple[int, int]:
    for fn in (
        test_specs,
        test_merge_and_diff,
        test_window_helpers,
        test_item_list_helpers,
        test_first_running_index,
        test_index_of_value,
        test_media_action_for_state,
        test_is_media_playing,
        test_file_stem_and_format,
        test_value_label,
        test_speech_safe,
        test_parse_window_item,
        test_window_item_label,
        test_window_value_label,
        test_device_item_label,
        test_prop_speech,
        test_game_switch_speech,
        test_media_speech,
        test_monitor,
        test_commands_monitor,
        test_settings_op,
        test_commands_settings,
        test_commands_apply_always_overlay,
        test_commands_media,
        test_commands_error_tolerance,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _results.append((f"{fn.__name__} が例外で失敗", False, repr(exc)))
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    return passed, failed


def results() -> list[tuple[str, bool, str]]:
    return _results


if __name__ == "__main__":
    p, f = run()
    for nm, ok, detail in _results:
        mark = "OK" if ok else "NG"
        line = f"[{mark}] {nm}"
        if not ok and detail:
            line += f" -> {detail}"
        print(line)
    print(f"props: {p} passed, {f} failed")
