# -*- coding: utf-8 -*-
"""全テストをまとめて実行し、結果を UTF-8 ファイルへ書き出す。

標準出力は ASCII のみ（cp932 環境での文字化けを避ける）。
詳細は tests/_last_run.txt に日本語で残す。
"""
from __future__ import annotations

import os
import sys

# 読み上げを無効化してからテスト対象を import する
os.environ["OBSNAVI_SILENT"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_commands  # noqa: E402
import test_config  # noqa: E402
import test_hotkeys  # noqa: E402
import test_keymap  # noqa: E402
import test_levels  # noqa: E402
import test_ordering  # noqa: E402
import test_camera  # noqa: E402
import test_filters  # noqa: E402
import test_props  # noqa: E402
import test_recording  # noqa: E402
import test_scenes  # noqa: E402
import test_setup  # noqa: E402
import test_sources  # noqa: E402
import test_video  # noqa: E402
import test_speech  # noqa: E402
import test_speech_format  # noqa: E402
import test_tracks  # noqa: E402
import test_volume  # noqa: E402

MODULES = [
    ("levels", test_levels),
    ("ordering", test_ordering),
    ("speech", test_speech),
    ("speech_format", test_speech_format),
    ("config", test_config),
    ("commands", test_commands),
    ("setup", test_setup),
    ("hotkeys", test_hotkeys),
    ("volume", test_volume),
    ("props", test_props),
    ("video", test_video),
    ("recording", test_recording),
    ("filters", test_filters),
    ("camera", test_camera),
    ("sources", test_sources),
    ("scenes", test_scenes),
    ("keymap", test_keymap),
    ("tracks", test_tracks),
]


def main() -> int:
    lines: list[str] = []
    total_pass = 0
    total_fail = 0
    for label, mod in MODULES:
        # モジュールが例外で死んでも、他のモジュールの実行と
        # _last_run.txt の書き出しは続ける（失敗は1件として計上する）
        try:
            p, f = mod.run()
            mod_results = mod.results()
        except Exception as exc:  # noqa: BLE001
            p, f = 0, 1
            mod_results = [
                (f"{label} モジュールが例外で停止", False, repr(exc))]
        total_pass += p
        total_fail += f
        lines.append(f"=== {label}: {p} passed, {f} failed ===")
        for nm, ok, detail in mod_results:
            mark = "OK" if ok else "NG"
            line = f"[{mark}] {nm}"
            if not ok and detail:
                line += f" -> {detail}"
            lines.append(line)
        lines.append("")

    lines.append(f"合計: {total_pass} passed, {total_fail} failed")
    out_path = os.path.join(HERE, "_last_run.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # stdout は ASCII のみ
    print(f"[run_tests] total={total_pass + total_fail} "
          f"pass={total_pass} fail={total_fail}")
    print(f"[run_tests] detail -> {out_path}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
