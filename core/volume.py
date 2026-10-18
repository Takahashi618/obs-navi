# -*- coding: utf-8 -*-
"""音量（フェーダー値）の計算（純ロジック・OS非依存）。

OBSが受け付ける音量の範囲は実測で -100.0dB 〜 +26.0dB。
範囲外を投げると OBS は 402 を返して拒否するので、投げる前に丸める。

「格子に寄せてから動かす」のがこのモジュールの肝。理由:
ユーザーがOBSの詳細音声プロパティで付けた値は +5.1dB のように
半端な値になっている。そこから素朴に +1.0 すると 6.1dB になり、
読み上げは「プラス6デシベル」なのに実際は6.1という食い違いが残り続ける。
このアプリは読み上げが唯一の情報源なので、読んだ値と実際の値は一致させたい。
そこで「最寄りの格子へ寄せてから delta 動かす」ことで、
値は常に格子（既定1dB刻み）に乗り、読み上げた値＝実際の値になる。
"""
from __future__ import annotations

# OBSが受け付ける範囲（obs-websocket の SetInputVolume の制限。実測値）
VOLUME_MIN_DB = -100.0
VOLUME_MAX_DB = 26.0


def clamp_db(db: float) -> float:
    """OBSが受け付ける範囲へ収める。"""
    if db < VOLUME_MIN_DB:
        return VOLUME_MIN_DB
    if db > VOLUME_MAX_DB:
        return VOLUME_MAX_DB
    return db


def next_db(current_db: float, delta_db: float, step_db: float = 1.0) -> float:
    """現在値を格子へ寄せてから delta_db 動かした音量(dB)を返す。

    step_db が格子の間隔（既定1dB）。delta_db は動かす量（+1.0 や -5.0）。
    step_db <= 0 のときは格子に寄せずそのまま足す。

    OBSが返す値は float32 由来の誤差を含む（6.0 が 5.99999952 で返る）ため、
    格子を求める前に丸める。丸めないと「最寄りの格子」が5になり、
    +1しても6.0のまま＝キーを押しても値が変わらないように見えてしまう。
    """
    if step_db <= 0:
        return clamp_db(round(current_db + delta_db, 3))
    base = round(round(current_db, 3) / step_db) * step_db
    return clamp_db(round(base + delta_db, 3))


def parse_db_input(text: str) -> float | None:
    """入力された文字列を音量(dB)として解釈する。解釈できなければ None。

    受け付ける例: "5" "-10" "+5.1" "５" "-10dB" " 3 db "
    全角数字や単位付きも通す（数値入力ダイアログに手で打ち込むため）。
    範囲外は None ではなく端へ丸める（打ち間違いで拒否されるより親切）。
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    # 全角を半角へ
    s = s.translate(str.maketrans(
        "０１２３４５６７８９＋－．", "0123456789+-."))
    # 単位や記号のゆらぎを落とす
    lowered = s.lower()
    for suffix in ("decibel", "デシベル", "db"):
        if lowered.endswith(suffix):
            s = s[: len(s) - len(suffix)]
            break
    s = s.strip()
    # 全角マイナス記号のゆらぎ
    s = s.replace("−", "-").replace("ー", "-").replace("―", "-")
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None  # NaN / inf は拒否
    return clamp_db(round(value, 3))
