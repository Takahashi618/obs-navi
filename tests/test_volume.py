# -*- coding: utf-8 -*-
"""volume モジュールのテスト（純関数）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.volume import (  # noqa: E402
    VOLUME_MAX_DB,
    VOLUME_MIN_DB,
    clamp_db,
    next_db,
    parse_db_input,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_clamp() -> None:
    check("上限を超えたら上限", clamp_db(30.0) == VOLUME_MAX_DB)
    check("下限を下回ったら下限", clamp_db(-200.0) == VOLUME_MIN_DB)
    check("範囲内はそのまま", clamp_db(-6.0) == -6.0)
    check("上限ちょうどは通る", clamp_db(26.0) == 26.0)
    check("下限ちょうどは通る", clamp_db(-100.0) == -100.0)


def test_next_db_on_grid() -> None:
    check("格子上から+1", next_db(6.0, 1.0, 1.0) == 7.0, str(next_db(6.0, 1.0, 1.0)))
    check("格子上から-1", next_db(6.0, -1.0, 1.0) == 5.0, str(next_db(6.0, -1.0, 1.0)))
    check("格子上から+5", next_db(6.0, 5.0, 1.0) == 11.0, str(next_db(6.0, 5.0, 1.0)))
    check("格子上から-5", next_db(6.0, -5.0, 1.0) == 1.0, str(next_db(6.0, -5.0, 1.0)))
    check("0をまたぐ", next_db(0.0, -1.0, 1.0) == -1.0, str(next_db(0.0, -1.0, 1.0)))


def test_next_db_off_grid_snaps() -> None:
    """OBSの詳細設定で付いた半端な値(+5.1dB)は格子へ寄せる。

    寄せないと 5.1→6.1 となり、読み上げ「プラス6デシベル」と実際の値が
    ずれたまま残る。このアプリは読み上げが唯一の情報源なので一致させる。
    """
    check("5.1から+1は6.0（6.1ではない）",
          next_db(5.1, 1.0, 1.0) == 6.0, str(next_db(5.1, 1.0, 1.0)))
    check("5.1から-1は4.0",
          next_db(5.1, -1.0, 1.0) == 4.0, str(next_db(5.1, -1.0, 1.0)))
    check("2.0から+1は3.0",
          next_db(2.0, 1.0, 1.0) == 3.0, str(next_db(2.0, 1.0, 1.0)))


def test_next_db_float32_noise() -> None:
    """OBSはfloat32由来の誤差込みで返す。丸めないと押しても値が変わらない。

    実測: 音量0dBが 0.0 で返るとは限らず、6.0が 5.99999952 で返ることがある。
    素朴に最寄り格子を取ると5になり、+1しても6.0のまま＝無反応に見える。
    """
    noisy = 5.999999523162842   # 実質 6.0
    check("誤差込み6.0から+1は7.0（6.0のままにならない）",
          next_db(noisy, 1.0, 1.0) == 7.0, str(next_db(noisy, 1.0, 1.0)))
    check("誤差込み6.0から-1は5.0",
          next_db(noisy, -1.0, 1.0) == 5.0, str(next_db(noisy, -1.0, 1.0)))
    # 実測した マイク の値でも確認
    mic = 5.099999904632568
    check("実測のマイク+5.1から+1は6.0",
          next_db(mic, 1.0, 1.0) == 6.0, str(next_db(mic, 1.0, 1.0)))


def test_next_db_always_changes_within_range() -> None:
    """範囲の内側なら押すたびに必ず値が変わること（無反応に見えないこと）。

    押したのに読み上げが変わらないと壊れていると誤解される。
    上限・下限に着いたあと動かないのは正しいので、そこは対象外
    （その挙動は test_next_db_clamps_at_limits で担保する）。
    ついでに端から端まで辿り着けること（途中で止まらないこと）も見る。
    """
    bad: list[str] = []
    value = -3.7
    steps = 0
    while value < VOLUME_MAX_DB and steps < 500:
        nxt = next_db(value, 1.0, 1.0)
        if nxt == value:
            bad.append(f"+1が無反応: {value}")
            break
        value = nxt
        steps += 1
    if value != VOLUME_MAX_DB:
        bad.append(f"上げ続けても上限に着かない: {value}")

    value = 3.7
    steps = 0
    while value > VOLUME_MIN_DB and steps < 500:
        nxt = next_db(value, -1.0, 1.0)
        if nxt == value:
            bad.append(f"-1が無反応: {value}")
            break
        value = nxt
        steps += 1
    if value != VOLUME_MIN_DB:
        bad.append(f"下げ続けても下限に着かない: {value}")

    check("範囲内では押すたびに必ず値が変わり、端まで辿り着ける",
          not bad, "; ".join(bad[:3]))


def test_next_db_clamps_at_limits() -> None:
    check("上限で止まる", next_db(26.0, 1.0, 1.0) == VOLUME_MAX_DB,
          str(next_db(26.0, 1.0, 1.0)))
    check("下限で止まる", next_db(-100.0, -1.0, 1.0) == VOLUME_MIN_DB,
          str(next_db(-100.0, -1.0, 1.0)))
    check("上限付近から粗い刻みでも超えない", next_db(24.0, 5.0, 1.0) == 26.0,
          str(next_db(24.0, 5.0, 1.0)))


def test_next_db_step_zero() -> None:
    """刻み0の設定でも壊れず、格子に寄せずそのまま足すこと。"""
    check("step=0なら素朴に足す", next_db(5.1, 1.0, 0.0) == 6.1,
          str(next_db(5.1, 1.0, 0.0)))


def test_next_db_custom_step() -> None:
    check("0.5刻みの格子", next_db(5.1, 0.5, 0.5) == 5.5,
          str(next_db(5.1, 0.5, 0.5)))
    check("2刻みの格子", next_db(5.1, 2.0, 2.0) == 8.0,
          str(next_db(5.1, 2.0, 2.0)))


def test_parse_db_input() -> None:
    check("整数", parse_db_input("5") == 5.0, str(parse_db_input("5")))
    check("負の値", parse_db_input("-10") == -10.0, str(parse_db_input("-10")))
    check("プラス記号つき", parse_db_input("+5.1") == 5.1,
          str(parse_db_input("+5.1")))
    check("小数", parse_db_input("5.1") == 5.1, str(parse_db_input("5.1")))
    check("前後の空白", parse_db_input("  3  ") == 3.0,
          str(parse_db_input("  3  ")))
    check("単位つき", parse_db_input("-10dB") == -10.0,
          str(parse_db_input("-10dB")))
    check("単位つき(大文字小文字混在と空白)", parse_db_input(" 3 db ") == 3.0,
          str(parse_db_input(" 3 db ")))
    check("日本語の単位つき", parse_db_input("6デシベル") == 6.0,
          str(parse_db_input("6デシベル")))
    check("全角数字", parse_db_input("５") == 5.0, str(parse_db_input("５")))
    check("全角マイナス", parse_db_input("－８") == -8.0,
          str(parse_db_input("－８")))


def test_parse_db_input_rejects() -> None:
    check("空文字はNone", parse_db_input("") is None)
    check("空白だけはNone", parse_db_input("   ") is None)
    check("文字はNone", parse_db_input("あ") is None)
    check("数値でない文字列はNone", parse_db_input("abc") is None)
    check("NoneはNone", parse_db_input(None) is None)
    check("infは拒否", parse_db_input("inf") is None,
          str(parse_db_input("inf")))
    check("nanは拒否", parse_db_input("nan") is None,
          str(parse_db_input("nan")))


def test_parse_db_input_clamps() -> None:
    """打ち間違いで拒否されるより、端へ丸めるほうが親切。"""
    check("大きすぎる値は上限へ", parse_db_input("100") == VOLUME_MAX_DB,
          str(parse_db_input("100")))
    check("小さすぎる値は下限へ", parse_db_input("-500") == VOLUME_MIN_DB,
          str(parse_db_input("-500")))


def run() -> tuple[int, int]:
    for fn in (
        test_clamp,
        test_next_db_on_grid,
        test_next_db_off_grid_snaps,
        test_next_db_float32_noise,
        test_next_db_always_changes_within_range,
        test_next_db_clamps_at_limits,
        test_next_db_step_zero,
        test_next_db_custom_step,
        test_parse_db_input,
        test_parse_db_input_rejects,
        test_parse_db_input_clamps,
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
    print(f"volume: {p} passed, {f} failed")
