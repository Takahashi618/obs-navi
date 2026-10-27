# -*- coding: utf-8 -*-
"""OBSナビ 起動エントリポイント。

使い方:
    python -X utf8 app.py

OBS を起動し、ツールメニューから WebSocket サーバーを有効にしておくこと。
パスワードは OBS 設定ファイルから自動取得されるため、手入力は不要。
"""
from __future__ import annotations

import os
import sys

# プロジェクト直下を import パスへ（core / ui / speech / version を解決）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx  # noqa: E402

from core.config import Config  # noqa: E402


def main() -> int:
    app = wx.App()
    # ★設定を読んでから画面の部品を import する。設定の読み込みで
    #   表示の言語が決まり（core/i18n.py）、メニューやキー一覧の表は
    #   import のときにその言語で作られるため
    config = Config.load()
    from ui.main_frame import MainFrame
    frame = MainFrame(config)
    frame.Show()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
