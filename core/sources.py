# -*- coding: utf-8 -*-
"""作れるソース（入力）の種類の表と、その純ロジック（wx・obsws非依存）。

解く問題:
これまでソースの作成は、スクリーンリーダー音声（core/setup.py）と
BGM（commands.create_media_input）だけを個別に作り込んでいた。
それ以外のソースは OBS 本体で作るしかなく、そこはスクリーンリーダーで
扱いにくい。ここは「どの種類を作れるか」を一般化するための表。

★方針: 作れるようにするのは、**作ったあと設定もできる種類だけ**。
作れても中身を設定できない種類を候補に出すと、「足したのに使えない
ソース」がシーンに残るだけになる（カメラは機材を選ばないと何も映らず、
ウィンドウキャプチャは対象を選ばないと何も映らない）。
そのため CREATABLE_KINDS に載せる種別は、必ず props.PROP_TABLE にも
項目があること。tests/test_sources.py がこれを見張る。

種別の識別子と既定設定は 2026-08-27 に実機（OBS 32.2.2）の
GetInputKindList / GetInputDefaultSettings で実測した。
★バージョン付きの識別子に注意（text_gdiplus_v3 / color_source_v3 /
  slideshow_v2 など）。OBSを上げると増えることがある。
"""
from __future__ import annotations

from dataclasses import dataclass

from .i18n import tr

# 種別の識別子（実測。バージョン付きのものは間違えやすいので定数化する）
KIND_CAMERA = "dshow_input"
KIND_GAME = "game_capture"
KIND_WINDOW = "window_capture"
KIND_MONITOR = "monitor_capture"
KIND_APP_AUDIO = "wasapi_process_output_capture"
KIND_AUDIO_IN = "wasapi_input_capture"
KIND_AUDIO_OUT = "wasapi_output_capture"
KIND_MEDIA = "ffmpeg_source"
KIND_IMAGE = "image_source"
KIND_TEXT = "text_gdiplus_v3"
KIND_BROWSER = "browser_source"
KIND_COLOR = "color_source_v3"


@dataclass(frozen=True)
class SourceKind:
    """作れるソース1種類の情報。"""

    kind: str
    label: str        # 既定の名前にも使う（読み上げ用の日本語）
    hint: str = ""    # 何のためのものかの一言
    # 作ったあと「これを設定しないと使えない」項目のキー。
    # 作成直後に設定ダイアログを開く案内で使う。
    needs: str = ""


# 作れる種類。よく使う順に並べる。
# ★載せるのは props.PROP_TABLE に項目がある種別だけ（冒頭の方針）。
CREATABLE_KINDS: list[SourceKind] = [
    SourceKind(
        KIND_CAMERA, tr("カメラ", "Camera"),
        tr("ウェブカメラやキャプチャーボードの映像を取り込みます", "Captures video from a webcam or capture card"),
        needs="video_device_id"),
    SourceKind(
        KIND_GAME, tr("ゲームキャプチャ", "Game Capture"),
        tr("ゲームの画面を取り込みます", "Captures the game screen"), needs="window"),
    SourceKind(
        KIND_WINDOW, tr("ウィンドウキャプチャ", "Window Capture"),
        tr("選んだウィンドウの画面を取り込みます", "Captures the screen of the selected window"), needs="window"),
    SourceKind(
        KIND_MONITOR, tr("画面キャプチャ", "Display Capture"),
        tr("モニター全体を取り込みます", "Captures a whole monitor"), needs="monitor_id"),
    SourceKind(
        KIND_APP_AUDIO, tr("アプリの音", "Application Audio"),
        tr("選んだアプリの音だけを取り込みます", "Captures audio from the selected application only"), needs="window"),
    SourceKind(
        KIND_AUDIO_IN, tr("マイクなどの音声入力", "Audio Input such as a Microphone"),
        tr("マイクやライン入力の音を取り込みます", "Captures audio from a microphone or line input"), needs="device_id"),
    SourceKind(
        KIND_AUDIO_OUT, tr("パソコンの音", "Computer Audio"),
        tr("スピーカーへ出ている音をまとめて取り込みます", "Captures all audio going to the speakers"), needs="device_id"),
    SourceKind(
        KIND_MEDIA, tr("音楽や動画のファイル", "Music or Video File"),
        tr("手元のファイルを再生します", "Plays a file on your computer"), needs="local_file"),
    SourceKind(
        KIND_IMAGE, tr("画像", "Image"),
        tr("画像ファイルを画面に出します", "Shows an image file on screen"), needs="file"),
    SourceKind(
        KIND_TEXT, tr("テキスト", "Text"),
        tr("文字を画面に出します", "Shows text on screen"), needs="text"),
    SourceKind(
        KIND_BROWSER, tr("ブラウザ", "Browser"),
        tr("ウェブページを画面に出します。配信の通知などに使います", "Shows a web page on screen. Used for stream alerts and the like"),
        needs="url"),
    SourceKind(
        KIND_COLOR, tr("単色の背景", "Color Background"),
        tr("決めた色で塗りつぶした四角を置きます", "Places a rectangle filled with a chosen color"), needs=""),
]

# 音声しか持たない種別。作ったあとの案内を変えるために使う
# （映像ソースは重なり順の話が要るが、音声ソースには関係ない）。
AUDIO_ONLY_KINDS = frozenset({
    KIND_APP_AUDIO, KIND_AUDIO_IN, KIND_AUDIO_OUT,
})


def kind_by_id(kind: str) -> SourceKind | None:
    """識別子から種類の情報を引く。作れない種別なら None。"""
    for info in CREATABLE_KINDS:
        if info.kind == kind:
            return info
    return None


def is_creatable(kind: str) -> bool:
    """このアプリで作れる種別か。"""
    return kind_by_id(kind) is not None


def is_audio_only(kind: str) -> bool:
    """音声だけを持つ種別か。"""
    return kind in AUDIO_ONLY_KINDS


def free_source_name(base: str, existing) -> str:
    """既存と衝突しないソース名を作る。

    OBSは同じ名前の入力を2つ作れない（601で拒否される）。同じ種類を
    2つ置くこと自体は正当なので、名前だけ空いているものへ変える。
    filters.free_filter_name と同じ考え方。
    """
    names = set(existing or ())
    if base not in names:
        return base
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in names:
            return candidate
    return base


def valid_source_name(name: str) -> str:
    """入力された名前を整える。使えない名前なら空文字。

    前後の空白を落とすだけにとどめる。OBSは名前に使える文字を
    ほとんど制限しないので、こちらで勝手に削らない。
    """
    return " ".join(str(name or "").split())
