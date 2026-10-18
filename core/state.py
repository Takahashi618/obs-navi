# -*- coding: utf-8 -*-
"""OBSの状態スナップショット（OS非依存・純データ）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AudioInput:
    """音声を持つ入力の情報。"""

    name: str
    kind: str = ""
    muted: bool = False
    # フェーダーの音量(dB)。取得できなければ None
    volume_db: float | None = None


@dataclass
class SourceFilter:
    """ソースに付いたフィルター1つの情報（純データ）。"""

    name: str
    kind: str = ""
    enabled: bool = False
    index: int = 0


@dataclass
class SceneItem:
    """シーン内のソース1つ（純データ）。

    可視性の操作は item_id（整数）で行う。名前ではなく id を使うのは、
    OBSのイベントも id で飛んでくるため（同名ソースの取り違えも防げる）。
    """

    item_id: int
    name: str
    enabled: bool = True
    kind: str = ""
    index: int = 0
    # 実際に絵が出ているか判定するための現在の映像サイズ。
    # ★0 は「映像を持たない」ではなく「今は絵が出ていない」。ゲームが
    #   起動していないゲームキャプチャも 0 になる（実測）。種別の判定には
    #   使えないので、補助的にしか使わない。
    source_width: float = 0.0
    source_height: float = 0.0


@dataclass
class Snapshot:
    """接続先OBSの状態の写し。"""

    connected: bool = False
    obs_version: str = ""
    streaming: bool = False
    stream_timecode: str = "00:00:00"
    recording: bool = False
    record_timecode: str = "00:00:00"
    # 録画を一時停止中か。★録画中のまま止まっている状態で、recording は
    #   True のまま。画面を見れば分かるが読み上げには出ないため、忘れると
    #   その間が丸ごと録れていない事故になる。状態要約に必ず出す。
    record_paused: bool = False
    current_scene: str = ""
    scenes: list[str] = field(default_factory=list)
    audio_inputs: list[AudioInput] = field(default_factory=list)

    def input_by_name(self, name: str) -> AudioInput | None:
        """名前で音声入力を探す。無ければ None。"""
        for item in self.audio_inputs:
            if item.name == name:
                return item
        return None
