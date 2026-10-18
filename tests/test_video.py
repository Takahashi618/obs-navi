# -*- coding: utf-8 -*-
"""映像ソースの重なり順ロジックのテスト。

実測に基づく前提:
- 新しく作った映像ソースは最前面(index が最大)に入る
- ゲームが起動していないゲームキャプチャは sourceWidth=0（絵が出ていない）
  ＝サイズでは「映像ソースかどうか」を判定できない
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import speech_format, video  # noqa: E402
from core.state import SceneItem  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def item(iid, name, kind, index, width=0.0, enabled=True):
    return SceneItem(item_id=iid, name=name, kind=kind, index=index,
                     enabled=enabled, source_width=width)


# 利用者の実際のシーン構成（手前が先頭＝fetch_scene_items の並び）＋
# キャプチャーボード用の映像キャプチャを足した状態
SCENE = [
    item(6, "映像キャプチャ", "dshow_input", 5),        # 最前面・信号なし
    item(5, "BGM", "ffmpeg_source", 4),                 # 音楽（音声のみ）
    item(4, "NVDA音声", "wasapi_input_capture", 3),
    item(3, "PC-Talker音声", "wasapi_process_output_capture", 2),
    item(2, "ゲーム音", "wasapi_process_output_capture", 1),
    item(1, "ゲームキャプチャ", "game_capture", 0),      # 最背面
]


def test_is_switchable() -> None:
    check("ゲームキャプチャは対象",
          video.is_switchable(item(1, "g", "game_capture", 0)) is True)
    check("映像キャプチャデバイスは対象",
          video.is_switchable(item(1, "d", "dshow_input", 0)) is True)
    check("画面キャプチャは対象",
          video.is_switchable(item(1, "m", "monitor_capture", 0)) is True)
    # ★音声を運ぶものは絶対に対象にしない（非表示にすると音が消えるため）
    for kind in ("wasapi_input_capture", "wasapi_output_capture",
                 "wasapi_process_output_capture"):
        check(f"{kind} は対象外",
              video.is_switchable(item(1, "a", kind, 0)) is False)
    # BGMがこれ。音楽用途なので映像扱いしない
    check("ffmpeg_source は対象外",
          video.is_switchable(item(1, "BGM", "ffmpeg_source", 0)) is False)
    check("vlc_source は対象外",
          video.is_switchable(item(1, "v", "vlc_source", 0)) is False)
    check("グループは対象外",
          video.is_switchable(item(1, "G", "OBS_SOURCE_TYPE_SCENE", 0)) is False)
    check("装飾（画像）は対象外",
          video.is_switchable(item(1, "i", "image_source", 0)) is False)
    # 未知の種別は「今絵が出ている」ときだけ救う
    check("未知でサイズ0なら対象外",
          video.is_switchable(item(1, "x", "plugin_thing", 0, 0.0)) is False)
    check("未知でも絵が出ていれば対象",
          video.is_switchable(item(1, "x", "plugin_thing", 0, 1920.0)) is True)
    # 設定で足せる
    check("extra_kinds で足せる",
          video.is_switchable(item(1, "x", "ndi_source", 0),
                              ("ndi_source",)) is True)


def test_video_items_excludes_audio() -> None:
    got = video.video_items(SCENE)
    names = [i.name for i in got]
    check("映像だけが残る", names == ["映像キャプチャ", "ゲームキャプチャ"], str(names))
    # ★音声ソースが1つでも混ざったら音が消える事故になる
    for bad in ("BGM", "ゲーム音", "PC-Talker音声", "NVDA音声"):
        check(f"{bad} を含まない", bad not in names)


def test_front_index() -> None:
    # 映像の最前面は 5（映像キャプチャ）。BGM(index=4)は映像ではないので
    # 数えない
    check("映像の最前面", video.front_index(SCENE) == 5,
          str(video.front_index(SCENE)))
    check("映像が無ければ-1",
          video.front_index([item(1, "a", "wasapi_input_capture", 0)]) == -1)


def test_plan_bring_to_front() -> None:
    # ゲームキャプチャ(最背面)を前に出す＝利用者の目的そのもの
    plan = video.plan_bring_to_front(SCENE, 1)
    check("計画が作れる", plan is not None)
    check("名前", plan.name == "ゲームキャプチャ", plan.name)
    check("移動先は映像の最前面", plan.dest_index == 5, str(plan.dest_index))
    check("まだ最前面ではない", plan.already_front is False)
    check("後ろに回るのは映像キャプチャ",
          plan.behind == ("映像キャプチャ",), str(plan.behind))
    check("今は映っていない（ゲーム未起動）", plan.blank is True)
    # すでに最前面のものを選んだ場合
    plan2 = video.plan_bring_to_front(SCENE, 6)
    check("最前面なら already_front", plan2.already_front is True)
    # 音声ソースは計画を作れない（安全側）
    check("音声ソースは対象外でNone",
          video.plan_bring_to_front(SCENE, 5) is None)
    check("存在しないIDはNone", video.plan_bring_to_front(SCENE, 999) is None)


def test_first_other_index() -> None:
    # 今いちばん手前(映像キャプチャ)ではない方を初期選択にする
    idx = video.first_other_index(SCENE)
    targets = video.video_items(SCENE)
    check("初期選択は最前面以外",
          targets[idx].name == "ゲームキャプチャ", targets[idx].name)
    check("1つしかなければ0",
          video.first_other_index(
              [item(1, "g", "game_capture", 0)]) == 0)


def test_speech() -> None:
    # ★「いま映っています」と断定しない（最前面でも絵が無いことがある）
    label = speech_format.video_item_label("ゲームキャプチャ", 0, 5, True)
    check("位置を伝える", "後ろ" in label, label)
    check("映っていないことを伝える", "今は映っていません" in label, label)
    check("断定しない", "いま映っています" not in label, label)
    top = speech_format.video_item_label("映像キャプチャ", 5, 5, False)
    check("前面を伝える", "前面" in top, top)

    plan = video.plan_bring_to_front(SCENE, 1)
    s = speech_format.video_front_speech(plan)
    check("前に出したことを言う", "ゲームキャプチャ を前に出しました" in s, s)
    check("後ろに回ったものを言う", "映像キャプチャ" in s, s)
    check("映っていない注意を言う", "映っていません" in s, s)

    check("すでに前面",
          "すでに" in speech_format.video_already_front_speech("X"))
    check("失敗の警告",
          "受け付けていません" in speech_format.video_unchanged_speech("X"))
    check("候補なしの案内",
          "映像ソースがありません" in speech_format.video_none_speech())


def test_scene_item_parses_size() -> None:
    """fetch_scene_items が映像サイズを拾えること（無くても壊れない）。"""
    from types import SimpleNamespace

    from core import commands

    class C:
        def get_scene_item_list(self, scene):
            return SimpleNamespace(scene_items=[
                {"sceneItemId": 1, "sourceName": "ゲームキャプチャ",
                 "inputKind": "game_capture", "sceneItemIndex": 0,
                 "sceneItemEnabled": True,
                 "sceneItemTransform": {"sourceWidth": 1920.0,
                                        "sourceHeight": 1080.0}},
                # transform が無い応答でも落ちないこと
                {"sceneItemId": 2, "sourceName": "音", "sceneItemIndex": 1,
                 "inputKind": "wasapi_input_capture",
                 "sceneItemEnabled": True},
            ])

    items = commands.fetch_scene_items(C(), "シーン")
    by_name = {i.name: i for i in items}
    check("サイズを拾う", by_name["ゲームキャプチャ"].source_width == 1920.0,
          str(by_name["ゲームキャプチャ"].source_width))
    check("transform無しは0", by_name["音"].source_width == 0.0)


def test_plan_layer_move() -> None:
    """重なり順を1段動かす計画。index が大きいほど手前。"""
    items = [
        SceneItem(3, "前", index=2),
        SceneItem(2, "中", index=1),
        SceneItem(1, "後", index=0),
    ]
    plan = video.plan_layer_move(items, 2, True)
    check("前へ1段", plan.new_index == 2, str(plan))
    check("前から数えた位置", plan.pos_from_front == 1, str(plan))
    check("総数", plan.total == 3, str(plan))
    plan = video.plan_layer_move(items, 2, False)
    check("後ろへ1段", plan.new_index == 0, str(plan))
    check("後ろへ動かした位置", plan.pos_from_front == 3, str(plan))
    # 端はこれ以上動かさない（今の位置は答える）
    plan = video.plan_layer_move(items, 3, True)
    check("最前面より前へは動かさない", plan.new_index == -1, str(plan))
    check("端でも今の位置は分かる", plan.pos_from_front == 1, str(plan))
    plan = video.plan_layer_move(items, 1, False)
    check("最背面より後ろへは動かさない", plan.new_index == -1, str(plan))
    check("無いソースは None", video.plan_layer_move(items, 99, True) is None)
    # ★映像かどうかで絞らない（重なり順は音に影響しないので安全）
    items = [SceneItem(9, "テキスト", kind="text_gdiplus_v2", index=1),
             SceneItem(8, "マイク", kind="wasapi_input_capture", index=0)]
    check("種別で弾かない", video.plan_layer_move(items, 8, True).new_index == 1,
          str(video.plan_layer_move(items, 8, True)))


def run() -> tuple[int, int]:
    for fn in (
        test_plan_layer_move,
        test_is_switchable,
        test_video_items_excludes_audio,
        test_front_index,
        test_plan_bring_to_front,
        test_first_other_index,
        test_speech,
        test_scene_item_parses_size,
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
    print(f"video: {p} passed, {f} failed")
