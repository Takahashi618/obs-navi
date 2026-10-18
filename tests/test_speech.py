# -*- coding: utf-8 -*-
"""speech モジュールのテスト（起動直後の割り込み抑止）。

★読み上げの「割り込むかどうか」はこのアプリで最も壊れやすい部分。
画面が無いので、切られた読み上げは二度と確かめられない。
実際に発声させずに済むよう、speaker を差し替えて interrupt の値だけを
記録する。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OBSNAVI_SILENT"] = "1"

import speech  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


class _Recorder:
    """speak の呼び出しを記録するだけの偽スピーカー。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def speak(self, text: str, interrupt: bool = False) -> None:
        self.calls.append((text, bool(interrupt)))


def _with_recorder(fn):
    """_SILENT と _speaker を差し替えて fn を走らせ、記録を返す。"""
    rec = _Recorder()
    silent, speaker = speech._SILENT, speech._speaker
    speech._SILENT = False
    speech._speaker = rec
    try:
        fn()
    finally:
        speech._SILENT = silent
        speech._speaker = speaker
        speech.end_grace()
    return rec.calls


def test_grace_holds_for_a_span_not_one_call() -> None:
    """★1回きりにしない。

    0.17.3 は「最初の1回だけ割り込まない」作りだったので、接続完了の
    読み上げが猶予を使い切ったあと、直後に届くレベル警告やOBSの
    イベントが割り込み、結局バージョンが切られていた。
    """
    def body() -> None:
        speech.start_grace(5.0)
        speech.speak("接続しました", interrupt=True)
        speech.warn("音が小さいです")
        speech.error("切断しました")

    calls = _with_recorder(body)
    check("3件とも読む", len(calls) == 3, str(calls))
    check("どれも割り込まない", all(not i for _t, i in calls), str(calls))


def test_grace_expires_with_time() -> None:
    def body() -> None:
        speech.start_grace(0.05)
        speech.speak("最初", interrupt=True)
        time.sleep(0.12)
        speech.speak("あと", interrupt=True)

    calls = _with_recorder(body)
    check("猶予中は割り込まない", calls[0][1] is False, str(calls))
    check("時間が過ぎたら割り込む", calls[1][1] is True, str(calls))


def test_end_grace_lets_the_user_take_over() -> None:
    """利用者がキーを押したら、そこから先は操作への応答なので割り込んでよい。"""
    def body() -> None:
        speech.start_grace(5.0)
        speech.end_grace()
        speech.speak("押した結果", interrupt=True)

    calls = _with_recorder(body)
    check("打ち切れる", calls[0][1] is True, str(calls))


def test_grace_pending_reports_state() -> None:
    speech.end_grace()
    check("既定では猶予なし", speech.grace_pending() is False)
    speech.start_grace(5.0)
    check("開始で猶予中", speech.grace_pending() is True)
    speech.end_grace()
    check("打ち切りで猶予なし", speech.grace_pending() is False)
    speech.start_grace("こわれた値")
    check("読めない秒数でも既定の長さで動く", speech.grace_pending() is True)
    speech.end_grace()


def test_grace_never_turns_on_interrupt() -> None:
    """猶予は「割り込みを外す」だけ。付け足しはしない。"""
    def body() -> None:
        speech.end_grace()
        speech.speak("静かに", interrupt=False)

    calls = _with_recorder(body)
    check("interrupt=False はそのまま", calls[0][1] is False, str(calls))


def run() -> tuple[int, int]:
    for fn in (
        test_grace_holds_for_a_span_not_one_call,
        test_grace_expires_with_time,
        test_end_grace_lets_the_user_take_over,
        test_grace_pending_reports_state,
        test_grace_never_turns_on_interrupt,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _results.append((f"{fn.__name__} が例外で失敗", False, repr(exc)))
    passed = sum(1 for _, ok, _ in _results if ok)
    return passed, len(_results) - passed


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
    print(f"speech: {p} passed, {f} failed")
