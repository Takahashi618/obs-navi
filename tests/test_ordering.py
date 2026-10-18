# -*- coding: utf-8 -*-
"""ordering モジュールのテスト（一覧の並び順の純ロジック）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ordering import (  # noqa: E402
    apply_order,
    apply_order_by,
    default_label,
    default_rows,
    is_default,
    move,
    order_for_edit,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_apply_order_basics() -> None:
    names = ["マイク", "ゲーム音", "BGM"]
    check("設定なしは元の並びのまま",
          apply_order(names) == names, str(apply_order(names)))
    check("設定なし＋名前順",
          apply_order(names, sort_rest=True) == sorted(names),
          str(apply_order(names, sort_rest=True)))
    got = apply_order(names, ["ゲーム音"])
    check("設定の分が先", got[0] == "ゲーム音", str(got))
    check("残りは元の並びのまま", got[1:] == ["マイク", "BGM"], str(got))
    got = apply_order(names, ["ゲーム音"], sort_rest=True)
    check("残りを名前順にもできる", got == ["ゲーム音", "BGM", "マイク"], str(got))


def test_apply_order_keeps_everything() -> None:
    """設定に載っていないものを落とさない（このモジュールの一番の約束）。"""
    names = ["マイク", "新入り"]
    got = apply_order(names, ["マイク"])
    check("設定に無いものも必ず出す", got == ["マイク", "新入り"], str(got))
    got = apply_order(["マイク"], ["消えたソース", "マイク"])
    check("今無い名前は出さない", got == ["マイク"], str(got))


def test_apply_order_by_key() -> None:
    """同名が複数あっても落とさない（OBSは同じソースを1シーンに2回置ける）。"""
    class Row:
        def __init__(self, name, tag):
            self.name = name
            self.tag = tag

        def __repr__(self):
            return f"{self.name}:{self.tag}"

    rows = [Row("画像", "a"), Row("ゲーム", "b"), Row("画像", "c")]
    got = apply_order_by(rows, ["画像"], key=lambda r: r.name)
    check("同名を2つとも前へ出す",
          [r.tag for r in got] == ["a", "c", "b"], str(got))
    check("件数が変わらない", len(got) == len(rows), str(got))


def test_order_for_edit() -> None:
    names = ["マイク", "ゲーム音", "BGM"]
    saved = ["ゲーム音", "消えたソース", "マイク"]
    rows = order_for_edit(names, saved)
    check("保存済みの並びを位置ごと保つ",
          rows[:3] == ["ゲーム音", "消えたソース", "マイク"], str(rows))
    check("保存に無いものを後ろへ", rows[3] == "BGM", str(rows))
    # ★開いてそのまま保存しても並びが変わらないこと
    check("再度かけても同じ", order_for_edit(names, rows) == rows, str(rows))
    check("重複は1つに",
          order_for_edit(["A"], ["A", "A"]) == ["A"],
          str(order_for_edit(["A"], ["A", "A"])))
    rows = order_for_edit(names, [], sort_rest=True)
    check("保存が空なら残りの並べ方に従う", rows == sorted(names), str(rows))


def test_default_rows() -> None:
    """「戻す」先の並び。同じ名前は1つにまとめる。"""
    names = ["前面", "中間", "背面"]
    check("OBSの順そのまま", default_rows(names) == names, str(default_rows(names)))
    check("名前順にもできる",
          default_rows(names, sort_rest=True) == sorted(names),
          str(default_rows(names, sort_rest=True)))
    # ★同じソースを1シーンに2回置ける。まとめないと戻すたびに行が増える
    got = default_rows(["画像", "テロップ", "画像"])
    check("同名は1つにまとめる", got == ["画像", "テロップ"], str(got))
    check("空や None を落とす", default_rows(["A", "", None]) == ["A"],
          str(default_rows(["A", "", None])))


def test_is_default() -> None:
    """既定と同じなら設定は空で保存してよい（＝以後も追従する）。"""
    names = ["前面", "中間", "背面"]
    check("そのままなら既定", is_default(names, names))
    check("入れ替えたら既定でない",
          not is_default(["中間", "前面", "背面"], names))
    check("名前順の画面では名前順が既定",
          is_default(sorted(names), names, sort_rest=True))
    check("名前順の画面でOBS順は既定でない",
          not is_default(names, names, sort_rest=True))
    check("同名を含んでいても既定と一致",
          is_default(["画像", "テロップ"], ["画像", "テロップ", "画像"]))


def test_default_rows_matches_empty_config() -> None:
    """★「戻す」先と、設定が空のときの初期表示は必ず同じでなければならない。

    ずれると「戻したのに順番が変わらない」（あるいは戻したのに保存が
    空にならない）が起きる。実装が委譲であることをここで固定する。
    """
    cases = (
        ["マイク", "BGM", "マイク", "", "ゲーム音"],
        [],
        ["A"],
    )
    for names in cases:
        for sort_rest in (False, True):
            check(f"既定＝空設定の初期表示 {names} {sort_rest}",
                  default_rows(names, sort_rest)
                  == order_for_edit(names, (), sort_rest),
                  str(default_rows(names, sort_rest)))


def test_default_label() -> None:
    """既定の並びの呼び名は1か所から出す（場面ごとに割れないように）。"""
    check("名前順", default_label(True) == "名前順", default_label(True))
    check("OBS順", default_label(False) == "OBSと同じ順", default_label(False))


def test_move() -> None:
    rows = ["A", "B", "C"]
    check("下へ", move(rows, 0, 1) == 1 and rows == ["B", "A", "C"], str(rows))
    check("上へ", move(rows, 1, -1) == 0 and rows == ["A", "B", "C"], str(rows))
    check("先頭より上へは動かさない", move(rows, 0, -1) == -1, str(rows))
    check("末尾より下へは動かさない", move(rows, 2, 1) == -1, str(rows))
    check("範囲外は動かさない", move(rows, 9, 1) == -1, str(rows))
    check("失敗しても中身は変わらない", rows == ["A", "B", "C"], str(rows))


def run() -> tuple[int, int]:
    for fn in (
        test_apply_order_basics,
        test_apply_order_keeps_everything,
        test_apply_order_by_key,
        test_order_for_edit,
        test_default_rows,
        test_default_rows_matches_empty_config,
        test_default_label,
        test_is_default,
        test_move,
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
    print(f"ordering: {p} passed, {f} failed")
