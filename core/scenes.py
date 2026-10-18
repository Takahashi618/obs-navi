# -*- coding: utf-8 -*-
"""シーンの作成・設定まわりの純ロジック（wx・obsws非依存）。

扱うのは3つ。

1. 名前の付け方（重複を避ける）
2. シーンごとのトランジション（切り替え効果）の上書き設定
3. 削除してよいかの判定

★シーンごとのトランジションについて（実測で確認、2026-08-27）
OBS には「全体のトランジション」と「このシーンへ切り替えるときだけ使う
トランジション」がある。後者が**オーバーライド**で、設定されていなければ
name も duration も None が返る（＝全体の設定に従う）。
`SetSceneSceneTransitionOverride` に None を渡すと解除できる。

★トランジションには「長さを変えられないもの」がある。
実測では「カット」が transitionFixed=True で、長さの指定が効かない。
長さの行を出してしまうと、変えても何も起きない項目を触らせることになる
（filters.visible_specs と同じ考え方で、意味を持つときだけ出す）。
"""
from __future__ import annotations

from dataclasses import dataclass

# OBSがトランジションの長さとして受け付ける範囲（obs-websocket の仕様）
DURATION_MIN_MS = 50
DURATION_MAX_MS = 20000
DEFAULT_DURATION_MS = 300

# 「このシーン専用の設定を使わない」を表す値。OBS へは None を送る。
USE_GLOBAL = ""


@dataclass(frozen=True)
class Transition:
    """使えるトランジション1つ（純データ）。"""

    name: str
    kind: str = ""
    # ★長さを変えられないもの（カットなど）。True なら長さの行を出さない
    fixed: bool = False


@dataclass
class SceneTransition:
    """シーンごとのトランジション設定。

    name が空なら「全体の設定に従う」（＝オーバーライドなし）。
    """

    name: str = USE_GLOBAL
    duration_ms: int | None = None

    @property
    def overridden(self) -> bool:
        return bool(self.name)


def parse_transitions(items) -> list[Transition]:
    """GetSceneTransitionList の応答をトランジションの並びにする。"""
    out: list[Transition] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("transitionName", "") or "")
        if not name:
            continue
        out.append(Transition(
            name=name,
            kind=str(it.get("transitionKind", "") or ""),
            fixed=bool(it.get("transitionFixed", False)),
        ))
    return out


def find_transition(transitions, name: str) -> Transition | None:
    """名前からトランジションを引く。無ければ None。"""
    for t in transitions or []:
        if t.name == name:
            return t
    return None


def is_fixed(transitions, name: str) -> bool:
    """そのトランジションは長さを変えられないか。

    分からないときは False（＝長さの行を出す）。出して効かないより、
    出さずに変えられないと思わせる方が困るため。
    """
    found = find_transition(transitions, name)
    return bool(found.fixed) if found is not None else False


def shows_duration(transitions, current: SceneTransition) -> bool:
    """長さの行を出すべきか。

    オーバーライドしていないなら全体の設定の話なのでここでは出さない。
    長さを変えられないトランジション（カット）でも出さない。
    """
    if not current.overridden:
        return False
    return not is_fixed(transitions, current.name)


def clamp_duration(ms) -> int:
    """トランジションの長さをOBSが受け付ける範囲へ収める。"""
    try:
        value = int(round(float(ms)))
    except (TypeError, ValueError):
        return DEFAULT_DURATION_MS
    return max(DURATION_MIN_MS, min(DURATION_MAX_MS, value))


def valid_scene_name(name: str) -> str:
    """入力されたシーン名を整える。使えない名前なら空文字。

    ソース名と同じ規則（前後と連続の空白を詰めるだけ）。OBSは名前に
    使える文字をほとんど制限しないので、こちらで勝手に削らない。
    """
    return " ".join(str(name or "").split())


def free_scene_name(base: str, existing) -> str:
    """既存と衝突しないシーン名を作る。

    OBSは同じ名前のシーンを2つ作れない。ソース名と同じ作り
    （sources.free_source_name と同じ規則）。
    """
    names = set(existing or ())
    if base not in names:
        return base
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in names:
            return candidate
    return base


def can_remove(scenes, name: str) -> tuple[bool, str]:
    """このシーンを削除してよいか。(可否, 断る理由) を返す。

    ★OBSはシーンが1つも無い状態を許さない。最後の1つを消そうとすると
    拒否されるので、投げる前にこちらで止めて理由を伝える
    （OBS側のエラーをそのまま読み上げても何が悪いのか分からない）。
    """
    names = [s for s in (scenes or []) if s]
    if name not in names:
        return (False, "そのシーンが見つかりません")
    if len(names) <= 1:
        return (False, "最後のシーンは削除できません。"
                       "先に別のシーンを作ってください")
    return (True, "")


def addable_sources(all_names, in_scene, special=None) -> list[str]:
    """このシーンにまだ置いていないソースの名前。

    同じソースを複数のシーンで使えるのがOBSの利点（ゲーム音を両方の
    シーンに置く、など）。既に置いてあるものを候補に出すと、選んでも
    二重に増えるだけなので外す。

    ★グローバル音声デバイス（special）も外す。OBS本体の[設定→音声]で
    決めるマイク・デスクトップ音声は**シーンに属さず全シーンで常に有効**
    なので、シーンへ足す必要が無い。足せてしまうが、ソース一覧に二重に
    現れて「消したのに音が出る」と誤解させるだけになる。
    実測で、この環境の「マイク」がこれに当たることを確認している。
    """
    placed = set(in_scene or ())
    globals_ = set(special or ())
    return [n for n in (all_names or [])
            if n and n not in placed and n not in globals_]
