# -*- coding: utf-8 -*-
"""設定変更の「合流器」（純ロジック・wx非依存）。

なぜ要るか:
設定変更の読み上げは、他の機能と同じく OBS からのイベント
(InputSettingsChanged) 経由で一元化したい。ところが素朴に
「イベントが来たら喋る」にすると3つの理由で壊れる。

1. 順序が保証されない
   映像を持つ入力(game_capture / ffmpeg_source)は更新が次の描画まで
   遅れるが、音声だけの入力(wasapi_*)は即時。ゲーム切り替えのように
   2つの入力を続けて変えると、後に投げた方が先に届くことがある。
   入力ごとに喋ると2回・逆順に読まれる。
2. イベントは重複排除されない
   値が変わっていなくても飛ぶ。OBS本体のプロパティ画面は入力中に連発する。
3. 届かない可能性への保険
   万一イベントが来なくても無言にはしたくない。

そこで「何を投げたか」を1件だけ保持し、対象すべてのイベントが揃うか、
一定時間が過ぎたら（呼び出し側が読み直して）まとめて1回だけ喋る。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SettingsOp:
    """自分が投げた設定変更1回ぶんの記録。

    op_id は「古いタイマーで確定させない」ための通し番号。
    連打されたとき、古い op のタイマーが後から発火して新しい op を
    横取りするのを防ぐ。
    """

    op_id: int
    kind: str                       # "game_switch" | "prop"
    sources: list[str]              # 反応を待つ入力名
    expected: dict = field(default_factory=dict)  # 入力名 → 投げた設定
    observed: dict = field(default_factory=dict)  # 入力名 → 実際の設定
    extra: dict = field(default_factory=dict)     # 読み上げ用の文脈

    def note(self, name: str, settings: dict) -> bool:
        """イベント/読み直しの結果を記録する。全員そろえば True。"""
        if name in self.sources:
            self.observed[name] = dict(settings or {})
        return self.is_complete()

    def is_complete(self) -> bool:
        """待っている入力すべての結果がそろったか。"""
        return all(name in self.observed for name in self.sources)

    def missing(self) -> list[str]:
        """まだ結果が来ていない入力名。"""
        return [name for name in self.sources if name not in self.observed]

    def applied(self, name: str, key: str) -> bool:
        """入力 name のキー key が、投げた値どおりになったか。

        OBS が受け付けなかった（種別が違う等で無視された）ことを
        検出するために使う。observed が無いときは判定できないので False。
        """
        want = (self.expected.get(name) or {})
        got = (self.observed.get(name) or {})
        if key not in want or name not in self.observed:
            return False
        return got.get(key) == want[key]
