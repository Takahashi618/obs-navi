# -*- coding: utf-8 -*-
"""映像ソースの重なり順を扱う純ロジック（wx・obsws非依存）。

解く問題:
OBSは新しく作ったソースを**最前面**に置く。キャプチャーボード用の
「映像キャプチャデバイス」を作ると、信号が来ていなくてもゲームキャプチャの
手前に来てゲーム画面を覆い、配信に「ノーシグナル」が出る（実測で確認）。
毎回ソースを消して作り直さずに済むよう、重なり順で切り替えられるようにする。

★この機能は「非表示」を一切使わない。
OBSではソースを非表示にすると、そのソースの音も配信から消える。映像だと
思って非表示にしたものが実は音を運んでいた、という取り違えは、目で確認
できない利用者にとって致命的。**重なり順の変更は音に一切影響しない**ので、
この機能は set_scene_item_index だけで完結させる。安全性を「判定の正しさ」
ではなく「そもそも危険な操作を持たないこと」で担保する。
"""
from __future__ import annotations

from dataclasses import dataclass

# 切り替えの対象にしてよい種別（許可リスト）。
# 迷ったら入れない方針にする。取りこぼしても「候補に出ない」だけで済むが、
# 誤って入れると意図しないソースを前後させてしまうため。
VIDEO_KINDS = frozenset({
    "game_capture",       # ゲームキャプチャ
    "dshow_input",        # 映像キャプチャデバイス（キャプチャーボード）
    "monitor_capture",    # 画面キャプチャ
    "window_capture",     # ウィンドウキャプチャ
})

# 明確に対象外。ここに挙げたものは絶対に候補へ出さない。
NOT_SWITCHABLE_KINDS = frozenset({
    # 音声のみ
    "wasapi_input_capture",
    "wasapi_output_capture",
    "wasapi_process_output_capture",
    # 音楽用途で使われる（この環境ではBGMがこれ）。映像扱いしない
    "ffmpeg_source",
    "vlc_source",
    "slideshow",
    "slideshow_v2",
    # 重ねる装飾。切り替える対象ではない
    # ★バージョン付きの識別子は取りこぼしやすい。実機（OBS 32.2.2）の
    #   GetInputKindList で現役の綴りを確認して並べてある。落とすと
    #   「未知の種別」の枝へ落ち、絵が出ているぶん候補に混ざってしまう
    #   （テキストや画像が映像切り替えの候補に出る）
    "image_source",
    "browser_source",
    "color_source_v2",
    "color_source_v3",
    "text_gdiplus_v2",
    "text_gdiplus_v3",
    "text_ft2_source_v2",
    # グループ・入れ子シーン。中に音声を含みうるので触らない
    "OBS_SOURCE_TYPE_SCENE",
    "scene",
    "group",
})


def is_switchable(item, extra_kinds=()) -> bool:
    """このソースを重なり順の切り替え対象にしてよいか。

    判定順:
      1. 許可リスト（設定で足した種別も含む）→ 対象
      2. 明示的な対象外リスト → 対象外
      3. どちらでもない未知の種別 → 今まさに絵が出ているときだけ対象
         （プラグイン製の映像ソースを救うため。サイズ>0 は「映像がある」
           ことの証明にはなる。0 は何の証明にもならないので落とす）
    """
    kind = getattr(item, "kind", "") or ""
    if kind in VIDEO_KINDS or kind in tuple(extra_kinds or ()):
        return True
    if kind in NOT_SWITCHABLE_KINDS:
        return False
    return float(getattr(item, "source_width", 0.0) or 0.0) > 0.0


def video_items(items, extra_kinds=()) -> list:
    """切り替え対象の映像ソースだけを、渡された順のまま返す。

    commands.fetch_scene_items は手前が先頭になる順で返すので、
    そのまま一覧に出せる。
    """
    return [it for it in items or [] if is_switchable(it, extra_kinds)]


def front_index(items, extra_kinds=()) -> int:
    """映像ソースのうち一番手前の index。1つも無ければ -1。

    「絶対的な最前面」ではなくこの値を使うのが肝。画面に重ねている
    装飾（画像やブラウザ）が映像より前にある構成を壊さないため。
    """
    idx = -1
    for it in video_items(items, extra_kinds):
        idx = max(idx, int(getattr(it, "index", 0)))
    return idx


@dataclass(frozen=True)
class FrontPlan:
    """「この映像ソースを前に出す」ための計画（純データ）。"""

    item_id: int
    name: str
    kind: str
    dest_index: int
    already_front: bool
    # 前に出したときに後ろへ回る映像ソースの名前（読み上げ用）
    behind: tuple
    # 対象が今この瞬間は絵を出していない（ゲーム未起動・信号なし等）
    blank: bool


def plan_bring_to_front(items, item_id: int, extra_kinds=()) -> FrontPlan | None:
    """指定のソースを映像の最前面へ持ってくる計画を作る。

    対象が見つからない、または切り替え対象でなければ None。
    """
    targets = video_items(items, extra_kinds)
    target = next(
        (it for it in targets if int(getattr(it, "item_id", -1)) == item_id),
        None)
    if target is None:
        return None
    dest = front_index(items, extra_kinds)
    cur = int(getattr(target, "index", 0))
    behind = tuple(
        getattr(it, "name", "") for it in targets
        if int(getattr(it, "item_id", -1)) != item_id
        and int(getattr(it, "index", 0)) > cur
    )
    return FrontPlan(
        item_id=item_id,
        name=str(getattr(target, "name", "")),
        kind=str(getattr(target, "kind", "")),
        dest_index=dest,
        already_front=(cur >= dest),
        behind=behind,
        blank=float(getattr(target, "source_width", 0.0) or 0.0) <= 0.0,
    )


def first_other_index(items, extra_kinds=()) -> int:
    """一覧の初期選択位置。

    今いちばん手前にあるもの以外の先頭を選ぶ（切り替えたいのはたいてい
    「今出ていない方」なので、矢印を押す回数を減らせる）。
    """
    targets = video_items(items, extra_kinds)
    if len(targets) <= 1:
        return 0
    top = max(int(getattr(it, "index", 0)) for it in targets)
    for i, it in enumerate(targets):
        if int(getattr(it, "index", 0)) != top:
            return i
    return 0


@dataclass(frozen=True)
class LayerMove:
    """重なり順を1つ動かす計画（純データ）。"""

    item_id: int
    name: str
    new_index: int       # OBSへ渡す index。-1 なら端でこれ以上動かせない
    pos_from_front: int  # 動かしたあとの「前から数えた位置」（1始まり）
    total: int


def plan_layer_move(items, item_id: int, forward: bool) -> LayerMove | None:
    """選んでいるソースを1つ前／後ろへ動かす計画を作る。見つからなければ None。

    items は commands.fetch_scene_items の戻り（手前が先頭）。
    各要素の index は OBS の sceneItemIndex で、**大きいほど手前**。

    ★対象を映像ソースに限らない。重なり順の変更は音に一切影響しない
    （このモジュール冒頭の説明と同じ理由）ので、どのソースでも安全に
    動かせる。「映像切り替え」が許可リストで絞っているのは、
    あちらが「今どれを映すか」を選ぶ操作で、候補を間違えると
    意図しないものが前に出てしまうため。ここは利用者が一覧で選んだ
    1つを1段だけ動かすので、その心配が無い。
    """
    rows = list(items or [])
    total = len(rows)
    target = next(
        (it for it in rows if int(getattr(it, "item_id", -1)) == item_id),
        None)
    if target is None:
        return None
    name = str(getattr(target, "name", ""))
    cur = int(getattr(target, "index", 0))
    dest = cur + 1 if forward else cur - 1
    if dest < 0 or dest > total - 1:
        # 端。今の位置を添えて「もう動かせない」と言えるようにする
        return LayerMove(item_id, name, -1, total - cur, total)
    return LayerMove(item_id, name, dest, total - dest, total)
