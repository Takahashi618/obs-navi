# -*- coding: utf-8 -*-
"""グローバルホットキーの修飾キー解析（wx非依存の純ロジック）。

設定の修飾キー文字列（例 "Ctrl+Shift"）を正規化トークン
（["ctrl", "shift"]）に変換する。実際の wx.MOD_* への対応づけは
UI層（main_frame）で行い、このモジュールは wx に依存しない。
"""
from __future__ import annotations

from .i18n import tr

# 別名を正規トークンへ寄せる
_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "win": "win",
    "windows": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
}

# 表示用の綺麗な名前
_DISPLAY_NAME = {
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "win": "Win",
}


def parse_modifier_tokens(text: str) -> list[str]:
    """"Ctrl+Shift" のような文字列を ["ctrl", "shift"] に正規化する。

    区切りは '+'。大文字小文字と別名を吸収し、重複は最初の出現順で除く。
    未知のトークンや空要素は無視する。
    """
    tokens: list[str] = []
    for raw in (text or "").split("+"):
        key = raw.strip().lower()
        if not key:
            continue
        canon = _MODIFIER_ALIASES.get(key)
        if canon and canon not in tokens:
            tokens.append(canon)
    return tokens


def modifier_label(tokens: list[str]) -> str:
    """正規トークンから表示用の修飾キー文字列を作る（例 "Ctrl+Shift"）。"""
    return "+".join(_DISPLAY_NAME.get(t, t) for t in tokens)


def hotkey_label(tokens: list[str], key_name: str) -> str:
    """修飾キー＋キー名の表示文字列を作る（例 "Ctrl+Shift+F8"）。"""
    prefix = modifier_label(tokens)
    return f"{prefix}+{key_name}" if prefix else key_name


def coarse_modifier_tokens(base_tokens: list[str]) -> list[str] | None:
    """粗い刻み用の修飾キーを基準の修飾キーから導く。

    基準に修飾キーを1つ足したものを粗い刻み用にする。足すのは Alt を優先し、
    基準に既に Alt が入っていれば Shift を足す。
      Ctrl+Shift → Ctrl+Shift+Alt
      Ctrl+Alt   → Ctrl+Alt+Shift   （ほかの道具と衝突しないよう基準を
                                      Ctrl+Alt にした場合。実測で全F列が空き）
    両方入っていると足せる余地がないので None を返す
    （呼び出し側は粗い刻みのグローバル割り当てを諦める）。
    基準が空のときも None（修飾キー無しのグローバル登録はしない方針）。
    """
    if not base_tokens:
        return None
    for extra in ("alt", "shift"):
        if extra not in base_tokens:
            return base_tokens + [extra]
    return None


# Win32 の RegisterHotKey に渡す修飾キーの値（winuser.h の MOD_*）
_WIN32_MODIFIER = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004,
                   "win": 0x0008}
# 押しっぱなし（自動リピート）で WM_HOTKEY を繰り返さない
WIN32_MOD_NOREPEAT = 0x4000
_WIN32_VK_F1 = 0x70


def win32_hotkey_args(tokens: list[str], key_name: str) -> tuple[int, int]:
    """Win32 の RegisterHotKey に渡す (修飾キー, 仮想キーコード) を作る。

    ★MOD_NOREPEAT を必ず付ける（0.18.3）。付けないと、キーを押しっぱなしに
    したときの自動リピートでも WM_HOTKEY が続けて届き、1回の長押しが
    連打になる。配信の2回押し確認が、1回の長押しで通っていた（レビューで
    判明）。wx の RegisterHotKey はこのフラグを渡せないので、Win32 を直接
    呼ぶための値をここで作る（wx に依存せずテストできるように）。
    キー名は F1〜F12、修飾キーは正規トークンだけ。それ以外は ValueError。
    """
    mods = WIN32_MOD_NOREPEAT
    for token in tokens:
        if token not in _WIN32_MODIFIER:
            raise ValueError(tr(f"使えない修飾キーです: {token!r}", f"Unsupported modifier key: {token!r}"))
        mods |= _WIN32_MODIFIER[token]
    name = str(key_name or "").strip().upper()
    number = name[1:]
    if not (name.startswith("F") and number.isascii() and number.isdigit()
            and 1 <= int(number) <= 12):
        raise ValueError(tr(f"使えないキー名です: {key_name!r}", f"Unsupported key name: {key_name!r}"))
    return mods, _WIN32_VK_F1 + int(number) - 1


# 二度押しで確かめるまでの猶予（秒）。★1回目を押した瞬間から数えるので、
# 案内の読み上げもこの中に入る。読み上げの遅い設定でも聞き終えてから
# 押し直せる長さにしてある（0.18.2 は5秒で、キー名と秒数を入れた長い
# 案内を読み終える前に切れることがあった。レビューで判明）
REPEAT_CONFIRM_SECONDS = 8.0


class RepeatConfirm:
    """同じキーを続けて2回押したら実行する、という確認（wx非依存）。

    ★グローバルキーから確認ダイアログを出さないための仕組み（0.18.2）。
    ゲーム中に押したときダイアログを出すと、OBSナビの画面を前に出す
    ことになり、ゲームから引きはがされる（全画面のゲームでは、前に
    出せずに見えず読まれもしないダイアログが残ることもある）。
    1回目で「もう一度押してください」と読み、猶予のうちに同じキーが
    来たら実行する。別のキーを挟んだら、前の1回目は取り消し。
    """

    def __init__(self, window_seconds: float = REPEAT_CONFIRM_SECONDS):
        self.window_seconds = float(window_seconds)
        self._pending = ""
        self._deadline = 0.0

    def press(self, action_id: str, now: float) -> bool:
        """押された。実行してよければ True（そのとき待ちは消える）。"""
        if self._pending == action_id and now <= self._deadline:
            self.reset()
            return True
        self._pending = action_id
        self._deadline = now + self.window_seconds
        return False

    def note(self, action_id: str) -> None:
        """キーが届いたことを知らせる。待っているのと別のキーなら取り消す。

        ★キーの受け口で、断る・早めに終わる経路より前に必ず呼ぶ（0.18.3）。
        press だけに任せると、間に挟んだキーが press まで届かなかったとき
        （すでに配信中、別の画面を開いている、など）に1回目が残り、
        「停止・開始・停止」で配信が止まっていた（レビューで判明）。
        """
        if action_id != self._pending:
            self.reset()

    def reset(self) -> None:
        self._pending = ""
        self._deadline = 0.0
