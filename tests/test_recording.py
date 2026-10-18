# -*- coding: utf-8 -*-
"""recording モジュールのテスト（時刻・残量を注入して再現する）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.recording import (  # noqa: E402
    DISK_CRITICAL,
    DISK_OK,
    DISK_WARN,
    SECTION_ADVANCED,
    SECTION_SIMPLE,
    DiskWatch,
    PauseReminder,
    chapter_name,
    output_section,
    output_supports_chapters,
    pick_record_output,
    record_path_key,
    supports_chapters,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# ------------------------------------------------------------
# 出力モードとセクションの解決
# ------------------------------------------------------------
def test_output_section() -> None:
    check("Simple は簡易セクション",
          output_section("Simple") == SECTION_SIMPLE)
    check("Advanced は詳細セクション",
          output_section("Advanced") == SECTION_ADVANCED)
    check("大文字小文字を無視", output_section("advanced") == SECTION_ADVANCED)
    # 未知・空は安全側（この環境の既定である簡易）へ倒す
    check("空は簡易扱い", output_section("") == SECTION_SIMPLE)
    check("Noneは簡易扱い", output_section(None) == SECTION_SIMPLE)
    check("未知の値は簡易扱い", output_section("なにか") == SECTION_SIMPLE)


def test_record_path_key() -> None:
    check("簡易は FilePath", record_path_key(SECTION_SIMPLE) == "FilePath")
    check("詳細は RecFilePath",
          record_path_key(SECTION_ADVANCED) == "RecFilePath")


# ------------------------------------------------------------
# チャプター
# ------------------------------------------------------------
def test_supports_chapters() -> None:
    check("ハイブリッドMP4は対応", supports_chapters("hybrid_mp4"))
    check("ハイブリッドMOVも対応", supports_chapters("hybrid_mov"))
    check("大文字でも対応", supports_chapters("Hybrid_MP4"))
    # ★プレーンMP4では打てない。ここを取り違えると「押しても無反応」に
    #   見える機能になるので、対応表は狭く保つ
    check("プレーンMP4は非対応", not supports_chapters("mp4"))
    check("MKVは非対応", not supports_chapters("mkv"))
    check("フラグメントMP4は非対応", not supports_chapters("fragmented_mp4"))
    check("空は非対応", not supports_chapters(""))
    check("Noneは非対応", not supports_chapters(None))


def test_output_supports_chapters() -> None:
    # ★実測（OBS 32.2.2）: ハイブリッド形式は obs-outputs.dll の
    #   mp4_output / mov_output、従来形式は ffmpeg_muxer
    check("mp4_output は対応", output_supports_chapters("mp4_output"))
    check("mov_output も対応", output_supports_chapters("mov_output"))
    check("ffmpeg_muxer は非対応",
          not output_supports_chapters("ffmpeg_muxer"))
    check("空は非対応", not output_supports_chapters(""))
    check("Noneは非対応", not output_supports_chapters(None))


def test_pick_record_output() -> None:
    # 実測の応答をそのまま模す
    outputs = [
        {"outputName": "simple_file_output", "outputKind": "ffmpeg_muxer",
         "outputActive": False},
        {"outputName": "virtualcam_output", "outputKind": "virtualcam_output",
         "outputActive": False},
    ]
    got = pick_record_output(outputs)
    check("録画出力を選ぶ",
          got is not None and got.get("outputKind") == "ffmpeg_muxer",
          str(got))
    # ★仮想カメラ・配信・リプレイを掴んではいけない（種別を誤判定する）
    check("仮想カメラは選ばない",
          pick_record_output([outputs[1]]) is None)
    adv = [{"outputName": "adv_file_output", "outputKind": "mp4_output"}]
    got2 = pick_record_output(adv)
    check("詳細出力の名前でも選べる",
          got2 is not None and got2.get("outputKind") == "mp4_output")
    # 名前が想定と違っても、種別から救えること
    odd = [{"outputName": "なにか", "outputKind": "mov_output"}]
    got3 = pick_record_output(odd)
    check("名前が違っても種別で救う",
          got3 is not None and got3.get("outputKind") == "mov_output")
    check("空なら None", pick_record_output([]) is None)
    check("Noneでも落ちない", pick_record_output(None) is None)
    check("辞書でない要素は無視", pick_record_output(["x", 5]) is None)


def test_chapter_name() -> None:
    check("番号はゼロ詰め", chapter_name(3, "00:12:34") == "03 00:12:34",
          chapter_name(3, "00:12:34"))
    check("2桁もそのまま", chapter_name(12, "01:02:03") == "12 01:02:03",
          chapter_name(12, "01:02:03"))
    # OBSのタイムコードはミリ秒付きで来ることがある
    check("ミリ秒は落とす", chapter_name(1, "00:00:07.512") == "01 00:00:07",
          chapter_name(1, "00:00:07.512"))
    check("時刻が無ければ番号だけ", chapter_name(5, "") == "05",
          chapter_name(5, ""))


# ------------------------------------------------------------
# 一時停止の見張り
# ------------------------------------------------------------
def test_pause_reminder_notifies_after_interval() -> None:
    r = PauseReminder(interval_seconds=300.0)
    r.set_paused(True, now=100.0)
    check("一時停止した直後は知らせない", r.tick(now=100.0) is None)
    check("間隔未満では知らせない", r.tick(now=399.0) is None)
    elapsed = r.tick(now=400.0)
    check("300秒経過で知らせる", elapsed is not None, str(elapsed))
    check("経過秒は一時停止からの合計", abs((elapsed or 0) - 300.0) < 0.001,
          str(elapsed))


def test_pause_reminder_repeats() -> None:
    r = PauseReminder(interval_seconds=60.0)
    r.set_paused(True, now=0.0)
    check("1回目", r.tick(now=60.0) is not None)
    check("直後は知らせない", r.tick(now=61.0) is None)
    second = r.tick(now=120.0)
    check("2回目も知らせる", second is not None, str(second))
    check("2回目の経過は120秒", abs((second or 0) - 120.0) < 0.001, str(second))


def test_pause_reminder_resume_stops() -> None:
    r = PauseReminder(interval_seconds=60.0)
    r.set_paused(True, now=0.0)
    r.set_paused(False, now=10.0)
    check("再開したら追跡をやめる", not r.paused)
    check("再開後は知らせない", r.tick(now=1000.0) is None)
    # 再び一時停止したら、そこが新しい起点になる
    r.set_paused(True, now=1000.0)
    check("再度の一時停止は起点が動く", r.tick(now=1059.0) is None)
    check("新しい起点から数える", r.tick(now=1060.0) is not None)


def test_pause_reminder_set_paused_is_idempotent() -> None:
    # イベントとスナップショットの両方から呼ばれるので、同じ状態で
    # 繰り返し呼ばれても起点が動いてはいけない（動くと永久に知らせない）
    r = PauseReminder(interval_seconds=60.0)
    r.set_paused(True, now=0.0)
    for t in (10.0, 20.0, 30.0, 40.0, 50.0):
        r.set_paused(True, now=t)
    check("繰り返し呼んでも起点は動かない", r.tick(now=60.0) is not None)


def test_pause_reminder_disabled() -> None:
    r = PauseReminder(interval_seconds=0.0)
    r.set_paused(True, now=0.0)
    check("0なら知らせない", r.tick(now=100000.0) is None)
    check("それでも追跡はしている", r.paused)


def test_pause_reminder_reset() -> None:
    r = PauseReminder(interval_seconds=60.0)
    r.set_paused(True, now=0.0)
    r.reset()
    check("resetで追跡をやめる", not r.paused)
    check("reset後は知らせない", r.tick(now=1000.0) is None)


# ------------------------------------------------------------
# 空き容量の見張り
# ------------------------------------------------------------
def _fresh_watch() -> DiskWatch:
    return DiskWatch(warn_mb=10240.0, critical_mb=2048.0)


def test_disk_watch_levels() -> None:
    w = _fresh_watch()
    check("十分な残量では黙る", w.check(50000.0) == DISK_OK)
    check("しきい値を切ったら警告", w.check(9000.0) == DISK_WARN)
    check("同じ段階では繰り返さない", w.check(8000.0) == DISK_OK)
    check("危険域まで減ったら強い警告", w.check(1000.0) == DISK_CRITICAL)
    check("危険域でも繰り返さない", w.check(500.0) == DISK_OK)


def test_disk_watch_boundary() -> None:
    w = _fresh_watch()
    check("しきい値ちょうどは警告", w.check(10240.0) == DISK_WARN)
    w2 = _fresh_watch()
    check("危険しきい値ちょうどは強い警告", w2.check(2048.0) == DISK_CRITICAL)


def test_disk_watch_rearms_after_recovery() -> None:
    w = _fresh_watch()
    check("まず警告", w.check(9000.0) == DISK_WARN)
    # ★境界付近で往復しても鳴り直さない（余裕を見てから張り直す）
    check("少し戻っただけでは張り直さない", w.check(10500.0) == DISK_OK)
    check("張り直していないので再警告なし", w.check(9000.0) == DISK_OK)
    # 十分に戻れば張り直す（ファイルを消したときなど）
    check("十分戻ると張り直す", w.check(30000.0) == DISK_OK)
    check("張り直したので再び警告できる", w.check(9000.0) == DISK_WARN)


def test_disk_watch_critical_then_recover_to_warn() -> None:
    w = _fresh_watch()
    w.check(1000.0)  # 危険まで落ちる
    # 危険を脱しても、警告域にいる限り「警告」を鳴らし直さない
    # （下がったときに1段ずつ鳴らすのが目的で、上がったときは静かでよい）
    check("危険から警告域へ戻っても黙る", w.check(9000.0) == DISK_OK)
    check("再び危険へ落ちたら鳴らす", w.check(1000.0) == DISK_CRITICAL)


def test_disk_watch_reset() -> None:
    w = _fresh_watch()
    check("警告する", w.check(9000.0) == DISK_WARN)
    w.reset()
    check("resetすれば同じ残量でも警告し直す", w.check(9000.0) == DISK_WARN)


def test_disk_watch_disabled() -> None:
    w = DiskWatch(warn_mb=0.0, critical_mb=0.0)
    check("0なら警告しない", w.check(1.0) == DISK_OK)


def test_disk_watch_bad_input() -> None:
    w = _fresh_watch()
    check("数値でなければ黙る", w.check(None) == DISK_OK)
    check("文字列でも落ちない", w.check("たくさん") == DISK_OK)
    # 壊れた値のあとでも、正しい値では通常どおり判定できる
    check("壊れた値のあとも動く", w.check(9000.0) == DISK_WARN)


TESTS = [
    test_output_section,
    test_record_path_key,
    test_supports_chapters,
    test_output_supports_chapters,
    test_pick_record_output,
    test_chapter_name,
    test_pause_reminder_notifies_after_interval,
    test_pause_reminder_repeats,
    test_pause_reminder_resume_stops,
    test_pause_reminder_set_paused_is_idempotent,
    test_pause_reminder_disabled,
    test_pause_reminder_reset,
    test_disk_watch_levels,
    test_disk_watch_boundary,
    test_disk_watch_rearms_after_recovery,
    test_disk_watch_critical_then_recover_to_warn,
    test_disk_watch_reset,
    test_disk_watch_disabled,
    test_disk_watch_bad_input,
]


def results() -> list[tuple[str, bool, str]]:
    return _results


def run() -> tuple[int, int]:
    _results.clear()
    for fn in TESTS:
        # テスト1件の例外で残りが止まらないようにする
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
