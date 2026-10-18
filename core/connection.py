# -*- coding: utf-8 -*-
"""OBS WebSocket への接続管理。

ReqClient（操作・取得）と EventClient（イベント購読）をまとめて扱う。
イベントは obsws-python 側のスレッドで届くため、UI層はコールバック内で
wx.CallAfter などを使って自分のスレッドへ載せ替えること。
"""
from __future__ import annotations

from typing import Callable

import obsws_python as obs
from obsws_python.error import OBSSDKError
from obsws_python.subs import Subs

from .config import Config


class ObsConnectError(Exception):
    """OBSへ接続できなかったことを表す。message は日本語の説明文。"""


class ObsConnection:
    """ReqClient と EventClient の生成・破棄を一括管理する。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.req = None
        self.events = None

    @property
    def connected(self) -> bool:
        return self.req is not None

    def connect(self, callbacks: list[Callable] | None = None) -> None:
        """接続する。失敗時は ObsConnectError を送出する。"""
        host, port, password = self.config.resolve_connection()
        if not password:
            raise ObsConnectError(
                "WebSocketのパスワードが取得できません。OBSのツールメニューから"
                "WebSocketサーバー設定を確認してください"
            )
        try:
            self.req = obs.ReqClient(
                host=host, port=port, password=password, timeout=5,
            )
            self.events = obs.EventClient(
                host=host,
                port=port,
                password=password,
                timeout=5,
                subs=(Subs.LOW_VOLUME | Subs.INPUTVOLUMEMETERS),
            )
        except ConnectionRefusedError as exc:
            self.close()
            raise ObsConnectError(
                "OBSに接続できません。OBSが起動しているか確認してください"
            ) from exc
        except OBSSDKError as exc:
            self.close()
            raise ObsConnectError(
                f"OBSとの認証に失敗しました。パスワード設定を確認してください（{exc}）"
            ) from exc
        except OSError as exc:
            self.close()
            raise ObsConnectError(f"OBSに接続できません（{exc}）") from exc
        except Exception as exc:  # noqa: BLE001
            # websocket-client の WebSocketTimeoutException 等は OSError の
            # 子ではないため、上の節では受からない。ここで受けないと UI 側へ
            # 素通りして「読み上げゼロで失敗」する。さらに ReqClient だけ
            # 成功して EventClient で失敗した場合に req が残ると、操作は
            # 効くのにイベント読み上げだけが全滅する片肺状態になるので、
            # どの失敗でも必ず close() してから ObsConnectError に変換する。
            self.close()
            raise ObsConnectError(f"OBSに接続できません（{exc}）") from exc
        if callbacks:
            self.events.callback.register(callbacks)

    def close(self) -> None:
        """接続を安全に閉じる（未接続でも安全に呼べる）。"""
        if self.events is not None:
            try:
                self.events.disconnect()
            except Exception:
                pass
            self.events = None
        if self.req is not None:
            try:
                closer = getattr(self.req, "disconnect", None)
                if closer is not None:
                    closer()
            except Exception:
                pass
            self.req = None
