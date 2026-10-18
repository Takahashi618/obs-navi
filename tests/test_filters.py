# -*- coding: utf-8 -*-
"""filters モジュールのテスト（音声フィルターの設定項目の表と純ロジック）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filters import (  # noqa: E402
    AUDIO_FILTER_KINDS,
    FILTER_TABLE,
    RECOMMENDED_FIRST,
    SIDECHAIN_NONE,
    FilterProp,
    choice_label,
    clamp,
    free_filter_name,
    is_known_kind,
    merge_defaults,
    specs_for_kind,
    visible_specs,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# 実機（OBS 32.2.2）の GetSourceFilterDefaultSettings で実測した既定値。
# 表のキーがこれと食い違っていたら、書いても効かない設定を書くことになる。
MEASURED_DEFAULTS = {
    "noise_suppress_filter_v2": {"method": "rnnoise", "suppress_level": -30},
    "noise_gate_filter": {
        "attack_time": 25, "close_threshold": -32.0, "hold_time": 200,
        "open_threshold": -26.0, "release_time": 150},
    "compressor_filter": {
        "attack_time": 6, "output_gain": 0.0, "ratio": 10.0,
        "release_time": 60, "sidechain_source": "none", "threshold": -18.0},
    "upward_compressor_filter": {
        "attack_time": 10, "detector": "RMS", "knee_width": 10,
        "output_gain": 0.0, "ratio": 0.5, "release_time": 50,
        "threshold": -20.0},
    "limiter_filter": {"release_time": 60, "threshold": -6.0},
    "expander_filter": {
        "attack_time": 10, "detector": "RMS", "output_gain": 0.0,
        "presets": "expander", "ratio": 2.0, "release_time": 50,
        "threshold": -40.0},
    "gain_filter": {"db": 0.0},
    "basic_eq_filter": {"high": 0.0, "low": 0.0, "mid": 0.0},
    "invert_polarity_filter": {},
}


def test_table_keys_match_obs() -> None:
    """★表のキーが実機の既定設定に実在すること。

    props.py と同じ方針。推測でキーを書くと overlay=True で
    「誰も読まない設定キー」を書き込む事故になる。ここが番人。
    """
    for kind, defaults in MEASURED_DEFAULTS.items():
        specs = specs_for_kind(kind)
        for spec in specs:
            check(f"{kind} の {spec.key} は実在するキー",
                  spec.key in defaults,
                  f"実測の既定={sorted(defaults)}")


def test_every_addable_kind_is_in_table() -> None:
    """追加できる種別は必ず表にあること。

    追加はできるのに設定を開けない種別があると、足したあとで詰む。
    """
    for info in AUDIO_FILTER_KINDS:
        check(f"{info.kind} が表にある", is_known_kind(info.kind))
        check(f"{info.kind} に説明がある", bool(info.label))
    check("おすすめの既定が候補に含まれる",
          any(i.kind == RECOMMENDED_FIRST for i in AUDIO_FILTER_KINDS))


def test_addable_kinds_exclude_broken() -> None:
    """★作れないもの・扱えないものを候補に出さないこと。

    async_delay_filter は CreateSourceFilter で作ろうとしても作られない
    （エラーも出ずに一覧へ現れない）ことを実機で確認した。
    vst_filter はプラグインの状態を持つのでこのアプリでは扱えない。
    候補に出すと「選んでも何も起きない」機能になる。
    """
    kinds = [i.kind for i in AUDIO_FILTER_KINDS]
    check("音声遅延は候補に出さない", "async_delay_filter" not in kinds)
    check("VSTは候補に出さない", "vst_filter" not in kinds)


def test_specs_for_unknown_kind() -> None:
    check("未知の種別は空", specs_for_kind("なにか") == [])
    check("未知の種別は表に無い", not is_known_kind("なにか"))
    # ★空リストは2つの意味を持つので、表にあることと区別できること
    check("位相反転は表にあるが項目0",
          is_known_kind("invert_polarity_filter")
          and specs_for_kind("invert_polarity_filter") == [])


def test_visible_specs_depends_on() -> None:
    """効かない項目を一覧に出さないこと。

    ノイズ抑制の抑制レベルは方式が speex のときしか効かない。
    出すと「変えても何も起きない行」を触らせることになる。
    """
    kind = "noise_suppress_filter_v2"
    rnn = [s.key for s in visible_specs(kind, {"method": "rnnoise"})]
    check("rnnoiseでは抑制レベルを出さない", "suppress_level" not in rnn,
          str(rnn))
    check("方式は常に出す", "method" in rnn, str(rnn))
    spx = [s.key for s in visible_specs(kind, {"method": "speex"})]
    check("speexでは抑制レベルを出す", "suppress_level" in spx, str(spx))
    # 条件を持たない項目はそのまま出る
    comp = [s.key for s in visible_specs("compressor_filter", {})]
    check("条件の無い項目は常に出る", "ratio" in comp, str(comp))


def test_clamp() -> None:
    f = FilterProp("ratio", "比率", "float", min_value=1.0, max_value=32.0)
    check("範囲内はそのまま", clamp(f, 10.0) == 10.0)
    check("上限を超えたら丸める", clamp(f, 99.0) == 32.0)
    check("下限を下回ったら丸める", clamp(f, 0.0) == 1.0)
    i = FilterProp("attack_time", "速さ", "int", min_value=1, max_value=500)
    check("intは整数になる", clamp(i, 25.7) == 26, str(clamp(i, 25.7)))
    check("intの型はint", isinstance(clamp(i, 25.7), int))
    # 数値でないものは触らない（選択肢やソース名を壊さない）
    c = FilterProp("method", "方式", "choice")
    check("選択肢は丸めない", clamp(c, "speex") == "speex")
    check("数値にできない値はそのまま", clamp(f, "あ") == "あ")
    check("NaNは下限へ", clamp(f, float("nan")) == 1.0)


def test_choice_label() -> None:
    spec = next(s for s in specs_for_kind("noise_suppress_filter_v2")
                if s.key == "method")
    check("既知の値は日本語", "品質" in choice_label(spec, "rnnoise"),
          choice_label(spec, "rnnoise"))
    check("未知の値はそのまま", choice_label(spec, "nvafx") == "nvafx")


def test_merge_defaults() -> None:
    """★作った直後の設定は空の辞書で返る（実測）。既定とのマージが要る。"""
    defaults = {"method": "rnnoise", "suppress_level": -30}
    check("空なら既定がそのまま",
          merge_defaults(defaults, {}) == defaults)
    check("現在値が既定を上書き",
          merge_defaults(defaults, {"method": "speex"})["method"] == "speex")
    check("上書きしない項目は既定のまま",
          merge_defaults(defaults, {"method": "speex"})["suppress_level"]
          == -30)
    check("どちらもNoneでも落ちない", merge_defaults(None, None) == {})
    # 元の辞書を書き換えないこと（既定値を汚すと次の表示が狂う）
    merge_defaults(defaults, {"method": "speex"})
    check("既定の辞書を壊さない", defaults["method"] == "rnnoise")


def test_free_filter_name() -> None:
    check("空いていればそのまま",
          free_filter_name("ノイズ抑制", []) == "ノイズ抑制")
    check("衝突したら番号を足す",
          free_filter_name("ノイズ抑制", ["ノイズ抑制"]) == "ノイズ抑制2")
    check("続けて衝突したら次の番号",
          free_filter_name("ノイズ抑制", ["ノイズ抑制", "ノイズ抑制2"])
          == "ノイズ抑制3")


def test_sidechain_none() -> None:
    """サイドチェーンの「なし」は OBS 側の実測値と一致すること。"""
    check("noneが既定値と一致",
          MEASURED_DEFAULTS["compressor_filter"]["sidechain_source"]
          == SIDECHAIN_NONE)


def test_choice_labels_have_no_comma() -> None:
    """★選択肢のラベルに読点を入れないこと。

    一覧の行は「ラベル、値」の形なので、値に読点が入ると区切りが
    分からなくなる（「方式、標準、品質重視」が3項目に聞こえる）。
    props.py の PRIORITY_JP が同じ理由で読点を避けており、
    その落とし穴をここで踏み直さないための番人。
    """
    for kind, specs in FILTER_TABLE.items():
        for spec in specs:
            for _value, label in spec.choices:
                check(f"{kind}.{spec.key} の選択肢に読点が無い",
                      "、" not in label and "," not in label, label)


def test_table_has_labels_and_units() -> None:
    """全項目に日本語ラベルがあること（読み上げ名になるので必須）。"""
    for kind, specs in FILTER_TABLE.items():
        for spec in specs:
            check(f"{kind}.{spec.key} にラベルがある", bool(spec.label))
            if spec.type in ("float", "int"):
                check(f"{kind}.{spec.key} に範囲がある",
                      spec.max_value > spec.min_value,
                      f"{spec.min_value}〜{spec.max_value}")
            if spec.type == "choice":
                check(f"{kind}.{spec.key} に選択肢がある", bool(spec.choices))


TESTS = [
    test_table_keys_match_obs,
    test_every_addable_kind_is_in_table,
    test_addable_kinds_exclude_broken,
    test_specs_for_unknown_kind,
    test_visible_specs_depends_on,
    test_clamp,
    test_choice_label,
    test_merge_defaults,
    test_free_filter_name,
    test_sidechain_none,
    test_choice_labels_have_no_comma,
    test_table_has_labels_and_units,
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
