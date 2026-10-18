# -*- coding: utf-8 -*-
"""sources モジュールのテスト（作れるソースの表と純ロジック）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import props  # noqa: E402
from core.sources import (  # noqa: E402
    CREATABLE_KINDS,
    free_source_name,
    is_audio_only,
    is_creatable,
    kind_by_id,
    valid_source_name,
)
from core.speech_format import (  # noqa: E402
    source_kind_row,
    source_created_speech,
    source_remove_warning,
    source_removed_speech,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# 実機（OBS 32.2.2）の GetInputKindList で実測した、作れる種別の全部。
# ★バージョン付きの綴りを取り違えると「作れない種別」を候補に出すことに
#   なるので、実測値をそのまま置いて突き合わせる。
MEASURED_KINDS = {
    "image_source", "color_source_v3", "slideshow_v2", "browser_source",
    "ffmpeg_source", "text_gdiplus_v3", "text_ft2_source_v2", "vlc_source",
    "monitor_capture", "window_capture", "game_capture", "dshow_input",
    "wasapi_input_capture", "wasapi_output_capture",
    "wasapi_process_output_capture",
}


def test_kinds_exist_in_obs() -> None:
    """★候補に出す種別が、実機に本当に存在すること。

    綴りを間違えると（text_gdiplus_v2 と v3 など）、選んでも作成に
    失敗する候補になる。
    """
    for info in CREATABLE_KINDS:
        check(f"{info.kind} は実機に存在する",
              info.kind in MEASURED_KINDS, info.kind)


def test_creatable_kinds_are_configurable() -> None:
    """★作れる種別は、必ず設定もできること。

    作れても中身を設定できない種別を出すと、「足したのに使えないソース」
    がシーンに残るだけになる（カメラは機材を選ばないと何も映らない）。
    """
    for info in CREATABLE_KINDS:
        specs = props.specs_for_kind(info.kind)
        check(f"{info.kind} に設定項目がある", bool(specs), str(specs))
        # 「これを設定しないと使えない」項目が、実際に表にあること
        if info.needs:
            keys = [s.key for s in specs]
            check(f"{info.kind} の {info.needs} が設定できる",
                  info.needs in keys, str(keys))


def test_kinds_have_labels_and_hints() -> None:
    """名前と用途の説明が全部にあること（種別名だけでは選べない）。"""
    seen_labels = set()
    for info in CREATABLE_KINDS:
        check(f"{info.kind} に名前がある", bool(info.label))
        check(f"{info.kind} に説明がある", bool(info.hint))
        # 既定の名前に使うので、重複していると毎回リネームが要る
        check(f"{info.label} は重複しない", info.label not in seen_labels,
              info.label)
        seen_labels.add(info.label)


def test_kind_lookup() -> None:
    got = kind_by_id("dshow_input")
    check("識別子から引ける", got is not None and got.label == "カメラ",
          str(got))
    check("未知は None", kind_by_id("なにか") is None)
    check("作れる判定", is_creatable("dshow_input"))
    check("作れない判定", not is_creatable("なにか"))
    # 表に無い種別（スライドショーなど）は候補に出していない
    check("スライドショーは候補外", not is_creatable("slideshow_v2"))


def test_audio_only() -> None:
    check("アプリの音は音声のみ",
          is_audio_only("wasapi_process_output_capture"))
    check("マイクは音声のみ", is_audio_only("wasapi_input_capture"))
    check("カメラは音声のみではない", not is_audio_only("dshow_input"))


def test_free_source_name() -> None:
    check("空いていればそのまま", free_source_name("カメラ", []) == "カメラ")
    check("衝突したら番号", free_source_name("カメラ", ["カメラ"]) == "カメラ2")
    check("続けて衝突",
          free_source_name("カメラ", ["カメラ", "カメラ2"]) == "カメラ3")


def test_valid_source_name() -> None:
    check("前後の空白を落とす", valid_source_name("  カメラ  ") == "カメラ")
    check("中の連続空白は詰める", valid_source_name("カ  メ ラ") == "カ メ ラ")
    check("空白だけは空", valid_source_name("   ") == "")
    check("Noneは空", valid_source_name(None) == "")
    # 記号は落とさない（OBSは名前をほとんど制限しない）
    check("記号は残す", valid_source_name("BGM #2") == "BGM #2")


def test_speech_rows() -> None:
    info = kind_by_id("dshow_input")
    row = source_kind_row(info)
    check("名前を読む", "カメラ" in row, row)
    check("用途を読む", "ウェブカメラ" in row, row)


def test_created_speech_leads_to_settings() -> None:
    """★作っただけでは使えない種類は、次に何をするかまで言うこと。"""
    cam = source_created_speech("ウェブカメラ", kind_by_id("dshow_input"),
                                "シーン")
    check("どこに作ったか言う", "シーン" in cam, cam)
    check("名前を言う", "ウェブカメラ" in cam, cam)
    check("設定へ進むと言う", "設定を開きます" in cam, cam)
    # 設定が要らない種類（単色の背景）では余計なことを言わない
    color = source_created_speech("背景", kind_by_id("color_source_v3"),
                                  "シーン")
    check("不要なら設定の案内はしない",
          "設定を開きます" not in color, color)


def test_remove_warning_is_explicit() -> None:
    """★削除の確認は、何が起きるかを全部書くこと。

    入力の削除は「このシーンから外す」ではなく全シーンから消える。
    目で確かめられない以上、言葉で伝えるしかない。
    """
    warn = source_remove_warning("マイク")
    check("名前を出す", "マイク" in warn, warn)
    check("全シーンから消えると書く", "すべてのシーン" in warn, warn)
    check("戻せないと書く", "元に戻せません" in warn, warn)
    # 設定で使っているソースなら、それも伝える
    used = source_remove_warning("BGM", ["BGM", "ゲーム切り替えの音声"])
    check("役割を伝える", "BGM" in used and "ゲーム切り替えの音声" in used, used)
    check("機能が止まると伝える", "動かなくなります" in used, used)
    check("役割が無ければ言わない",
          "使っています" not in warn, warn)


def test_removed_speech() -> None:
    check("削除を伝える", source_removed_speech("カメラ") == "カメラ を削除しました")


TESTS = [
    test_kinds_exist_in_obs,
    test_creatable_kinds_are_configurable,
    test_kinds_have_labels_and_hints,
    test_kind_lookup,
    test_audio_only,
    test_free_source_name,
    test_valid_source_name,
    test_speech_rows,
    test_created_speech_leads_to_settings,
    test_remove_warning_is_explicit,
    test_removed_speech,
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
