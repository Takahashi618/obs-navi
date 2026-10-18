# -*- coding: utf-8 -*-
"""commands モジュールのテスト（FakeClient で ReqClient を差し替え）。"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import commands, speech_format  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


class FakeClient:
    """ReqClient 互換の最小フェイク。"""

    def __init__(self) -> None:
        self.muted: dict[str, bool] = {"マイク": False, "ゲーム": True}
        # 実測値を模す。OBSはfloat32由来の誤差込みで返す
        self.volumes: dict[str, float] = {
            "マイク": 5.099999904632568, "ゲーム": 0.0}
        self.filter_calls: list[tuple] = []
        self.item_calls: list[tuple] = []
        self.vcam = False
        self.record_pause_calls = 0
        self.replay_available = True
        self.replay_active = False
        self.replay_saved = 0
        self.scene = "ゲーム画面"
        # 録画まわり
        self.recording = False
        self.record_paused = False
        self.record_timecode = "00:00:00"
        self.chapters: list = []
        self.chapter_supported = True
        self.record_directory = "F:/Videos"
        self.last_replay = "F:/Videos/Replay.mp4"
        # 実際に動いている録画出力の種別（設定のフォーマットとは別物）
        self.record_output_kind = "ffmpeg_muxer"
        # フィルター。(ソース名, フィルター名) → 種別・設定など
        self.filters_state: dict = {}
        self.filter_defaults = {
            "noise_suppress_filter_v2": {"method": "rnnoise",
                                         "suppress_level": -30},
            "compressor_filter": {"ratio": 10.0, "threshold": -18.0,
                                  "sidechain_source": "none"},
        }
        self.filter_overlays: list = []
        # カメラ。★ボタンでしか変わらない（設定を書いても変わらない）
        self.camera_active = True
        self.button_presses: list = []
        # プロファイル設定（簡易出力・プレーンMP4。実機の実測値に合わせる）
        self.profile: dict[tuple[str, str], str] = {
            ("Output", "Mode"): "Simple",
            ("SimpleOutput", "RecFormat2"): "mp4",
            ("SimpleOutput", "RecEncoder"): "x264",
            ("SimpleOutput", "RecQuality"): "Small",
            ("SimpleOutput", "RecTracks"): "1",
            ("Output", "FilenameFormatting"): "%CCYY-%MM-%DD %hh-%mm-%ss",
        }

    def get_version(self):
        return SimpleNamespace(obs_version="32.1.2")

    def get_stream_status(self):
        return SimpleNamespace(output_active=True, output_timecode="00:05:00")

    def get_record_status(self):
        return SimpleNamespace(
            output_active=self.recording, output_paused=self.record_paused,
            output_timecode=self.record_timecode)

    def get_scene_list(self):
        # OBSは上段が末尾。ここでは [下, 上] の並びで返す
        return SimpleNamespace(
            scenes=[
                {"sceneName": "待機画面"},
                {"sceneName": "ゲーム画面"},
            ],
            current_program_scene_name="ゲーム画面",
        )

    def get_input_list(self, kind=None):
        return SimpleNamespace(inputs=[
            {"inputName": "マイク", "inputKind": "wasapi_input_capture"},
            {"inputName": "ゲーム", "inputKind": "wasapi_process_output"},
            {"inputName": "映像", "inputKind": "monitor_capture"},
        ])

    def get_input_mute(self, name):
        if name not in self.muted:
            raise RuntimeError("no audio")  # 映像入力など
        return SimpleNamespace(input_muted=self.muted[name])

    def toggle_input_mute(self, name):
        self.muted[name] = not self.muted[name]

    def set_input_mute(self, name, muted):
        self.muted[name] = muted

    def get_input_volume(self, name):
        if name not in self.volumes:
            raise RuntimeError("no audio")
        return SimpleNamespace(
            input_volume_db=self.volumes[name], input_volume_mul=1.0)

    def set_input_volume(self, name, vol_mul=None, vol_db=None):
        if vol_db is not None:
            self.volumes[name] = vol_db

    def get_source_filter_list(self, name):
        # マイクだけ2つフィルターを持つ。他は空。
        if name == "マイク":
            return SimpleNamespace(filters=[
                {"filterName": "ノイズ抑制", "filterKind": "noise_suppress_filter",
                 "filterEnabled": True, "filterIndex": 0},
                {"filterName": "コンプ", "filterKind": "compressor_filter",
                 "filterEnabled": False, "filterIndex": 1},
            ])
        return SimpleNamespace(filters=[])

    def set_source_filter_enabled(self, source_name, filter_name, enabled):
        self.filter_calls.append((source_name, filter_name, enabled))

    def get_scene_item_list(self, name):
        # index が大きいほど画面の手前。OBSの生の並びは index 昇順で返る。
        return SimpleNamespace(scene_items=[
            {"sceneItemId": 2, "sourceName": "ゲームキャプチャ",
             "sceneItemEnabled": True, "inputKind": "game_capture",
             "sceneItemIndex": 0},
            {"sceneItemId": 5, "sourceName": "カメラ",
             "sceneItemEnabled": False, "inputKind": "dshow_input",
             "sceneItemIndex": 1},
        ])

    def set_scene_item_enabled(self, scene_name, item_id, enabled):
        self.item_calls.append((scene_name, item_id, enabled))

    def get_stats(self):
        return SimpleNamespace(
            cpu_usage=12.5, active_fps=60.0, available_disk_space=2048.0,
            memory_usage=150.0, render_total_frames=1000,
            render_skipped_frames=3, output_total_frames=0,
            output_skipped_frames=0)

    def get_virtual_cam_status(self):
        return SimpleNamespace(output_active=self.vcam)

    def toggle_virtual_cam(self):
        self.vcam = not self.vcam

    def toggle_record_pause(self):
        self.record_pause_calls += 1

    def get_replay_buffer_status(self):
        if not self.replay_available:
            raise RuntimeError("Replay buffer is not available.")
        return SimpleNamespace(output_active=self.replay_active)

    def start_replay_buffer(self):
        if not self.replay_available:
            raise RuntimeError("Replay buffer is not available.")
        self.replay_active = True

    def save_replay_buffer(self):
        self.replay_saved += 1

    def set_current_program_scene(self, name):
        self.scene = name

    # --- 録画 ---
    def create_record_chapter(self, chapter_name=None):
        if not self.chapter_supported:
            # OBSは対応フォーマットでないと拒否する
            raise RuntimeError("Unsupported: chapters need hybrid MP4")
        self.chapters.append(chapter_name)

    def get_record_directory(self):
        return SimpleNamespace(record_directory=self.record_directory)

    def get_profile_parameter(self, category, name):
        value = self.profile.get((category, name))
        if value is None:
            # OBSは未設定のとき parameterValue が None で既定値を別に返す
            return SimpleNamespace(
                parameter_value=None, default_parameter_value="既定")
        return SimpleNamespace(
            parameter_value=value, default_parameter_value="既定")

    def set_profile_parameter(self, category, name, value):
        self.profile[(category, name)] = value

    def get_last_replay_buffer_replay(self):
        return SimpleNamespace(saved_replay_path=self.last_replay)

    # --- フィルター ---
    def get_source_filter(self, source_name, filter_name):
        info = self.filters_state.get((source_name, filter_name))
        if info is None:
            raise RuntimeError("No filter was found")
        return SimpleNamespace(
            filter_kind=info["kind"],
            filter_index=info["index"],
            filter_enabled=info["enabled"],
            filter_settings=dict(info["settings"]))

    def get_source_filter_default_settings(self, kind):
        return SimpleNamespace(
            default_filter_settings=dict(self.filter_defaults.get(kind, {})))

    def set_source_filter_settings(self, source_name, filter_name,
                                   settings, overlay=None):
        info = self.filters_state.get((source_name, filter_name))
        if info is None:
            raise RuntimeError("No filter was found")
        self.filter_overlays.append(overlay)
        if overlay:
            info["settings"].update(settings)
        else:
            info["settings"] = dict(settings)

    def create_source_filter(self, source_name, filter_name, filter_kind,
                             filter_settings=None):
        if (source_name, filter_name) in self.filters_state:
            raise RuntimeError("already exists")
        self.filters_state[(source_name, filter_name)] = {
            "kind": filter_kind, "index": len(self.filters_state),
            "enabled": True, "settings": dict(filter_settings or {})}

    def remove_source_filter(self, source_name, filter_name):
        self.filters_state.pop((source_name, filter_name), None)

    def set_source_filter_index(self, source_name, filter_name, filter_index):
        info = self.filters_state.get((source_name, filter_name))
        if info is not None:
            info["index"] = filter_index

    # --- カメラ ---
    def press_input_properties_button(self, input_name, prop_name):
        self.button_presses.append((input_name, prop_name))
        if prop_name == "activate":
            # 実機と同じく押すたびに反転する（値は指定できない）
            self.camera_active = not self.camera_active

    def get_input_settings(self, name):
        if name == "カメラ":
            return SimpleNamespace(
                input_kind="dshow_input",
                input_settings={"active": self.camera_active,
                                "video_device_id": "c922"})
        return SimpleNamespace(input_kind="", input_settings={})

    def get_input_default_settings(self, kind):
        if kind == "dshow_input":
            return SimpleNamespace(default_input_settings={"active": True})
        return SimpleNamespace(default_input_settings={})

    def get_input_properties_list_property_items(self, name, prop):
        if prop == "video_device_id":
            return SimpleNamespace(property_items=[
                {"itemName": "c922 Pro Stream Webcam", "itemValue": "c922",
                 "itemEnabled": True},
                {"itemName": "AVerMedia GC551", "itemValue": "gc551",
                 "itemEnabled": True},
                {"itemName": "OBS Virtual Camera", "itemValue": "vcam",
                 "itemEnabled": True},
            ])
        return SimpleNamespace(property_items=[])

    def get_output_list(self):
        # 実測の応答をそのまま模す（簡易出力・従来のffmpeg muxer）
        return SimpleNamespace(outputs=[
            {"outputName": "simple_file_output",
             "outputKind": self.record_output_kind, "outputActive": False},
            {"outputName": "virtualcam_output",
             "outputKind": "virtualcam_output", "outputActive": False},
        ])


def test_fetch_snapshot() -> None:
    c = FakeClient()
    snap = commands.fetch_snapshot(c)
    check("接続フラグ", snap.connected is True)
    check("バージョン", snap.obs_version == "32.1.2", snap.obs_version)
    check("配信中", snap.streaming is True)
    check("録画停止", snap.recording is False)
    check("現在シーン", snap.current_scene == "ゲーム画面", snap.current_scene)
    # reverse されて [上, 下] になる
    check("シーン並び反転", snap.scenes == ["ゲーム画面", "待機画面"],
          str(snap.scenes))


def test_audio_inputs_only() -> None:
    c = FakeClient()
    snap = commands.fetch_snapshot(c)
    names = [i.name for i in snap.audio_inputs]
    check("音声入力だけ抽出", names == ["マイク", "ゲーム"], str(names))
    game = snap.input_by_name("ゲーム")
    check("ミュート状態を反映", game is not None and game.muted is True)


def test_toggle_and_set_mute() -> None:
    c = FakeClient()
    commands.toggle_mute(c, "マイク")
    check("トグルで反転", c.muted["マイク"] is True)
    commands.set_mute(c, "マイク", False)
    check("明示設定", c.muted["マイク"] is False)


def test_scene_and_outputs() -> None:
    c = FakeClient()
    commands.set_scene(c, "待機画面")
    check("シーン設定を反映", c.scene == "待機画面", c.scene)


def test_snapshot_includes_volume() -> None:
    c = FakeClient()
    snap = commands.fetch_snapshot(c)
    mic = snap.input_by_name("マイク")
    check("スナップショットに音量が入る",
          mic is not None and mic.volume_db == 5.099999904632568,
          str(mic.volume_db if mic else None))


def test_fetch_and_set_volume() -> None:
    c = FakeClient()
    check("音量を取得", commands.fetch_volume_db(c, "ゲーム") == 0.0,
          str(commands.fetch_volume_db(c, "ゲーム")))
    commands.set_volume_db(c, "ゲーム", -6.0)
    check("音量を設定", c.volumes["ゲーム"] == -6.0, str(c.volumes["ゲーム"]))
    check("設定した値が読み戻せる",
          commands.fetch_volume_db(c, "ゲーム") == -6.0)


def test_fetch_volume_missing_is_none() -> None:
    """音量を取れない入力でも失敗にせず None を返すこと。

    取れないだけで他の操作（ミュート等）は続けられるべきなので、
    ここで例外を上げるとアプリ全体が止まってしまう。
    """
    c = FakeClient()
    check("音量を持たない入力はNone",
          commands.fetch_volume_db(c, "映像") is None,
          str(commands.fetch_volume_db(c, "映像")))


def test_snapshot_without_volume_api() -> None:
    """get_input_volume を持たない相手でもスナップショットが壊れないこと。"""

    class NoVolumeClient(FakeClient):
        def get_input_volume(self, name):
            raise AttributeError("この相手は音量APIを持たない")

    c = NoVolumeClient()
    snap = commands.fetch_snapshot(c)
    names = [i.name for i in snap.audio_inputs]
    check("音量が取れなくても入力一覧は出る", names == ["マイク", "ゲーム"],
          str(names))
    mic = snap.input_by_name("マイク")
    check("音量はNoneになるだけ", mic is not None and mic.volume_db is None,
          str(mic.volume_db if mic else "no mic"))


def test_fetch_source_filters() -> None:
    c = FakeClient()
    filters = commands.fetch_source_filters(c, "マイク")
    check("フィルター2つ取得", len(filters) == 2, str(len(filters)))
    check("1つ目の名前", filters[0].name == "ノイズ抑制", filters[0].name)
    check("1つ目は有効", filters[0].enabled is True)
    check("2つ目は無効", filters[1].enabled is False)
    check("種別も取れる", filters[0].kind == "noise_suppress_filter",
          filters[0].kind)
    check("index順", [f.index for f in filters] == [0, 1],
          str([f.index for f in filters]))


def test_fetch_filters_empty_and_safe() -> None:
    c = FakeClient()
    check("フィルター無しは空リスト",
          commands.fetch_source_filters(c, "ゲーム") == [])
    check("空の名前は空リスト", commands.fetch_source_filters(c, "") == [])

    class Boom(FakeClient):
        def get_source_filter_list(self, name):
            raise RuntimeError("失敗")

    check("取得例外でも空リスト（落ちない）",
          commands.fetch_source_filters(Boom(), "マイク") == [])


def test_set_filter_enabled() -> None:
    c = FakeClient()
    commands.set_filter_enabled(c, "マイク", "コンプ", True)
    check("設定が呼ばれる", c.filter_calls == [("マイク", "コンプ", True)],
          str(c.filter_calls))


def test_fetch_scene_items() -> None:
    c = FakeClient()
    items = commands.fetch_scene_items(c, "シーン")
    check("2つ取得", len(items) == 2, str(len(items)))
    # index 降順（手前が先頭）＝ カメラ(index1) が先、ゲームキャプチャ(index0) が後
    check("手前が先頭", items[0].name == "カメラ", items[0].name)
    check("id が整数で取れる", items[0].item_id == 5, str(items[0].item_id))
    check("可視性を反映", items[0].enabled is False and items[1].enabled is True,
          str([i.enabled for i in items]))


def test_fetch_scene_items_safe() -> None:
    c = FakeClient()
    check("空シーン名は空リスト", commands.fetch_scene_items(c, "") == [])

    class Boom(FakeClient):
        def get_scene_item_list(self, name):
            raise RuntimeError("失敗")

    check("取得例外でも空リスト", commands.fetch_scene_items(Boom(), "シーン") == [])


def test_checked_fetchers_separate_empty_from_failure() -> None:
    """★「空」と「届かなかった」を呼ぶ側が区別できること。

    空リストで潰すと、接続が切れているのに「ソースが見つかりません」
    「フィルターが見つかりません」と読み上げ、一覧まで消してしまう。
    利用者は原因を取り違えて探し続けることになる。
    """
    class Resp:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Empty:
        def get_scene_item_list(self, name):
            return Resp(scene_items=[])

        def get_source_filter_list(self, name):
            return Resp(filters=[])

    class Boom:
        def get_scene_item_list(self, name):
            raise RuntimeError("切断")

        def get_source_filter_list(self, name):
            raise RuntimeError("切断")

    ok, items = commands.fetch_scene_items_checked(Empty(), "シーン")
    check("空のシーンは成功で空", ok is True and items == [], str(items))
    ok, items = commands.fetch_scene_items_checked(Boom(), "シーン")
    check("通信の失敗は失敗として返す", ok is False and items == [], str(items))
    ok, found = commands.fetch_source_filters_checked(Empty(), "マイク")
    check("フィルター無しは成功で空", ok is True and found == [], str(found))
    ok, found = commands.fetch_source_filters_checked(Boom(), "マイク")
    check("フィルターの通信失敗も伝える", ok is False, str(found))
    check("シーン名が空なら成功で空",
          commands.fetch_scene_items_checked(Empty(), "") == (True, []))
    # 旧来の呼び名は今までどおり一覧だけを返す
    check("旧来の呼び名は一覧を返す",
          commands.fetch_scene_items(Boom(), "シーン") == []
          and commands.fetch_source_filters(Boom(), "マイク") == [])


def test_set_scene_item_enabled() -> None:
    c = FakeClient()
    commands.set_scene_item_enabled(c, "シーン", 5, True)
    check("設定が呼ばれる", c.item_calls == [("シーン", 5, True)],
          str(c.item_calls))


def test_fetch_stats() -> None:
    c = FakeClient()
    s = commands.fetch_stats(c)
    check("CPUが入る", s.get("cpu") == 12.5, str(s.get("cpu")))
    check("空き容量が入る", s.get("disk_free_mb") == 2048.0)
    check("描画スキップが入る", s.get("render_skipped") == 3)


def test_fetch_stats_safe() -> None:
    class Boom(FakeClient):
        def get_stats(self):
            raise RuntimeError("失敗")

    check("取得例外でも空辞書", commands.fetch_stats(Boom()) == {})


def test_toggle_virtual_cam() -> None:
    c = FakeClient()
    check("初期はオフ", commands.is_virtual_cam_active(c) is False)
    commands.toggle_virtual_cam(c)
    check("トグルでオン", commands.is_virtual_cam_active(c) is True)


def test_toggle_record_pause() -> None:
    c = FakeClient()
    commands.toggle_record_pause(c)
    check("一時停止トグルが呼ばれる", c.record_pause_calls == 1)


def test_save_replay_active_saves() -> None:
    c = FakeClient()
    c.replay_active = True
    commands.save_replay_buffer(c)
    check("起動済みなら保存が呼ばれる", c.replay_saved == 1)


def test_save_replay_inactive_starts_only() -> None:
    """未起動なら起動だけ行い、保存はしないこと。

    起動は非同期なので、直後に保存を投げても失敗するか中身ほぼ0秒の
    リプレイになる。ReplayBufferStarting で「起動した。待ってからもう一度」
    の案内に回す。
    """
    c = FakeClient()
    c.replay_active = False
    raised = False
    try:
        commands.save_replay_buffer(c)
    except commands.ReplayBufferStarting:
        raised = True
    check("未起動なら ReplayBufferStarting", raised)
    check("バッファは起動されている", c.replay_active is True)
    check("起動直後は保存しない", c.replay_saved == 0)


def test_save_replay_unavailable() -> None:
    c = FakeClient()
    c.replay_available = False
    raised = False
    try:
        commands.save_replay_buffer(c)
    except commands.ReplayBufferUnavailable:
        raised = True
    check("無効なら ReplayBufferUnavailable", raised)
    check("保存は呼ばれない", c.replay_saved == 0)


# ------------------------------------------------------------
# 録画
# ------------------------------------------------------------
def test_snapshot_record_paused() -> None:
    c = FakeClient()
    c.recording = True
    c.record_paused = True
    c.record_timecode = "00:10:05"
    snap = commands.fetch_snapshot(c)
    check("録画中を反映", snap.recording is True)
    # ★一時停止でも output_active は True のまま。両方読まないと
    #   「録れているつもりで止まっている」を区別できない
    check("一時停止を反映", snap.record_paused is True)
    check("タイムコードを反映", snap.record_timecode == "00:10:05")


def test_snapshot_paused_defaults_false() -> None:
    """output_paused を返さない相手でも壊れないこと。"""

    class OldClient(FakeClient):
        def get_record_status(self):
            return SimpleNamespace(
                output_active=True, output_timecode="00:01:00")

    snap = commands.fetch_snapshot(OldClient())
    check("一時停止フラグが無ければ False", snap.record_paused is False)


def test_fetch_record_status() -> None:
    c = FakeClient()
    c.recording = True
    c.record_paused = True
    c.record_timecode = "01:02:03"
    check("状態を3つ返す",
          commands.fetch_record_status(c) == (True, True, "01:02:03"),
          str(commands.fetch_record_status(c)))


def test_fetch_record_status_safe() -> None:
    """取れなくても例外にせず既定値を返すこと（呼び出し側で分岐する）。"""

    class BrokenClient(FakeClient):
        def get_record_status(self):
            raise RuntimeError("切断")

    check("失敗時は停止扱い",
          commands.fetch_record_status(BrokenClient())
          == (False, False, "00:00:00"))


def test_create_record_chapter() -> None:
    c = FakeClient()
    commands.create_record_chapter(c, "01 00:12:34")
    check("チャプター名を渡す", c.chapters == ["01 00:12:34"], str(c.chapters))
    commands.create_record_chapter(c)
    # 名前が空なら None を渡す（OBS側で自動命名させる）
    check("空名は None にする", c.chapters[-1] is None, str(c.chapters))


def test_create_record_chapter_unsupported() -> None:
    c = FakeClient()
    c.chapter_supported = False
    raised = False
    try:
        commands.create_record_chapter(c, "01")
    except commands.RecordChapterUnsupported:
        raised = True
    # ★UI側が「フォーマットを変えてください」と案内できるよう、
    #   生の例外ではなく専用の型へ変換すること
    check("非対応なら RecordChapterUnsupported", raised)


def test_fetch_record_directory() -> None:
    c = FakeClient()
    check("保存先を取得",
          commands.fetch_record_directory(c) == "F:/Videos",
          commands.fetch_record_directory(c))

    class BrokenClient(FakeClient):
        def get_record_directory(self):
            raise RuntimeError("切断")

    check("取れなければ空文字",
          commands.fetch_record_directory(BrokenClient()) == "")


def test_fetch_profile_parameter() -> None:
    c = FakeClient()
    check("値を取得",
          commands.fetch_profile_parameter(c, "SimpleOutput", "RecFormat2")
          == "mp4")
    # 未設定のときは既定値へ落とす（設定ファイルに書かれていない＝既定）
    check("未設定なら既定値",
          commands.fetch_profile_parameter(c, "SimpleOutput", "無い項目")
          == "既定")

    class BrokenClient(FakeClient):
        def get_profile_parameter(self, category, name):
            raise RuntimeError("切断")

    check("取れなければ空文字",
          commands.fetch_profile_parameter(BrokenClient(), "A", "B") == "")


def test_apply_profile_parameter() -> None:
    c = FakeClient()
    commands.apply_profile_parameter(c, "SimpleOutput", "RecFormat2",
                                     "hybrid_mp4")
    check("書き換わる",
          c.profile[("SimpleOutput", "RecFormat2")] == "hybrid_mp4")


def test_fetch_record_settings_simple() -> None:
    c = FakeClient()
    s = commands.fetch_record_settings(c)
    check("簡易出力と判定", s["section"] == "SimpleOutput", s["section"])
    check("保存先", s["directory"] == "F:/Videos", s["directory"])
    check("フォーマット", s["format"] == "mp4", s["format"])
    check("エンコーダ", s["encoder"] == "x264", s["encoder"])
    # 品質は簡易出力にだけある項目
    check("品質を含む", s.get("quality") == "Small", str(s.get("quality")))
    check("空き容量を含む", s.get("disk_free_mb") == 2048.0,
          str(s.get("disk_free_mb")))


def test_fetch_record_settings_advanced() -> None:
    c = FakeClient()
    c.profile[("Output", "Mode")] = "Advanced"
    c.profile[("AdvOut", "RecFormat2")] = "hybrid_mp4"
    c.profile[("AdvOut", "RecEncoder")] = "jim_nvenc"
    s = commands.fetch_record_settings(c)
    # ★詳細出力では別セクションを見る。同じキー名で別の場所にあるので、
    #   モードを見ずに引くと簡易出力の値を読んでしまう
    check("詳細出力と判定", s["section"] == "AdvOut", s["section"])
    check("詳細側のフォーマット", s["format"] == "hybrid_mp4", s["format"])
    check("詳細側のエンコーダ", s["encoder"] == "jim_nvenc", s["encoder"])
    check("品質は含まない", "quality" not in s, str(s.keys()))


def test_fetch_record_output_kind() -> None:
    c = FakeClient()
    check("実際の出力種別を取る",
          commands.fetch_record_output_kind(c) == "ffmpeg_muxer",
          commands.fetch_record_output_kind(c))
    c.record_output_kind = "mp4_output"
    check("ハイブリッドなら mp4_output",
          commands.fetch_record_output_kind(c) == "mp4_output")

    class BrokenClient(FakeClient):
        def get_output_list(self):
            raise RuntimeError("切断")

    check("取れなければ空文字",
          commands.fetch_record_output_kind(BrokenClient()) == "")


def test_record_settings_detects_mismatch() -> None:
    """★設定と実態のずれを設定辞書の中で見分けられること。

    録画フォーマットを変えてもOBSを再起動するまで出力は作り直されない
    （実測）。両方を持って初めて「再起動が要る」と言える。
    """
    c = FakeClient()
    c.profile[("SimpleOutput", "RecFormat2")] = "hybrid_mp4"
    c.record_output_kind = "ffmpeg_muxer"  # まだ再起動していない
    s = commands.fetch_record_settings(c)
    check("設定は対応フォーマット", s["format"] == "hybrid_mp4")
    check("実態は従来の出力", s["output_kind"] == "ffmpeg_muxer")
    check("読み上げは再起動を促す",
          "再起動" in speech_format.record_settings_summary(s),
          speech_format.record_settings_summary(s))
    # 再起動後は素直に使えると言う
    c.record_output_kind = "mp4_output"
    s2 = commands.fetch_record_settings(c)
    check("反映後は使えると言う",
          "チャプターが使えます" in speech_format.record_settings_summary(s2),
          speech_format.record_settings_summary(s2))


def test_fetch_last_replay_path() -> None:
    c = FakeClient()
    check("最後のリプレイを取得",
          commands.fetch_last_replay_path(c) == "F:/Videos/Replay.mp4")

    class BrokenClient(FakeClient):
        def get_last_replay_buffer_replay(self):
            raise RuntimeError("まだ保存していない")

    check("取れなければ空文字",
          commands.fetch_last_replay_path(BrokenClient()) == "")


# ------------------------------------------------------------
# フィルターの設定
# ------------------------------------------------------------
def test_filter_settings_roundtrip() -> None:
    c = FakeClient()
    commands.create_filter(c, "マイク", "ノイズ抑制",
                           "noise_suppress_filter_v2")
    check("種別を取れる",
          commands.fetch_filter_kind(c, "マイク", "ノイズ抑制")
          == "noise_suppress_filter_v2")
    # ★作った直後は空。既定とのマージが要る（実機で確認した挙動）
    check("作った直後の設定は空",
          commands.fetch_filter_settings(c, "マイク", "ノイズ抑制") == {})
    kind, merged = commands.fetch_merged_filter_settings(
        c, "マイク", "ノイズ抑制")
    check("マージすると既定が読める",
          merged.get("method") == "rnnoise" and merged.get("suppress_level") == -30,
          str(merged))
    check("マージで種別も返る", kind == "noise_suppress_filter_v2")

    commands.apply_filter_settings(c, "マイク", "ノイズ抑制",
                                   {"method": "speex"})
    _k, after = commands.fetch_merged_filter_settings(c, "マイク", "ノイズ抑制")
    check("設定が変わる", after.get("method") == "speex", str(after))
    # ★overlay=True でないと、指定しなかった設定が既定へ戻ってしまう
    check("常に上書きマージで投げる",
          c.filter_overlays and all(o is True for o in c.filter_overlays),
          str(c.filter_overlays))
    check("指定しなかった設定は残る",
          after.get("suppress_level") == -30, str(after))


def test_filter_settings_safe_when_missing() -> None:
    """無いフィルターを読んでも例外にしないこと（一覧が古いときに起きる）。"""
    c = FakeClient()
    check("種別は空文字", commands.fetch_filter_kind(c, "マイク", "無い") == "")
    check("設定は空辞書",
          commands.fetch_filter_settings(c, "マイク", "無い") == {})
    kind, merged = commands.fetch_merged_filter_settings(c, "マイク", "無い")
    check("マージも空", kind == "" and merged == {})


def test_filter_create_and_remove() -> None:
    c = FakeClient()
    commands.create_filter(c, "マイク", "コンプ", "compressor_filter")
    check("作れる", ("マイク", "コンプ") in c.filters_state)
    commands.set_filter_index(c, "マイク", "コンプ", 0)
    check("並び替えできる", c.filters_state[("マイク", "コンプ")]["index"] == 0)
    commands.remove_filter(c, "マイク", "コンプ")
    check("消せる", ("マイク", "コンプ") not in c.filters_state)


def test_filter_default_settings() -> None:
    c = FakeClient()
    d = commands.fetch_filter_default_settings(c, "compressor_filter")
    check("既定設定を取れる", d.get("ratio") == 10.0, str(d))
    check("未知の種別は空", commands.fetch_filter_default_settings(c, "なし") == {})
    check("空文字は空", commands.fetch_filter_default_settings(c, "") == {})


# ------------------------------------------------------------
# カメラ
# ------------------------------------------------------------
def test_camera_toggle_uses_button() -> None:
    """★カメラの切り替えは必ずボタンで行うこと。

    設定として active を書いてもデバイスは止まらない（実機で確認）。
    ここで設定書き込みに退行すると「止めたのに撮られている」が起きる。
    """
    c = FakeClient()
    commands.toggle_camera_active(c, "カメラ")
    check("ボタンを押している", c.button_presses == [("カメラ", "activate")],
          str(c.button_presses))
    check("状態が反転する", c.camera_active is False)
    commands.toggle_camera_active(c, "カメラ")
    check("もう一度押すと戻る", c.camera_active is True)


def test_camera_state_reads_reality() -> None:
    c = FakeClient()
    state = commands.fetch_camera_state(c, "カメラ")
    check("動作中を読む", state.active is True)
    check("機材名を引く", state.device == "c922 Pro Stream Webcam",
          state.device)
    # ボタンで止めたあとは、読み直すと止まっていること
    commands.toggle_camera_active(c, "カメラ")
    state2 = commands.fetch_camera_state(c, "カメラ")
    check("停止を読む", state2.active is False)


def test_unused_camera_devices() -> None:
    c = FakeClient()
    got = commands.fetch_unused_camera_devices(c, ["カメラ"])
    # カメラは c922 を使っているので、残りは GC551（仮想カメラは除く）
    check("使っていない機材を挙げる", "AVerMedia GC551" in got, str(got))
    check("使っている機材は挙げない",
          not any("c922" in g for g in got), str(got))
    check("仮想カメラは挙げない",
          not any("Virtual" in g for g in got), str(got))
    check("カメラが無ければ空", commands.fetch_unused_camera_devices(c, []) == [])


def run() -> tuple[int, int]:
    for fn in (
        test_fetch_snapshot,
        test_audio_inputs_only,
        test_toggle_and_set_mute,
        test_scene_and_outputs,
        test_snapshot_includes_volume,
        test_fetch_and_set_volume,
        test_fetch_volume_missing_is_none,
        test_snapshot_without_volume_api,
        test_fetch_source_filters,
        test_fetch_filters_empty_and_safe,
        test_set_filter_enabled,
        test_fetch_scene_items,
        test_fetch_scene_items_safe,
        test_checked_fetchers_separate_empty_from_failure,
        test_set_scene_item_enabled,
        test_fetch_stats,
        test_fetch_stats_safe,
        test_toggle_virtual_cam,
        test_toggle_record_pause,
        test_save_replay_active_saves,
        test_save_replay_inactive_starts_only,
        test_save_replay_unavailable,
        test_snapshot_record_paused,
        test_snapshot_paused_defaults_false,
        test_fetch_record_status,
        test_fetch_record_status_safe,
        test_create_record_chapter,
        test_create_record_chapter_unsupported,
        test_fetch_record_directory,
        test_fetch_profile_parameter,
        test_apply_profile_parameter,
        test_fetch_record_settings_simple,
        test_fetch_record_settings_advanced,
        test_fetch_record_output_kind,
        test_record_settings_detects_mismatch,
        test_fetch_last_replay_path,
        test_filter_settings_roundtrip,
        test_filter_settings_safe_when_missing,
        test_filter_create_and_remove,
        test_filter_default_settings,
        test_camera_toggle_uses_button,
        test_camera_state_reads_reality,
        test_unused_camera_devices,
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
    print(f"commands: {p} passed, {f} failed")
