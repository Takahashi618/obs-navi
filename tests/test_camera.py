# -*- coding: utf-8 -*-
"""camera モジュールのテスト。

★このテストが守っているのは「カメラが動いているかを嘘なく伝えること」。
見えない利用者にとって、カメラの動作は読み上げでしか分からない
（本体のランプが判断材料にならない）ので、ここを間違えると
「止めたつもりで撮られている」が起きる。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.camera import (  # noqa: E402
    ACTIVATE_BUTTON,
    CAMERA_KIND,
    STATE_OFF,
    STATE_ON,
    STATE_ON_NO_SIGNAL,
    build_state,
    device_label,
    is_camera_kind,
    is_virtual_device,
    next_state_after_toggle,
    unused_devices,
)
from core.speech_format import (  # noqa: E402
    camera_list_speech,
    camera_state_speech,
    camera_toggle_result_speech,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_kind_and_button() -> None:
    check("種別", CAMERA_KIND == "dshow_input")
    # ★設定ではなくボタン。設定 active を書いてもデバイスは止まらない
    #   ことを実機で確認している（core/camera.py の冒頭）
    check("切り替えはボタン", ACTIVATE_BUTTON == "activate")
    check("種別の判定", is_camera_kind("dshow_input"))
    check("音声入力はカメラではない",
          not is_camera_kind("wasapi_input_capture"))


def test_build_state_three_ways() -> None:
    """★「止まっている」「動いて映っている」「動いているが映らない」の3つを
    必ず言い分けること。真ん中で丸めると嘘になる。"""
    off = build_state("カメラ", {"active": False}, "c922", 0.0)
    check("無効なら止まっている", off.state == STATE_OFF, off.state)
    on = build_state("カメラ", {"active": True}, "c922", 1920.0)
    check("有効で映像あり", on.state == STATE_ON, on.state)
    # 起動直後や、キャプチャーボードに信号が来ていないとき（ノーシグナル）
    nosig = build_state("カメラ", {"active": True}, "GC551", 0.0)
    check("有効でも映像が無ければ言い分ける",
          nosig.state == STATE_ON_NO_SIGNAL, nosig.state)
    # ★無効なのに映像サイズが残っていても「動いている」と言わない
    stale = build_state("カメラ", {"active": False}, "c922", 1920.0)
    check("無効が最優先", stale.state == STATE_OFF, stale.state)


def test_build_state_defaults() -> None:
    # 設定が取れないときは OBS の既定（active=true）に合わせる。
    # ★安全側＝「動いているかもしれない」に倒す。動いていないと
    #   決めつける方が危ない
    unknown = build_state("カメラ", {}, "", 0.0)
    check("activeが無ければ動作中扱い", unknown.active is True)
    check("機材名が無ければ未設定", unknown.device == "未設定")
    check("シーンに無ければ表示状態はNone", unknown.visible is None)


def test_speech_says_camera_running() -> None:
    on = build_state("ウェブカメラ", {"active": True}, "c922 Pro", 1920.0)
    text = camera_state_speech(on)
    check("動作を伝える", "動いています" in text, text)
    check("映像の有無を伝える", "映像が来ています" in text, text)
    check("機材名を伝える", "c922 Pro" in text, text)

    off = build_state("ウェブカメラ", {"active": False}, "c922 Pro", 0.0)
    text_off = camera_state_speech(off)
    check("停止を伝える", "止まっています" in text_off, text_off)
    check("使われていないと伝える", "使われていません" in text_off, text_off)
    # ★止まっているときに「動いています」と読まないこと
    check("停止時に動作中と言わない",
          "動いています" not in text_off, text_off)

    nosig = build_state("キャプチャーボード", {"active": True}, "GC551", 0.0)
    text_ns = camera_state_speech(nosig)
    check("信号なしを言い分ける",
          "映像は来ていません" in text_ns, text_ns)
    check("信号なしでも動作中とは言う",
          "動いています" in text_ns, text_ns)


def test_speech_visibility_is_separate() -> None:
    """表示・非表示と、カメラが動いているかは別のこと。"""
    hidden = build_state("カメラ", {"active": True}, "c922", 1920.0,
                         visible=False)
    text = camera_state_speech(hidden)
    check("非表示を伝える", "非表示" in text, text)
    check("それでも動作中と伝える", "動いています" in text, text)
    shown = build_state("カメラ", {"active": True}, "c922", 1920.0,
                        visible=True)
    check("表示中なら余計なことを言わない",
          "非表示" not in camera_state_speech(shown))


def test_toggle_result_warns_on_failure() -> None:
    """★期待どおりにならなかったら、はっきり言うこと。"""
    still_on = build_state("カメラ", {"active": True}, "c922", 1920.0)
    text = camera_toggle_result_speech(still_on, expected_active=False)
    check("止められなかったと言う", "止められませんでした" in text, text)
    check("まだ動いていると言う", "まだ動いています" in text, text)

    still_off = build_state("カメラ", {"active": False}, "c922", 0.0)
    text2 = camera_toggle_result_speech(still_off, expected_active=True)
    check("動かせなかったと言う", "動かせませんでした" in text2, text2)

    ok = build_state("カメラ", {"active": False}, "c922", 0.0)
    text3 = camera_toggle_result_speech(ok, expected_active=False)
    check("成功なら状態を読む", "止まっています" in text3, text3)

    check("状態不明なら確認できないと言う",
          "確認できませんでした"
          in camera_toggle_result_speech(None, expected_active=False))


def test_next_state_after_toggle() -> None:
    # ボタンは押すたびに反転する（値を指定できない）ので、押す前の状態から
    # 期待値を決めるしかない
    check("動作中から押すと止まる", next_state_after_toggle(True) is False)
    check("停止から押すと動く", next_state_after_toggle(False) is True)


def test_unused_devices() -> None:
    items = [
        {"itemName": "AVerMedia GC551 Video Capture",
         "itemValue": "gc551", "itemEnabled": True},
        {"itemName": "c922 Pro Stream Webcam",
         "itemValue": "c922", "itemEnabled": True},
        {"itemName": "OBS Virtual Camera",
         "itemValue": "obsvcam", "itemEnabled": True},
        {"itemName": "外したカメラ", "itemValue": "gone", "itemEnabled": False},
    ]
    got = unused_devices(items, ["gc551"])
    check("使っていない機材を挙げる", "c922 Pro Stream Webcam" in got, str(got))
    check("使っている機材は挙げない",
          not any("GC551" in g for g in got), str(got))
    # ★OBSの仮想カメラは機材ではないので挙げない（選んでも意味が無い）
    check("仮想カメラは挙げない",
          not any("Virtual" in g for g in got), str(got))
    check("つながっていない機材は挙げない",
          "外したカメラ" not in got, str(got))
    check("空でも落ちない", unused_devices([], []) == [])
    check("Noneでも落ちない", unused_devices(None, None) == [])


def test_is_virtual_device() -> None:
    check("OBS Virtual Camera", is_virtual_device("OBS Virtual Camera"))
    check("大文字小文字を無視", is_virtual_device("obs virtual camera"))
    check("実機は仮想でない", not is_virtual_device("c922 Pro Stream Webcam"))


def test_device_label() -> None:
    check("そのまま読む",
          device_label("c922 Pro Stream Webcam") == "c922 Pro Stream Webcam")
    check("余分な空白を詰める",
          device_label("  c922   Pro  ") == "c922 Pro")
    check("空は未設定", device_label("") == "未設定")


def test_camera_list_speech() -> None:
    states = [
        build_state("ウェブカメラ", {"active": True}, "c922", 1920.0),
        build_state("キャプチャーボード", {"active": False}, "GC551", 0.0),
    ]
    text = camera_list_speech(states, ["予備のカメラ"])
    check("件数を言う", "カメラ 2 件" in text, text)
    check("1台目の状態", "動いています" in text, text)
    check("2台目の状態", "止まっています" in text, text)
    check("使っていない機材を知らせる", "使っていない機材" in text, text)
    check("作り方まで言う", "ソースを作る" in text, text)
    empty = camera_list_speech([], [])
    check("ソースが無いことを言う", "ソースがありません" in empty, empty)


TESTS = [
    test_kind_and_button,
    test_build_state_three_ways,
    test_build_state_defaults,
    test_speech_says_camera_running,
    test_speech_visibility_is_separate,
    test_toggle_result_warns_on_failure,
    test_next_state_after_toggle,
    test_unused_devices,
    test_is_virtual_device,
    test_device_label,
    test_camera_list_speech,
]


def results() -> list[tuple[str, bool, str]]:
    return _results


def run() -> tuple[int, int]:
    _results.clear()
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} が例外", False, repr(exc))
    passed = sum(1 for _n, ok, _d in _results if ok)
    return passed, len(_results) - passed


if __name__ == "__main__":
    p, f = run()
    for name, ok, detail in _results:
        mark = "OK" if ok else "NG"
        line = f"[{mark}] {name}"
        if not ok and detail:
            line += f" -> {detail}"
        print(line)
    print(f"{p} passed, {f} failed")
