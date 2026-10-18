# -*- coding: utf-8 -*-
"""levels モジュールのテスト（時刻を注入して時間経過を再現）。"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.levels import (  # noqa: E402
    LevelMonitor,
    mul_to_db,
    peak_db_from_levels,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def _fresh_monitor() -> LevelMonitor:
    return LevelMonitor(
        silence_threshold_db=-50.0,
        silence_seconds=60.0,
        clip_threshold_db=-0.5,
        cooldown_seconds=30.0,
    )


def test_db_conversion() -> None:
    check("mul=1.0は0dB付近", abs(mul_to_db(1.0)) < 0.001, str(mul_to_db(1.0)))
    check("mul=0は下限", mul_to_db(0.0) == -120.0, str(mul_to_db(0.0)))
    check("mul=0.5は約-6dB", abs(mul_to_db(0.5) - (-6.0206)) < 0.01,
          str(mul_to_db(0.5)))
    peak = peak_db_from_levels([[0.1, 0.5, 0.5], [0.2, 0.7, 0.7]])
    check("複数chの最大peakを採用", abs(peak - mul_to_db(0.7)) < 0.001, str(peak))
    check("空リストは下限", peak_db_from_levels([]) == -120.0)


def test_silence_warns_once() -> None:
    m = _fresh_monitor()
    m.set_active(True, now=0.0)
    # 入力を認識した時刻(10.0)を起点に無音が続く
    w = m.update("マイク", -80.0, now=10.0)
    check("60秒未満では無音警告なし", w == [], str(w))
    w = m.update("マイク", -80.0, now=70.0)
    check("60秒経過で無音警告1回", len(w) == 1 and w[0].kind == "silence",
          str(w))
    w = m.update("マイク", -80.0, now=71.0)
    check("無音継続では再警告しない", w == [], str(w))


def test_silence_rearm_after_sound() -> None:
    m = _fresh_monitor()
    m.set_active(True, now=0.0)
    m.update("マイク", -80.0, now=0.0)   # 入力を認識（起点）
    w = m.update("マイク", -80.0, now=61.0)  # 60秒経過で1回警告
    check("最初の無音警告", len(w) == 1 and w[0].kind == "silence", str(w))
    # 音が戻る
    w = m.update("マイク", -10.0, now=62.0)
    check("音復帰時は警告なし", w == [], str(w))
    # 再び無音（クールダウン30秒も経過させ、無音60秒を満たす）
    m.update("マイク", -80.0, now=100.0)
    w = m.update("マイク", -80.0, now=161.0)
    check("復帰後の無音で再警告", len(w) == 1 and w[0].kind == "silence", str(w))


def test_no_warn_when_inactive() -> None:
    m = _fresh_monitor()
    # 監視オフ（配信も録画もしていない）
    w = m.update("マイク", -80.0, now=61.0)
    check("非アクティブ時は無音警告なし", w == [], str(w))
    w = m.update("マイク", 0.0, now=62.0)
    check("非アクティブ時はクリップ警告なし", w == [], str(w))


def test_no_warn_when_muted() -> None:
    m = _fresh_monitor()
    m.set_active(True, now=0.0)
    w = m.update("マイク", -80.0, now=61.0, muted=True)
    check("ミュート中は無音警告なし", w == [], str(w))
    w = m.update("マイク", 0.0, now=62.0, muted=True)
    check("ミュート中はクリップ警告なし", w == [], str(w))


def test_clip_warns_with_cooldown() -> None:
    m = _fresh_monitor()
    m.set_active(True, now=0.0)
    w = m.update("マイク", 0.0, now=1.0)
    check("しきい値超えでクリップ警告", len(w) == 1 and w[0].kind == "clip",
          str(w))
    w = m.update("マイク", 0.0, now=5.0)
    check("クールダウン中は再警告しない", w == [], str(w))
    w = m.update("マイク", 0.0, now=32.0)
    check("クールダウン後は再警告", len(w) == 1 and w[0].kind == "clip", str(w))


def test_clip_suppressed_when_inactive() -> None:
    m = _fresh_monitor()
    w = m.update("マイク", 3.0, now=1.0)
    check("非アクティブ時はクリップ抑制", w == [], str(w))


def test_suppress_warnings_tracks_peak_no_warn() -> None:
    m = _fresh_monitor()
    m.set_active(True, now=0.0)
    # スクリーンリーダー音声想定: 警告抑止だがピークは追跡する
    m.update("NVDA音声", -80.0, now=0.0, suppress_warnings=True)
    w = m.update("NVDA音声", -80.0, now=120.0, suppress_warnings=True)
    check("抑止中は無音警告なし", w == [], str(w))
    w = m.update("NVDA音声", 0.0, now=121.0, suppress_warnings=True)
    check("抑止中はクリップ警告なし", w == [], str(w))
    peaks = m.current_peaks()
    check("ピークは追跡される", peaks.get("NVDA音声") == 0.0, str(peaks))


# ------------------------------------------------------------
# レベル読み上げ(F6)のピーク保持窓
# ------------------------------------------------------------
def test_hold_reports_recent_peak_not_instant() -> None:
    """声が途切れた瞬間に押しても、直前のレベルを読めること。"""
    m = LevelMonitor(hold_seconds=3.0)
    m.update("NVDA音声", -12.0, now=10.0)   # 喋っている
    m.update("NVDA音声", -120.0, now=11.0)  # 息継ぎで無音
    peaks = m.current_peaks(now=11.0)
    check("窓の中の最大を読む（瞬間値ではない）",
          peaks.get("NVDA音声") == -12.0, str(peaks))


def test_hold_window_expires() -> None:
    """窓から出た古いピークは読まない（いつまでも残らない）。"""
    m = LevelMonitor(hold_seconds=3.0)
    m.update("NVDA音声", -12.0, now=10.0)
    m.update("NVDA音声", -120.0, now=14.0)  # 4秒後 = 窓の外
    peaks = m.current_peaks(now=14.0)
    check("3秒より古いピークは落ちる",
          peaks.get("NVDA音声") == -120.0, str(peaks))


def test_hold_zero_is_instant_value() -> None:
    """hold_seconds=0 なら従来どおり瞬間値。"""
    m = LevelMonitor(hold_seconds=0.0)
    m.update("マイク", -12.0, now=10.0)
    m.update("マイク", -120.0, now=10.05)
    peaks = m.current_peaks(now=10.05)
    check("hold=0は瞬間値のまま", peaks.get("マイク") == -120.0, str(peaks))


def test_hold_stale_when_meters_stopped() -> None:
    """メーターが止まったら、古い値を読まず無音扱いにする。"""
    m = LevelMonitor(hold_seconds=3.0)
    m.update("マイク", -12.0, now=10.0)
    peaks = m.current_peaks(now=30.0)  # 20秒メーターが来ていない
    check("窓に何も無ければ無音扱い", peaks.get("マイク") == -120.0, str(peaks))
    peaks = m.current_peaks()  # now を渡さなければ持っている値をそのまま
    check("nowなしなら保持値を返す", peaks.get("マイク") == -12.0, str(peaks))


def test_hold_does_not_change_warnings() -> None:
    """保持窓は読み上げ用。警告の判定は瞬間値のままであること。"""
    m = LevelMonitor(hold_seconds=3.0, silence_threshold_db=-50.0,
                     silence_seconds=60.0, clip_threshold_db=-0.5)
    m.set_active(True, now=0.0)
    m.update("マイク", 0.0, now=1.0)          # クリップ
    # 直前に大きい音があっても、無音が続けば無音警告は出る
    m.update("マイク", -80.0, now=2.0)
    w = m.update("マイク", -80.0, now=63.0)
    check("保持窓があっても無音警告は瞬間値で判定",
          len(w) == 1 and w[0].kind == "silence", str(w))


def test_hold_memory_is_bounded() -> None:
    """窓ぶんしか溜めない（高頻度イベントで際限なく増えない）。"""
    m = LevelMonitor(hold_seconds=3.0)
    t = 0.0
    for _ in range(2000):  # 50ms間隔で100秒ぶん
        m.update("マイク", -30.0, now=t)
        t += 0.05
    history = m._inputs["マイク"].peak_history  # noqa: SLF001
    check("保持件数は窓ぶんに収まる", len(history) <= 62, str(len(history)))


def test_concurrent_update_and_read() -> None:
    """wsスレッドがupdateし続ける中でcurrent_peaksを読んでも落ちないこと。

    実機では update が obsws-python の別スレッドから ~50ms ごとに呼ばれ、
    current_peaks は F6 のたびに UIスレッドから呼ばれる。ロックが無いと
    「deque mutated during iteration」や
    「dictionary changed size during iteration」で落ちる。
    """
    m = LevelMonitor(hold_seconds=3.0)
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        # 入力が途中で増えるのも再現する（辞書への挿入と反復の競合）
        t = 0.0
        i = 0
        try:
            while not stop.is_set():
                m.update(f"入力{i % 8}", -30.0, now=t)
                t += 0.05
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                m.current_peaks(now=1.0)
                m.current_peaks()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, daemon=True),
               threading.Thread(target=reader, daemon=True),
               threading.Thread(target=reader, daemon=True)]
    for th in threads:
        th.start()
    time.sleep(0.7)
    stop.set()
    for th in threads:
        th.join(timeout=5.0)

    # デッドロック型の退行は join(timeout) が黙って諦めるため、
    # is_alive を失敗条件にする（daemon なのでスイート終了もハングしない）
    stuck = [th for th in threads if th.is_alive()]
    check("スレッドが時間内に終了する（デッドロックなし）", not stuck,
          f"{len(stuck)} 本が終了せず")
    check("並行アクセスで例外が出ない", not errors,
          "; ".join(repr(e) for e in errors[:3]))


def test_concurrent_forget_missing() -> None:
    """入力の削除(UIスレッド)と update(wsスレッド)が競合しても落ちないこと。"""
    m = LevelMonitor(hold_seconds=3.0)
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        t = 0.0
        i = 0
        try:
            while not stop.is_set():
                m.update(f"入力{i % 8}", -30.0, now=t)
                t += 0.05
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def forgetter() -> None:
        try:
            while not stop.is_set():
                m.forget_missing({"入力0", "入力1"})
                m.current_peaks(now=1.0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, daemon=True),
               threading.Thread(target=forgetter, daemon=True)]
    for th in threads:
        th.start()
    time.sleep(0.7)
    stop.set()
    for th in threads:
        th.join(timeout=5.0)

    stuck = [th for th in threads if th.is_alive()]
    check("スレッドが時間内に終了する（デッドロックなし）", not stuck,
          f"{len(stuck)} 本が終了せず")
    check("削除と更新の並行で例外が出ない", not errors,
          "; ".join(repr(e) for e in errors[:3]))


def run() -> tuple[int, int]:
    for fn in (
        test_db_conversion,
        test_silence_warns_once,
        test_silence_rearm_after_sound,
        test_no_warn_when_inactive,
        test_no_warn_when_muted,
        test_clip_warns_with_cooldown,
        test_clip_suppressed_when_inactive,
        test_suppress_warnings_tracks_peak_no_warn,
        test_hold_reports_recent_peak_not_instant,
        test_hold_window_expires,
        test_hold_zero_is_instant_value,
        test_hold_stale_when_meters_stopped,
        test_hold_does_not_change_warnings,
        test_hold_memory_is_bounded,
        test_concurrent_update_and_read,
        test_concurrent_forget_missing,
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
    print(f"levels: {p} passed, {f} failed")
