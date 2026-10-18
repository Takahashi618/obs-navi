# -*- coding: utf-8 -*-
"""hotkeys モジュール（修飾キー解析）のテスト。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import hotkeys  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_repeat_confirm() -> None:
    """0.18.2: グローバルキーの二度押し確認。"""
    rc = hotkeys.RepeatConfirm(5.0)
    check("1回目は実行しない", rc.press("stream_start", 100.0) is False)
    check("猶予のうちの2回目で実行", rc.press("stream_start", 103.0) is True)
    check("実行したら待ちは消える（3回目は1回目扱い）",
          rc.press("stream_start", 104.0) is False)
    rc = hotkeys.RepeatConfirm(5.0)
    rc.press("stream_start", 100.0)
    check("猶予を過ぎたら実行しない",
          rc.press("stream_start", 105.5) is False)
    check("過ぎた2回目が新しい1回目になる",
          rc.press("stream_start", 106.0) is True)
    rc = hotkeys.RepeatConfirm(5.0)
    rc.press("stream_start", 100.0)
    check("別のキーを挟んだら実行しない",
          rc.press("stream_stop", 101.0) is False)
    check("挟んだ前の1回目は取り消し",
          rc.press("stream_start", 102.0) is False)
    rc.reset()
    check("reset で待ちが消える", rc.press("stream_start", 102.5) is False)


def test_repeat_confirm_note() -> None:
    """0.18.3: キーの受け口で知らせる。別のキーなら1回目を取り消す。

    ★press まで届かないキー（すでに配信中で早めに終わる、など）を
    挟んでも取り消されること。0.18.2 はここが漏れていた。
    """
    rc = hotkeys.RepeatConfirm(5.0)
    rc.note("stream_stop")
    rc.press("stream_stop", 100.0)
    rc.note("stream_start")          # press まで届かなかった別のキー
    rc.note("stream_stop")
    check("別のキーが届いたら2回目扱いにしない",
          rc.press("stream_stop", 101.0) is False)
    rc = hotkeys.RepeatConfirm(5.0)
    rc.press("stream_stop", 100.0)
    rc.note("stream_stop")
    check("同じキーなら待ちを残す", rc.press("stream_stop", 101.0) is True)
    check("既定の猶予は、案内を聞き終えて押し直せる長さ",
          hotkeys.REPEAT_CONFIRM_SECONDS >= 8.0,
          str(hotkeys.REPEAT_CONFIRM_SECONDS))


def test_win32_hotkey_args() -> None:
    """0.18.3: Win32 へ直接渡す値。MOD_NOREPEAT を必ず付ける。"""
    mods, vk = hotkeys.win32_hotkey_args(["ctrl", "alt", "shift"], "F6")
    check("押しっぱなしで繰り返さない（MOD_NOREPEAT）",
          mods & hotkeys.WIN32_MOD_NOREPEAT == hotkeys.WIN32_MOD_NOREPEAT,
          hex(mods))
    check("Ctrl+Alt+Shift の値", mods & 0x0007 == 0x0007, hex(mods))
    check("F6 は VK_F6（0x75）", vk == 0x75, hex(vk))
    check("F1 は VK_F1（0x70）",
          hotkeys.win32_hotkey_args(["ctrl"], "F1")[1] == 0x70)
    check("F12 は VK_F12（0x7B）",
          hotkeys.win32_hotkey_args(["ctrl"], "f12")[1] == 0x7B)
    check("Win キーの値",
          hotkeys.win32_hotkey_args(["win"], "F1")[0] & 0x0008 == 0x0008)
    for bad_tokens, bad_key in ((["ctrl"], "F13"), (["ctrl"], "A"),
                                (["ctrl"], "F０"), (["hyper"], "F1")):
        try:
            hotkeys.win32_hotkey_args(bad_tokens, bad_key)
        except ValueError:
            check(f"使えない値は断る: {bad_tokens} {bad_key}", True)
        else:
            check(f"使えない値は断る: {bad_tokens} {bad_key}", False)


def test_parse_basic() -> None:
    check("Ctrl+Shift",
          hotkeys.parse_modifier_tokens("Ctrl+Shift") == ["ctrl", "shift"],
          str(hotkeys.parse_modifier_tokens("Ctrl+Shift")))
    check("大文字小文字を吸収",
          hotkeys.parse_modifier_tokens("CTRL+alt") == ["ctrl", "alt"])
    check("別名 control/option",
          hotkeys.parse_modifier_tokens("control+option") == ["ctrl", "alt"])
    check("win系の別名",
          hotkeys.parse_modifier_tokens("super") == ["win"])


def test_parse_edge() -> None:
    check("空文字は空リスト", hotkeys.parse_modifier_tokens("") == [])
    check("未知トークンは無視",
          hotkeys.parse_modifier_tokens("Ctrl+Foo") == ["ctrl"],
          str(hotkeys.parse_modifier_tokens("Ctrl+Foo")))
    check("重複は最初のみ",
          hotkeys.parse_modifier_tokens("Ctrl+ctrl+Shift")
          == ["ctrl", "shift"])
    check("余分な空白と区切り",
          hotkeys.parse_modifier_tokens(" Ctrl + + Shift ")
          == ["ctrl", "shift"])


def test_labels() -> None:
    check("修飾キー表示",
          hotkeys.modifier_label(["ctrl", "shift"]) == "Ctrl+Shift")
    check("ホットキー表示",
          hotkeys.hotkey_label(["ctrl", "shift"], "F8") == "Ctrl+Shift+F8")
    check("修飾なしはキーのみ",
          hotkeys.hotkey_label([], "F8") == "F8")


def test_coarse_modifier_tokens() -> None:
    """粗い刻み用の修飾キーは基準に1つ足したもの（Alt優先、次にShift）。

    グローバルの基準が既に Ctrl+Shift なので、ウィンドウ内のように
    Shift を足して粗くする手は使えない（同じ組み合わせになる）。
    """
    from core.hotkeys import coarse_modifier_tokens

    check("Ctrl+Shift には Alt を足す",
          coarse_modifier_tokens(["ctrl", "shift"]) == ["ctrl", "shift", "alt"],
          str(coarse_modifier_tokens(["ctrl", "shift"])))
    check("Ctrl+Alt には Shift を足す（基準をCtrl+Altにした場合）",
          coarse_modifier_tokens(["ctrl", "alt"]) == ["ctrl", "alt", "shift"],
          str(coarse_modifier_tokens(["ctrl", "alt"])))
    check("Ctrl だけなら Alt を足す",
          coarse_modifier_tokens(["ctrl"]) == ["ctrl", "alt"],
          str(coarse_modifier_tokens(["ctrl"])))
    check("元のリストを壊さない", _unchanged_after_coarse())
    check("Alt も Shift も入っていれば足す余地がないので None",
          coarse_modifier_tokens(["ctrl", "shift", "alt"]) is None,
          str(coarse_modifier_tokens(["ctrl", "shift", "alt"])))
    check("空ならNone", coarse_modifier_tokens([]) is None,
          str(coarse_modifier_tokens([])))


def _unchanged_after_coarse() -> bool:
    from core.hotkeys import coarse_modifier_tokens

    base = ["ctrl", "shift"]
    coarse_modifier_tokens(base)
    return base == ["ctrl", "shift"]


def run() -> tuple[int, int]:
    for fn in (
        test_coarse_modifier_tokens, test_parse_basic, test_parse_edge,
        test_labels, test_repeat_confirm, test_repeat_confirm_note,
        test_win32_hotkey_args,
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
    print(f"hotkeys: {p} passed, {f} failed")
