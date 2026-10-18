# -*- coding: utf-8 -*-
"""scenes モジュールのテスト（シーンの純ロジック）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scenes import (  # noqa: E402
    DEFAULT_DURATION_MS,
    DURATION_MAX_MS,
    DURATION_MIN_MS,
    USE_GLOBAL,
    SceneTransition,
    addable_sources,
    can_remove,
    clamp_duration,
    find_transition,
    free_scene_name,
    is_fixed,
    parse_transitions,
    shows_duration,
    valid_scene_name,
)
from core.speech_format import (  # noqa: E402
    scene_created_speech,
    scene_duration_row,
    scene_no_addable_speech,
    scene_remove_warning,
    scene_removed_speech,
    scene_renamed_speech,
    scene_source_added_speech,
    scene_transition_changed_speech,
    scene_transition_row,
)

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


# 実機（OBS 32.2.2）の GetSceneTransitionList の応答をそのまま模す。
# ★カットは transitionFixed=True＝長さを変えられない
MEASURED_TRANSITIONS = [
    {"transitionConfigurable": False, "transitionFixed": True,
     "transitionKind": "cut_transition", "transitionName": "カット"},
    {"transitionConfigurable": False, "transitionFixed": False,
     "transitionKind": "fade_transition", "transitionName": "フェード"},
]


def test_parse_transitions() -> None:
    got = parse_transitions(MEASURED_TRANSITIONS)
    check("2件読める", len(got) == 2, str(got))
    check("名前", got[0].name == "カット")
    check("種別", got[0].kind == "cut_transition")
    check("カットは長さ固定", got[0].fixed is True)
    check("フェードは長さを変えられる", got[1].fixed is False)
    # 壊れた応答でも落ちない
    check("空でも落ちない", parse_transitions([]) == [])
    check("Noneでも落ちない", parse_transitions(None) == [])
    check("辞書でない要素は無視", parse_transitions(["x", 5]) == [])
    check("名前が無い要素は無視",
          parse_transitions([{"transitionKind": "x"}]) == [])


def test_find_and_fixed() -> None:
    trs = parse_transitions(MEASURED_TRANSITIONS)
    check("名前で引ける", find_transition(trs, "フェード") is not None)
    check("無い名前はNone", find_transition(trs, "無い") is None)
    check("カットは固定", is_fixed(trs, "カット"))
    check("フェードは固定でない", not is_fixed(trs, "フェード"))
    # ★分からないときは False（出して効かない方が、出さずに変えられないと
    #   思わせるよりまし）
    check("未知は固定でない扱い", not is_fixed(trs, "知らない効果"))


def test_shows_duration() -> None:
    """★長さの行は「意味を持つときだけ」出すこと。

    上書きしていないなら全体設定の話だし、カットは長さが効かない。
    出すと、変えても何も起きない行を触らせることになる。
    """
    trs = parse_transitions(MEASURED_TRANSITIONS)
    check("上書きしていなければ出さない",
          not shows_duration(trs, SceneTransition()))
    check("カットでは出さない",
          not shows_duration(trs, SceneTransition("カット", 300)))
    check("フェードでは出す",
          shows_duration(trs, SceneTransition("フェード", 300)))


def test_scene_transition_dataclass() -> None:
    check("既定は上書きなし", not SceneTransition().overridden)
    check("空文字も上書きなし", not SceneTransition(USE_GLOBAL).overridden)
    check("名前があれば上書きあり", SceneTransition("フェード").overridden)


def test_clamp_duration() -> None:
    check("範囲内はそのまま", clamp_duration(500) == 500)
    check("下限へ丸める", clamp_duration(10) == DURATION_MIN_MS)
    check("上限へ丸める", clamp_duration(99999) == DURATION_MAX_MS)
    check("小数は丸める", clamp_duration(300.6) == 301, str(clamp_duration(300.6)))
    check("読めない値は既定", clamp_duration("はやく") == DEFAULT_DURATION_MS)
    check("Noneは既定", clamp_duration(None) == DEFAULT_DURATION_MS)


def test_valid_scene_name() -> None:
    check("前後の空白を落とす", valid_scene_name("  待機  ") == "待機")
    check("中の連続空白を詰める", valid_scene_name("待機  画面") == "待機 画面")
    check("空白だけは空", valid_scene_name("   ") == "")
    check("Noneは空", valid_scene_name(None) == "")


def test_free_scene_name() -> None:
    check("空いていればそのまま", free_scene_name("待機", []) == "待機")
    check("衝突したら番号", free_scene_name("待機", ["待機"]) == "待機2")
    check("続けて衝突",
          free_scene_name("待機", ["待機", "待機2"]) == "待機3")


def test_can_remove() -> None:
    """★最後の1つは消せない。OBSのエラーではなく、こちらで理由を伝える。"""
    ok, why = can_remove(["シーン"], "シーン")
    check("最後の1つは断る", not ok)
    check("理由を返す", "最後のシーン" in why, why)
    ok2, why2 = can_remove(["A", "B"], "A")
    check("2つあれば消せる", ok2 and why2 == "")
    ok3, why3 = can_remove(["A", "B"], "無い")
    check("無いシーンは断る", not ok3)
    check("見つからない理由", "見つかりません" in why3, why3)
    check("空でも落ちない", can_remove([], "A")[0] is False)
    check("Noneでも落ちない", can_remove(None, "A")[0] is False)


def test_addable_sources() -> None:
    """既に置いてあるソースを候補に出さないこと（二重に増えるだけ）。"""
    got = addable_sources(["ゲーム音", "BGM", "カメラ"], ["ゲーム音"])
    check("置いていないものだけ", got == ["BGM", "カメラ"], str(got))
    check("全部置いてあれば空",
          addable_sources(["BGM"], ["BGM"]) == [])
    check("空でも落ちない", addable_sources([], []) == [])
    check("Noneでも落ちない", addable_sources(None, None) == [])


def test_addable_excludes_global_audio() -> None:
    """★グローバル音声デバイスを候補に出さないこと。

    OBS本体の[設定→音声]で決めるマイク・デスクトップ音声は
    シーンに属さず全シーンで常に有効。足せてしまうが、ソース一覧に
    二重に現れて「消したのに音が出る」と誤解させるだけになる。
    実測で、この環境の「マイク」がこれに当たることを確認している
    （シーンのソース一覧には現れないのに音声入力一覧には出る）。
    """
    got = addable_sources(
        ["マイク", "ゲーム音", "BGM"], [], special=["マイク"])
    check("グローバル音声を外す", "マイク" not in got, str(got))
    check("他は残る", got == ["ゲーム音", "BGM"], str(got))
    # special を渡さなくても従来どおり動く（後方互換）
    check("指定が無ければ従来どおり",
          "マイク" in addable_sources(["マイク"], []))
    check("Noneでも落ちない",
          addable_sources(["BGM"], [], None) == ["BGM"])


# ------------------------------------------------------------
# 読み上げ
# ------------------------------------------------------------
def test_created_speech() -> None:
    """★作っても現在のシーンは変わらないことを言うこと。

    切り替わったと誤解すると「配信の画面が変わった」と思わせる。
    """
    got = scene_created_speech("待機画面")
    check("名前を言う", "待機画面" in got, got)
    check("画面が変わらないと言う", "変わっていません" in got, got)
    check("次にやることを言う", "ソースを追加" in got, got)


def test_transition_rows() -> None:
    # ★「未設定」だと、効果が無いのか設定が無いのか分からない
    plain = scene_transition_row(SceneTransition())
    check("上書きなしは全体に従うと読む", "全体の設定に従う" in plain, plain)
    over = scene_transition_row(SceneTransition("フェード", 300))
    check("上書きありは効果名を読む", "フェード" in over, over)
    check("長さの行", "300ミリ秒" in scene_duration_row(
        SceneTransition("フェード", 300)))
    check("長さ未設定は既定と読む",
          "既定" in scene_duration_row(SceneTransition("フェード")))


def test_transition_changed_speech() -> None:
    back = scene_transition_changed_speech("待機", SceneTransition())
    check("解除を伝える", "全体の設定に戻しました" in back, back)
    setted = scene_transition_changed_speech(
        "待機", SceneTransition("フェード", 300))
    check("設定を伝える", "フェード" in setted, setted)


def test_remove_warning_is_explicit() -> None:
    """★何が失われるかを全部書くこと。目で確かめられない。"""
    warn = scene_remove_warning("待機画面")
    check("名前を出す", "待機画面" in warn, warn)
    check("専用ソースが消えると書く", "一緒に消えます" in warn, warn)
    check("共有ソースは残ると書く", "残ります" in warn, warn)
    check("戻せないと書く", "元に戻せません" in warn, warn)
    check("今のシーンでなければ余計に言わない",
          "今映しているシーン" not in warn, warn)
    # 今映しているシーンなら、切り替わることも伝える
    cur = scene_remove_warning("待機画面", is_current=True)
    check("今のシーンだと警告する", "今映しているシーン" in cur, cur)
    check("切り替わると伝える", "切り替わります" in cur, cur)


def test_other_speech() -> None:
    check("改名", scene_renamed_speech("A", "B") == "シーン A を B に変えました")
    check("削除", scene_removed_speech("A") == "シーン A を削除しました")
    # ★コピーではなく共有であることを伝える（知らないと戸惑う）
    added = scene_source_added_speech("待機", "マイク")
    check("共有だと伝える", "共有" in added, added)
    check("両方に効くと伝える", "両方に効きます" in added, added)
    check("追加できないとき",
          "追加できるソースがありません" in scene_no_addable_speech("待機"))


TESTS = [
    test_parse_transitions,
    test_find_and_fixed,
    test_shows_duration,
    test_scene_transition_dataclass,
    test_clamp_duration,
    test_valid_scene_name,
    test_free_scene_name,
    test_can_remove,
    test_addable_sources,
    test_addable_excludes_global_audio,
    test_created_speech,
    test_transition_rows,
    test_transition_changed_speech,
    test_remove_warning_is_explicit,
    test_other_speech,
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
