# -*- coding: utf-8 -*-
"""表示と読み上げの言語（日本語か英語）。

利用者に見せる文・読ませる文は、日本語と英語を
`tr("日本語", "English")` のように並べて書き、いまの言語のほうを使う。
訳の表を別に持たないのは、組み立てる文（f 文字列）が多いため。
表にすると、どの文がどの訳か取り違えやすい。

言語は起動したときに1回だけ決める（init）:

1. 環境変数 OBSNAVI_LANG が ja か en なら、それ（テストと確かめ用）
2. 設定の language が ja か en なら、それ（「ツール」メニューから選ぶ）
3. どちらでもなければ（auto）PC の表示言語。日本語なら ja、それ以外は en

★途中で変えない。メニューや一覧の表（keymap の WINDOW_PLAN など）は
import のときに作るので、途中で変えると食い違う。設定から言語を
選び直したときは、次に起動したときから効く。
"""
from __future__ import annotations

import os
import sys

#: 使える言語
LANGUAGES = ("ja", "en")
#: 設定の language に書ける値（auto は PC の表示言語に合わせる）
SETTINGS = ("auto", "ja", "en")
#: 言語を決める環境変数（ja か en）。設定より強い
ENV_VAR = "OBSNAVI_LANG"

_current: str | None = None


def normalize(value) -> str | None:
    """「ja」「en-US」「EN」などを ja / en にする。どちらでもなければ None。"""
    if not isinstance(value, str):
        return None
    head = value.strip().lower()
    if head.startswith("ja"):
        return "ja"
    if head.startswith("en"):
        return "en"
    return None


def normalize_setting(value) -> str:
    """設定の language を auto / ja / en のどれかへ寄せる（読めなければ auto）。"""
    return normalize(value) or "auto"


def _windows_language() -> str | None:
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:  # noqa: BLE001
        return None
    # 下位10ビットが主言語。0x11 が日本語
    return "ja" if (int(lang_id) & 0x3FF) == 0x11 else "en"


def _posix_language() -> str | None:
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            return "ja" if normalize(value) == "ja" else "en"
    return None


def system_language() -> str:
    """PC の表示言語（ja か en）。日本語でなければ en。"""
    found = _windows_language() if sys.platform == "win32" else None
    return found or _posix_language() or "en"


def resolve(setting=None) -> str:
    """環境変数・設定値・PC の表示言語から、使う言語を決める。"""
    return (normalize(os.environ.get(ENV_VAR))
            or normalize(setting)
            or system_language())


def init(setting=None) -> str:
    """起動時に言語を決める（設定を読んだ直後に1回呼ぶ）。"""
    global _current
    _current = resolve(setting)
    return _current


def language() -> str:
    """いまの言語（ja か en）。init より前なら設定なしとして決める。"""
    global _current
    if _current is None:
        _current = resolve(None)
    return _current


def is_japanese() -> bool:
    return language() == "ja"


def tr(ja: str, en: str) -> str:
    """いまの言語のほうの文を返す。"""
    return ja if language() == "ja" else en
