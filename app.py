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
from ui.main_frame import MainFrame  # noqa: E402


def main() -> int:
    app = wx.App()
    config = Config.load()
    frame = MainFrame(config)
    frame.Show()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
