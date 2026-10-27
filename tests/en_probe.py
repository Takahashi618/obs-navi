# -*- coding: utf-8 -*-
"""英語の画面を実際に作り、日本語が残っていないかを調べる。

★run_tests.py には入れていない（wx.App を作るので重い。smoke_ui.py と
同じ扱い）。言語は起動時に1回だけ決まるので、このスクリプトは自分で
英語に固定して走る。手で走らせる:

    python -X utf8 tests/en_probe.py

集めるもの: 窓の見出し、部品の名前とラベル、一覧の行、メニュー（各リストの
操作メニューも）、キー操作の一覧、各設定画面、未接続のときの読み上げ、
読み上げの文を作る関数（core/speech_format.py）のほぼすべて。
どれかに かな・漢字・全角の記号 があれば NG。最後に、わざと日本語を
混ぜて検査が見つけることも確かめる。
"""
import io
import os
import re
import sys

os.environ["OBSNAVI_SILENT"] = "1"
os.environ["OBSNAVI_LANG"] = "en"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx  # noqa: E402

import speech  # noqa: E402
from core import (  # noqa: E402
    camera, commands, filters, i18n, keymap, props, scenes, sources,
    speech_format, tracks)
from core.config import Config  # noqa: E402
from core.connection import ObsConnectError  # noqa: E402
from core.state import AudioInput, Snapshot  # noqa: E402

import ui.main_frame as mf  # noqa: E402
import ui.prop_dialog as pd  # noqa: E402

JP = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff\uff01-\uff60]")
# 日本語と英語を併記している項目（どちらの言葉でも見つけられるように）
BILINGUAL = {"表示の言語 (Language)"}

fails = []
texts: list[tuple[str, str]] = []


def check(name, cond, detail=""):
    print(("[OK] " if cond else "[NG] ") + name + ("" if cond else f" -> {detail}"))
    if not cond:
        fails.append(name)


def collect(where, text):
    if text:
        texts.append((where, str(text)))


def collect_window(where, win):
    collect(where + " 見出し", win.GetTitle() if isinstance(
        win, wx.TopLevelWindow) else "")
    for child in win.GetChildren():
        collect(where + " 名前", child.GetName())
        collect(where + " ラベル", child.GetLabel())
        if isinstance(child, (wx.ListBox, wx.Choice)):
            for row in child.GetStrings():
                collect(where + " 行", row)
        if isinstance(child, wx.TextCtrl):
            collect(where + " 本文", child.GetValue())
        collect_window(where, child)


def collect_menu(where, menu):
    for item in menu.GetMenuItems():
        collect(where, item.GetItemLabel())
        if item.GetSubMenu():
            collect_menu(where, item.GetSubMenu())


check("言語は英語", i18n.language() == "en", i18n.language())


def _refuse_connect(self, callbacks=None):
    raise ObsConnectError("not connecting in the probe")


mf.ObsConnection.connect = _refuse_connect

said: list[str] = []
speech.speak = lambda text, *a, **k: said.append(text)
speech.warn = lambda text, *a, **k: said.append("[Warning] " + text)
speech.error = lambda text, *a, **k: said.append("[Error] " + text)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "obs_navi_config.json")
_before = (io.open(CONFIG_PATH, "rb").read()
           if os.path.exists(CONFIG_PATH) else None)

cfg = Config()
cfg._save_blocked = True  # 利用者の設定へ書かない（smoke_ui.py と同じ）
check("既定のソース名が英語",
      cfg.game_switch["video_source"] == "Game Capture"
      and cfg.sr_sources[0]["name"] == "NVDA Voice",
      str(cfg.game_switch) + str(cfg.sr_sources))

problems: list[str] = []
_orig_announce = mf.MainFrame._announce_key_problems


def _capture_problems(self):
    problems.extend(self._key_problems)
    _orig_announce(self)


mf.MainFrame._announce_key_problems = _capture_problems

app = wx.App()
frame = mf.MainFrame(cfg)
check("メニューとキー一覧の文言が食い違わない", not problems, str(problems))

snap = Snapshot(connected=True)
snap.scenes = ["Live", "Break"]
snap.current_scene = "Live"
snap.audio_inputs = [AudioInput(name="Mic", muted=False, volume_db=-6.0),
                     AudioInput(name="Music", muted=True, volume_db=0.0)]
frame.apply_snapshot(snap)
collect_window("メイン", frame)
collect("メイン 見出し", frame.GetTitle())
bar = frame.GetMenuBar()
for i in range(bar.GetMenuCount()):
    collect("メニュー見出し", bar.GetMenuLabel(i))
    collect_menu("メニュー", bar.GetMenu(i))
for lst in (frame.scene_list, frame.item_list, frame.input_list,
            frame.filter_list):
    menu = frame.build_list_menu(lst)
    collect_menu("操作メニュー", menu)
    menu.Destroy()
collect("キー操作の一覧", keymap.help_text(cfg))
for row in keymap.help_rows(cfg):
    collect("キー一覧の行", row.keys)

# 未接続のときの操作（接続を求める読み上げ）
frame.conn.req = None
frame.on_about(None)
frame.announce_state()
frame.announce_levels()

# --- 設定の画面（OBS には繋がず、読み込みを差し替える） ---
commands.fetch_merged_settings = lambda c, n, k: {}
commands.fetch_property_items = lambda c, n, k: []
commands.fetch_monitor_type = lambda c, n: props.MONITOR_ONLY
commands.fetch_input_audio_tracks = lambda c, n: (True, False, True,
                                                  False, False, False)
commands.fetch_media_status = lambda c, n: (
    "OBS_MEDIA_STATE_PLAYING", 61000, 3723000)
commands.fetch_transitions = lambda c: []
commands.fetch_scene_transition = lambda c, n: scenes.SceneTransition()
commands.fetch_record_tracks = lambda c: {
    "section": "AdvOut", "tracks": (True, True, False, False, False, False),
    "quality": ""}

for kind in list(props.PROP_TABLE) + ["unknown_kind"]:
    dlg = pd.SourcePropDialog(frame, "Source", kind)
    collect_window("ソースの設定 " + kind, dlg)
    dlg.Destroy()
for kind in list(filters.FILTER_TABLE) + ["unknown_filter"]:
    commands.fetch_merged_filter_settings = (
        lambda c, s, f, k=kind: (k, {"method": "speex"}))
    dlg = pd.FilterPropDialog(frame, "Mic", "Filter")
    collect_window("フィルターの設定 " + kind, dlg)
    dlg.Destroy()
dlg = pd.ScenePropDialog(frame, "Live")
collect_window("シーンの設定", dlg)
dlg.Destroy()
dlg = pd.RecordTracksDialog(frame)
collect_window("録画のトラック設定", dlg)
dlg.Destroy()
dlg = pd.KeyHelpDialog(frame, keymap.help_text(cfg))
collect_window("キー一覧の画面", dlg)
dlg.Destroy()
dlg = pd.OrderDialog(frame, "Source list order", ["Game", "Mic"], ["Old"],
                     present={"Game", "Mic"})
collect_window("並べ替え", dlg)
dlg.Destroy()

# --- 読み上げの文を作る関数 ---
sf = speech_format


class _Plan:
    name = "Game"
    behind = ["Camera", "Window"]
    blank = True


class _Trans:
    overridden = True
    name = "Fade"
    duration_ms = 300


class _NotTrans:
    overridden = False
    name = ""
    duration_ms = None


cam_states = [
    camera.build_state("Cam", {"active": True}, "c922", 1920.0, False),
    camera.build_state("Cam2", {"active": False}, "", 0.0, True),
    camera.build_state("Cam3", {"active": True}, "c922", 0.0, True),
]
spec_db = filters.FILTER_TABLE["compressor_filter"][1]
spec_ratio = filters.FILTER_TABLE["compressor_filter"][0]
spec_choice = filters.FILTER_TABLE["noise_suppress_filter_v2"][0]
calls = [
    lambda: sf.fmt_db(-18.4), lambda: sf.fmt_db(-120), lambda: sf.fmt_db(1),
    lambda: sf.fmt_volume_db(-100), lambda: sf.fmt_volume_db(6.5),
    lambda: sf.timecode_to_speech("01:01:01.000"),
    lambda: sf.state_summary(Snapshot()),
    lambda: sf.state_summary(snap),
    lambda: sf.level_summary({"Mic": -20.0, "Music": -50.0},
                             {"Music": True}),
    lambda: sf.level_summary({"Mic": -20.0}, {"Mic": True}, skip_muted=True),
    lambda: sf.level_summary({}),
    lambda: sf.order_saved_speech("the order", ["a"], True, ["a"]),
    lambda: sf.order_saved_speech("the order", [], False, []),
    lambda: sf.order_saved_speech("the order", ["a"], True, []),
    lambda: sf.order_unchanged_speech("the order"),
    lambda: sf.config_save_failed_speech("the order"),
    lambda: sf.order_reset_speech(True, 2), lambda: sf.order_reset_speech(False),
    lambda: sf.item_moved_speech("Cam", 1, 3, True),
    lambda: sf.item_move_edge_speech("Cam", False),
    lambda: sf.skip_muted_speech(True), lambda: sf.skip_muted_speech(False),
    lambda: sf.filter_kind_jp("noise_gate_filter"),
    lambda: sf.filter_list_label("Gate", True),
    lambda: sf.filter_toggle_speech("Gate", False),
    lambda: sf.scene_item_list_label("Cam", False),
    lambda: sf.scene_item_toggle_speech("Cam", True),
    lambda: sf.stats_summary({"cpu": 3.0, "fps": 60.0, "render_total": 100,
                              "render_skipped": 2, "output_total": 100,
                              "output_skipped": 0, "disk_free_mb": 50000.0}),
    lambda: sf.stats_summary({}),
    lambda: sf.onoff_speech("virtual camera", True),
    lambda: sf.input_list_label("Mic", True, -3.0),
    lambda: sf.window_item_label("[game.exe]: Game Title", False),
    lambda: sf.window_item_label(""),
    lambda: sf.window_value_label(""),
    lambda: sf.window_value_label("Title:Class:game.exe"),
    lambda: sf.device_item_label("Line (Steinberg UR44C)", False),
    lambda: sf.device_item_label(""),
    lambda: sf.prop_multi_changed_speech("Src", [("A", "1"), ("B", "2")]),
    lambda: sf.prop_multi_changed_speech("Src", []),
    lambda: sf.prop_unchanged_speech("Src", "Window"),
    lambda: sf.game_switch_speech("Game", "Game Capture", ["Game Audio"],
                                  ["Voice"]),
    lambda: sf.game_switch_speech("Game", "Game Capture", running=False),
    lambda: sf.media_status_speech("Music", "OBS_MEDIA_STATE_PAUSED",
                                   1000, 61000),
    lambda: sf.media_status_speech("Music", "X", None, None),
    lambda: sf.media_action_speech("Music", "X_PAUSE"),
    lambda: sf.media_action_speech("Music", "X_STOP"),
    lambda: sf.media_action_speech("Music", "X_RESTART"),
    lambda: sf.media_started_speech("Music"),
    lambda: sf.media_ended_speech("Music"),
    lambda: sf.bgm_file_speech("Music", ""),
    lambda: sf.video_item_label("Game", 0, 1, True),
    lambda: sf.video_front_speech(_Plan()),
    lambda: sf.video_already_front_speech("Game"),
    lambda: sf.video_unchanged_speech("Game"),
    lambda: sf.video_none_speech(),
    lambda: sf.mute_monitor_caveat(True, props.MONITOR_ONLY),
    lambda: sf.mute_monitor_caveat(True, props.MONITOR_ONLY,
                                   "OBS_MEDIA_STATE_PLAYING"),
    lambda: sf.mute_monitor_caveat(False, props.MONITOR_ONLY),
    lambda: sf.monitor_changed_speech("Music", props.MONITOR_NONE),
    lambda: sf.bgm_wrong_kind_speech("BGM"),
    lambda: sf.fmt_seconds(-1), lambda: sf.path_speech(""),
    lambda: sf.record_stopped_speech(""),
    lambda: sf.record_stopped_speech("C:/v/a.mkv"),
    lambda: sf.replay_saved_speech(""),
    lambda: sf.replay_saved_speech("C:/v/a.mkv"),
    lambda: sf.pause_reminder_speech(3700),
    lambda: sf.disk_warning_speech(2, 1000.0),
    lambda: sf.disk_warning_speech(1, None),
    lambda: sf.chapter_added_speech(2, "00:00:05"),
    lambda: sf.record_settings_summary({}),
    lambda: sf.record_settings_summary({
        "directory": "C:/v", "format": "hybrid_mp4", "quality": "HQ",
        "encoder": "obs_qsv11", "tracks": 5, "disk_free_mb": 900.0,
        "output_kind": ""}),
    lambda: sf.chapter_status_speech("mkv"),
    lambda: sf.chapter_unsupported_speech("mkv"),
    lambda: sf.chapter_unsupported_speech("hybrid_mp4"),
    lambda: sf.chapter_not_recording_speech(),
    lambda: sf.fmt_filter_value(spec_db, -18.0),
    lambda: sf.filter_prop_row(spec_ratio, 4.0),
    lambda: sf.filter_prop_row(spec_choice, "rnnoise"),
    lambda: sf.filter_prop_changed_speech("Comp", spec_db, -12),
    lambda: sf.filter_prop_unchanged_speech("Comp", spec_db),
    lambda: sf.filter_no_props_speech("X", True),
    lambda: sf.filter_no_props_speech("X", False),
    lambda: sf.filter_added_speech("Gate", "Mic"),
    lambda: sf.filter_removed_speech("Gate", "Mic"),
    lambda: sf.filter_none_speech("Mic"),
    lambda: sf.camera_list_speech([], ["c922"]),
    lambda: sf.camera_list_speech(cam_states, []),
    lambda: sf.camera_toggle_result_speech(cam_states[0], False),
    lambda: sf.camera_toggle_result_speech(cam_states[1], True),
    lambda: sf.camera_toggle_intent_speech("Cam", True),
    lambda: sf.camera_toggle_result_speech(None, True),
    lambda: sf.camera_none_speech(),
    lambda: sf.source_created_speech("Cam", sources.CREATABLE_KINDS[0], "Live"),
    lambda: sf.source_remove_warning("Cam", ["BGM"]),
    lambda: sf.source_removed_speech("Cam"),
    lambda: sf.scene_created_speech("New"),
    lambda: sf.scene_renamed_speech("A", "B"),
    lambda: sf.scene_remove_warning("Live", True),
    lambda: sf.scene_removed_speech("Live"),
    lambda: sf.scene_transition_row(_Trans()),
    lambda: sf.scene_transition_row(_NotTrans()),
    lambda: sf.scene_duration_row(_Trans()),
    lambda: sf.scene_duration_row(_NotTrans()),
    lambda: sf.scene_transition_changed_speech("Live", _NotTrans()),
    lambda: sf.scene_source_added_speech("Live", "Cam"),
    lambda: sf.scene_no_addable_speech("Live"),
    lambda: sf.license_notice_speech(), lambda: sf.ai_notice_speech(),
    lambda: sf.input_track_row(2, True),
    lambda: sf.input_tracks_changed_speech("Mic", 2, False,
                                           (False,) * 6),
    lambda: sf.input_tracks_changed_speech("Mic", 2, True,
                                           (True, True, True, False, True,
                                            False)),
    lambda: sf.input_tracks_unchanged_speech("Mic"),
    lambda: sf.record_track_row(1, False),
    lambda: sf.record_tracks_changed_speech((False,) * 6),
    lambda: sf.record_tracks_changed_speech((True, True, True, True,
                                             False, False)),
    lambda: sf.tracks_overview_speech(
        {"Mic": (False, False, False, False, True, False)},
        (True, False, False, False, False, False),
        tracks.simple_mode_note("SimpleOutput", "Stream")),
    lambda: sf.tracks_overview_speech({}, None),
    lambda: sf.tracks_recommendation_speech(),
]
for row in sources.CREATABLE_KINDS:
    calls.append(lambda r=row: sf.source_kind_row(r))
for row in filters.AUDIO_FILTER_KINDS:
    calls.append(lambda r=row: sf.filter_kind_row(r))
for mon in props.MONITOR_CHOICES:
    calls.append(lambda m=mon: props.monitor_label(m))
for kind, specs in props.PROP_TABLE.items():
    for spec in specs:
        calls.append(lambda s=spec, k=kind: s.label)
        calls.append(lambda s=spec, k=kind: props.format_value(s, k, None))
for msg in keymap.invalid_key_warnings(Config(
        sr_sources=[{"name": "X", "key": "Delete"}],
        record={"pause_hotkey": "Q"})):
    calls.append(lambda m=msg: m)
for i, fn in enumerate(calls):
    try:
        collect(f"読み上げ関数 {i}", fn())
    except Exception as exc:  # noqa: BLE001
        check(f"読み上げ関数 {i} が例外を出さない", False, repr(exc))
for i, text in enumerate(said):
    collect(f"読み上げ {i}", text)

frame.Destroy()

# --- 判定 ---
bad = [(w, t) for w, t in texts if JP.search(t) and t not in BILINGUAL]
check(f"英語の画面と読み上げに日本語が無い（{len(texts)} 件を調べた）",
      not bad, "; ".join(f"{w}: {t}" for w, t in bad[:10]))
check("検査が日本語を見つけられる",
      bool(JP.search("Mic ミュート中")) and not JP.search("Mic muted"))
check("数を読む単位の単数・複数",
      sf.timecode_to_speech("01:01:02") == "1 hour 1 minute 2 seconds",
      sf.timecode_to_speech("01:01:02"))
check("デシベルは記号を読ませない",
      sf.fmt_db(-18.4) == "minus 18 decibels", sf.fmt_db(-18.4))

_after = (io.open(CONFIG_PATH, "rb").read()
          if os.path.exists(CONFIG_PATH) else None)
check("設定ファイルに書き込んでいない", _before == _after)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
