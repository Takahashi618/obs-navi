# -*- coding: utf-8 -*-
"""setup モジュールの純関数テスト（実機の OBS から取得したデータを使用）。"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import setup  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# 実機の OBS から取得した window プロパティ項目（抜粋）
SAMPLE_ITEMS = [
    {"itemEnabled": False, "itemName": "[Diablo IV.exe]: ディアブロ IV",
     "itemValue": "ディアブロ IV:Diablo IV Main Window Class:Diablo IV.exe"},
    {"itemEnabled": True, "itemName": "[SearchHost.exe]: 検索",
     "itemValue": "検索:Windows.UI.Core.CoreWindow:SearchHost.exe"},
    {"itemEnabled": True, "itemName": "[python.exe]: OBSナビ 0.1.0",
     "itemValue": "OBSナビ 0.1.0:wxWindowNR:python.exe"},
    {"itemEnabled": True, "itemName": "[PCTalker.exe]: 音声基本設定",
     "itemValue": "音声基本設定:#2232770:PCTalker.exe"},
    # タイトルに ':' がエスケープされて含まれる例
    {"itemEnabled": True,
     "itemName": "[WindowsTerminal.exe]: C:\\...\\python.exe",
     "itemValue": "C#3A\\Users\\user\\...\\python.exe:CASCADIA:WindowsTerminal.exe"},
]


def test_parse_window_exe() -> None:
    check("PCTalkerを抽出",
          setup.parse_window_exe("音声基本設定:#2232770:PCTalker.exe")
          == "PCTalker.exe")
    check("エスケープ済みタイトルでも実行ファイルを抽出",
          setup.parse_window_exe(
              "C#3A\\Users\\x\\python.exe:CASCADIA:WindowsTerminal.exe")
          == "WindowsTerminal.exe")
    check("空文字は空", setup.parse_window_exe("") == "")


def test_pick_process_window() -> None:
    v = setup.pick_process_window(SAMPLE_ITEMS, "PCTalker.exe")
    check("PCTalkerのwindow値を選ぶ",
          v == "音声基本設定:#2232770:PCTalker.exe", str(v))
    # 大文字小文字を無視
    v2 = setup.pick_process_window(SAMPLE_ITEMS, "pctalker.EXE")
    check("大文字小文字を無視", v2 == "音声基本設定:#2232770:PCTalker.exe", str(v2))
    # 存在しない実行ファイル
    v3 = setup.pick_process_window(SAMPLE_ITEMS, "nvda.exe")
    check("無ければNone", v3 is None, str(v3))
    # 空リスト
    check("空リストはNone", setup.pick_process_window([], "PCTalker.exe") is None)


class FakeClient:
    """create_sr_audio_input の一連の呼び出しを記録するフェイク。"""

    def __init__(self, found: bool = True) -> None:
        self.created: list[tuple] = []
        self.settings: dict[str, dict] = {}
        self.muted: dict[str, bool] = {}
        self.removed: list[str] = []
        self._found = found
        self._inputs: list[dict] = []

    def create_input(self, sceneName, inputName, inputKind,
                     inputSettings, sceneItemEnabled):
        self.created.append(
            (sceneName, inputName, inputKind, sceneItemEnabled))
        self._inputs.append({"inputName": inputName, "inputKind": inputKind})

    def remove_input(self, name):
        self.removed.append(name)
        self._inputs = [
            it for it in self._inputs if it.get("inputName") != name]

    def get_input_properties_list_property_items(self, input_name, prop_name):
        items = list(SAMPLE_ITEMS) if self._found else [
            {"itemValue": "検索:X:SearchHost.exe"}]
        return SimpleNamespace(property_items=items)

    def set_input_settings(self, name, settings, overlay):
        self.settings[name] = settings

    def set_input_mute(self, name, muted):
        self.muted[name] = muted

    def set_input_name(self, old_name, new_name):
        for it in self._inputs:
            if it.get("inputName") == old_name:
                it["inputName"] = new_name
        self.renamed = getattr(self, "renamed", [])
        self.renamed.append((old_name, new_name))

    def get_input_list(self):
        return SimpleNamespace(inputs=list(self._inputs))


def test_create_sets_target_and_mutes() -> None:
    c = FakeClient(found=True)
    value = setup.create_sr_audio_input(
        c, "シーン", "スクリーンリーダー音声", "PCTalker.exe")
    check("window値を返す", value == "音声基本設定:#2232770:PCTalker.exe",
          str(value))
    check("入力を作成した", len(c.created) == 1, str(c.created))
    check("種類が正しい", c.created[0][2] == setup.APP_AUDIO_KIND,
          c.created[0][2])
    s = c.settings.get("スクリーンリーダー音声", {})
    check("windowを設定", s.get("window") == "音声基本設定:#2232770:PCTalker.exe",
          str(s))
    check("priority=2を設定", s.get("priority") == 2, str(s))
    check("初期ミュート", c.muted.get("スクリーンリーダー音声") is True,
          str(c.muted))


def test_create_when_process_missing() -> None:
    # 既定 (remove_if_not_found=True): 未ターゲットなら作りかけを削除
    c = FakeClient(found=False)
    value = setup.create_sr_audio_input(
        c, "シーン", "スクリーンリーダー音声", "PCTalker.exe")
    check("対象未検出でNone", value is None, str(value))
    check("作成は試みる", len(c.created) == 1)
    check("作りかけを削除する",
          "スクリーンリーダー音声" in c.removed, str(c.removed))
    check("入力は残らない",
          setup.input_exists(c, "スクリーンリーダー音声") is False)


def test_create_when_missing_keep() -> None:
    # remove_if_not_found=False: 未ターゲットでも入力を残しミュート
    c = FakeClient(found=False)
    value = setup.create_sr_audio_input(
        c, "シーン", "スクリーンリーダー音声", "PCTalker.exe",
        remove_if_not_found=False)
    check("対象未検出でNone(keep)", value is None, str(value))
    check("削除しない", c.removed == [], str(c.removed))
    check("ミュートはする",
          c.muted.get("スクリーンリーダー音声") is True, str(c.muted))


def test_input_exists() -> None:
    c = FakeClient()
    c._inputs = [{"inputName": "マイク"}, {"inputName": "スクリーンリーダー音声"}]
    check("存在する", setup.input_exists(c, "スクリーンリーダー音声") is True)
    check("存在しない", setup.input_exists(c, "無い入力") is False)


def test_rename_input() -> None:
    c = FakeClient()
    c._inputs = [{"inputName": "スクリーンリーダー音声"}]
    setup.rename_input(c, "スクリーンリーダー音声", "PC-Talker音声")
    check("リネーム後の名前で存在",
          setup.input_exists(c, "PC-Talker音声") is True)
    check("旧名は消える",
          setup.input_exists(c, "スクリーンリーダー音声") is False)


SAMPLE_DEVICES = [
    {"itemName": "既定", "itemValue": "default"},
    {"itemName": "Line (Steinberg UR44C)", "itemValue": "{0.0.1.aaa}"},
    {"itemName": "CABLE Output (VB-Audio Virtual Cable)",
     "itemValue": "{0.0.1.6603bc7a}"},
    {"itemName": "マイク (Realtek USB Audio)", "itemValue": "{0.0.1.bbb}"},
]


def test_pick_device_id() -> None:
    v = setup.pick_device_id(SAMPLE_DEVICES, "CABLE Output")
    check("CABLE Outputのidを選ぶ", v == "{0.0.1.6603bc7a}", str(v))
    v2 = setup.pick_device_id(SAMPLE_DEVICES, "cable output")
    check("大文字小文字を無視", v2 == "{0.0.1.6603bc7a}", str(v2))
    check("既定は選ばない",
          setup.pick_device_id(
              [{"itemName": "既定", "itemValue": "default"}], "既定") is None)
    check("無ければNone",
          setup.pick_device_id(SAMPLE_DEVICES, "存在しない") is None)


class DeviceFakeClient:
    """デバイスキャプチャ作成の呼び出しを記録するフェイク。"""

    def __init__(self, found: bool = True) -> None:
        self.created: list[tuple] = []
        self.settings: dict[str, dict] = {}
        self.muted: dict[str, bool] = {}
        self.removed: list[str] = []
        self._found = found

    def create_input(self, scene, name, kind, s, enabled):
        self.created.append((scene, name, kind, enabled))

    def get_input_properties_list_property_items(self, name, prop):
        items = SAMPLE_DEVICES if self._found else [
            {"itemName": "既定", "itemValue": "default"}]
        return SimpleNamespace(property_items=items)

    def set_input_settings(self, name, settings, overlay):
        self.settings[name] = settings

    def set_input_mute(self, name, muted):
        self.muted[name] = muted

    def remove_input(self, name):
        self.removed.append(name)


def test_create_device_capture() -> None:
    c = DeviceFakeClient(found=True)
    dev = setup.create_device_capture_input(
        c, "シーン", "NVDA音声", "CABLE Output")
    check("device_idを返す", dev == "{0.0.1.6603bc7a}", str(dev))
    check("入力種別が正しい",
          c.created[0][2] == setup.DEVICE_INPUT_KIND, c.created[0][2])
    s = c.settings.get("NVDA音声", {})
    check("device_idを設定", s.get("device_id") == "{0.0.1.6603bc7a}", str(s))
    check("初期ミュート", c.muted.get("NVDA音声") is True, str(c.muted))


def test_create_device_missing() -> None:
    c = DeviceFakeClient(found=False)
    dev = setup.create_device_capture_input(
        c, "シーン", "NVDA音声", "CABLE Output")
    check("未検出でNone", dev is None, str(dev))
    check("作りかけを削除", "NVDA音声" in c.removed, str(c.removed))


def test_dispatch_by_method() -> None:
    # device 方式のディスパッチ
    c = DeviceFakeClient(found=True)
    src = {"name": "NVDA音声", "method": "device", "device_match": "CABLE Output"}
    dev = setup.create_sr_source_input(c, "シーン", src)
    check("device方式にディスパッチ", dev == "{0.0.1.6603bc7a}", str(dev))
    # app 方式のディスパッチ
    c2 = FakeClient(found=True)
    src2 = {"name": "スクリーンリーダー音声", "method": "app",
            "exe": "PCTalker.exe"}
    val = setup.create_sr_source_input(c2, "シーン", src2)
    check("app方式にディスパッチ",
          val == "音声基本設定:#2232770:PCTalker.exe", str(val))


def run() -> tuple[int, int]:
    for fn in (
        test_parse_window_exe,
        test_pick_process_window,
        test_create_sets_target_and_mutes,
        test_create_when_process_missing,
        test_create_when_missing_keep,
        test_input_exists,
        test_rename_input,
        test_pick_device_id,
        test_create_device_capture,
        test_create_device_missing,
        test_dispatch_by_method,
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
    print(f"setup: {p} passed, {f} failed")
