# -*- coding: utf-8 -*-
"""読み上げ出力層。

accessible_output2 経由でアクティブなスクリーンリーダー
（PC-Talker / NVDA など）へ発声する。
環境変数 OBSNAVI_SILENT=1 のときは一切発声しない（テスト用）。

接頭語の方針（全プロジェクト共通ルール）:
- [エラー] と [警告] のみ接頭語を付ける
- 情報・成功は本文をそのまま読む
"""
from __future__ import annotations

import os
import time

_SILENT: bool = os.environ.get("OBSNAVI_SILENT", "") == "1"
_speaker = None
_speaker_failed = False
# 起動直後、この時刻までは割り込まない（start_grace で決める）
_grace_until: float = 0.0

# 起動直後に割り込みを止めておく既定の長さ（秒）。状態欄の名前
# （「OBSナビ バージョン x.y.z の状態」）と、続く接続完了の読み上げを
# 読み終えるまでを見込んだ値。★短すぎると版が切られ、長すぎると
# 本当に急ぎの警告が後ろに回る。
GRACE_SECONDS = 3.0


def start_grace(seconds: float = GRACE_SECONDS) -> None:
    """しばらくの間、読み上げで割り込まないことにする（起動直後用）。

    ★スクリーンリーダーは、窓が前に出た時点でフォーカスのある欄の
    読み上げ名を自分で読み始める。OBSナビはそこにバージョンを入れて
    いる（0.17.1）ので、その間に割り込むと版が分からなくなる。

    ★「最初の1回だけ」にしてはいけない（0.17.3 の作り）。最初の1回を
    接続完了の読み上げが使い切ったあと、直後に届くレベル警告やOBSの
    イベントが割り込んで、結局バージョンが切られていた（レビューで
    判明）。守るべきなのは回数ではなく、読み終わるまでの時間。
    """
    global _grace_until
    try:
        span = max(0.0, float(seconds))
    except (TypeError, ValueError):
        span = GRACE_SECONDS
    _grace_until = time.monotonic() + span


def end_grace() -> None:
    """猶予を打ち切る。

    利用者がキーを押し始めたら、そこから先の読み上げは操作への応答なので
    割り込んでよい（待たされる方が困る）。
    """
    global _grace_until
    _grace_until = 0.0


def grace_pending() -> bool:
    """今まだ猶予の時間内か（起動直後の割り込み抑止が効いているか）。"""
    return time.monotonic() < _grace_until


def _get_speaker():
    global _speaker, _speaker_failed
    if _SILENT or _speaker_failed:
        return None
    if _speaker is None:
        try:
            from accessible_output2.outputs.auto import Auto
            _speaker = Auto()
        except Exception:
            # スクリーンリーダー環境が無い場合でもアプリは動作させる
            _speaker_failed = True
            return None
    return _speaker


def speak(text: str, interrupt: bool = False) -> None:
    """本文をそのまま読み上げる（情報・成功はこれを使う）。

    ウィンドウタイトルやファイル名には絵文字や ™ などが混ざることがあり、
    PC-Talker のバックエンドでは「？」と読まれてしまう。ここで一度だけ
    無害な文字に置き換えてから渡す（整形自体は純関数側にある）。
    """
    if interrupt and grace_pending():
        # 起動直後。ここで割り込むと、スクリーンリーダーが読んでいる
        # 状態欄の名前（バージョン入り）を途中で切ってしまう
        interrupt = False
    sp = _get_speaker()
    if sp is None:
        return
    try:
        from core.speech_format import speech_safe
        text = speech_safe(text)
    except Exception:  # noqa: BLE001
        pass
    try:
        sp.speak(text, interrupt=interrupt)
    except Exception:
        pass


def warn(text: str, interrupt: bool = True) -> None:
    """警告。接頭語 [警告] を付ける。既定は割り込みで読む。

    ★interrupt=False は「起動直後」のためにある。スクリーンリーダーが
    フォーカスした欄の名前（バージョンが入っている）を読んでいる最中に
    割り込むと、そこで切れて版が分からなくなる。
    """
    speak(f"[警告] {text}", interrupt=interrupt)


def error(text: str, interrupt: bool = True) -> None:
    """エラー。接頭語 [エラー] を付ける。既定は割り込みで読む。

    interrupt=False の理由は warn と同じ。
    """
    speak(f"[エラー] {text}", interrupt=interrupt)
