# -*- coding: utf-8 -*-
"""映像キャプチャデバイス（ウェブカメラ・キャプチャーボード）の純ロジック。

wx・obsws に依存しない。

★★このモジュールが慎重な理由（実測で確定、2026-08-27）

カメラが動いているかどうかは、目が見えれば本体のランプで分かる。
見えない場合、**読み上げだけが唯一の判断材料**になる。だから
「カメラを止めました」と言ったのに実際は動いている、は起こしてはならない。

実測で分かった2つの落とし穴:

1. **設定 `active` を書いても、カメラは止まらない。**
   SetInputSettings で active=false を書くと、読み戻すと false になるのに
   映像は流れ続けた（sourceWidth は 1920 のまま10回連続で観測）。
   設定値だけを見て「止めました」と読み上げると**嘘になる**。
   → 止めるには **PressInputPropertiesButton(name, "activate")**。
     こちらは実際に映像が 0x0 になり、active も false になった。

2. **`active` が true でも映っているとは限らない。**
   起動直後は 1〜2秒ほど 0x0 のままだし、キャプチャーボードは
   信号が来ていなければ true のまま 0x0 になる（＝「ノーシグナル問題」）。
   → 「動作中」と「映像が来ている」は別のこととして読み分ける。

したがって状態は (active, 映像サイズ) の2つで表し、
断定できないことは断定しない（video.py と同じ考え方）。
"""
from __future__ import annotations

from dataclasses import dataclass

# 映像キャプチャデバイスの種別。OBSの「映像キャプチャデバイス」。
CAMERA_KIND = "dshow_input"

# 有効・無効を切り替えるボタンのプロパティ名。
# ★設定ではなくボタン。OBS本体のプロパティ画面にある[非アクティブ化]と同じ。
ACTIVATE_BUTTON = "activate"

# 状態
STATE_OFF = "off"          # 止まっている（デバイスを離している）
STATE_ON = "on"            # 動いていて映像も来ている
STATE_ON_NO_SIGNAL = "no_signal"  # 動いているが映像が来ていない
STATE_UNKNOWN = "unknown"  # 判定できない

# 仮想カメラは「つながっている機材」ではないので、未使用デバイスの案内から
# 外す（OBS自身が作っているもので、選んでも意味が無い）。
VIRTUAL_DEVICE_HINTS = ("obs virtual camera", "obs-camera", "obs virtualcam")


@dataclass
class CameraState:
    """カメラ1台の状態（純データ）。"""

    name: str                 # OBSの入力名
    device: str = ""          # 選ばれている機材の名前（読み上げ用）
    active: bool = False      # OBSがデバイスを掴んでいるか
    has_image: bool = False   # 今この瞬間、映像が来ているか
    visible: bool | None = None   # シーンで表示中か（シーンに無ければ None）

    @property
    def state(self) -> str:
        if not self.active:
            return STATE_OFF
        return STATE_ON if self.has_image else STATE_ON_NO_SIGNAL


def is_camera_kind(kind: str) -> bool:
    """映像キャプチャデバイスか。"""
    return kind == CAMERA_KIND


def is_virtual_device(item_name: str) -> bool:
    """OBS自身の仮想カメラなど、機材ではないものか。"""
    low = str(item_name or "").strip().lower()
    return any(h in low for h in VIRTUAL_DEVICE_HINTS)


def device_label(item_name: str) -> str:
    """機材の名前を読み上げ用にする。

    デバイス名は "c922 Pro Stream Webcam" のように英語のまま出るので、
    余計な整形はしない。空なら「未設定」。
    """
    text = " ".join(str(item_name or "").split())
    return text or "未設定"


def build_state(
    name: str,
    settings: dict | None,
    device_name: str = "",
    source_width: float = 0.0,
    visible: bool | None = None,
) -> CameraState:
    """カメラ1台の状態を組み立てる。

    ★active は「設定を書いた値」ではなく「OBSが今どうなっているか」を
    読んだ値であること。書いた値は実態と一致しない（冒頭の落とし穴1）。
    """
    values = settings or {}
    return CameraState(
        name=name,
        device=device_label(device_name),
        active=bool(values.get("active", True)),
        has_image=float(source_width or 0.0) > 0.0,
        visible=visible,
    )


def unused_devices(items, used_values) -> list[str]:
    """つながっているのに、どのソースでも使われていない機材の名前。

    「ウェブカメラはつないであるのにOBSに出ていない」を知らせるため。
    仮想カメラと、今は使えない（列挙に無い）ものは外す。
    """
    used = {str(v) for v in (used_values or ()) if v}
    out: list[str] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if not it.get("itemEnabled", True):
            continue  # 今つながっていない
        value = str(it.get("itemValue", "") or "")
        item_name = str(it.get("itemName", "") or "")
        if not value or value in used:
            continue
        if is_virtual_device(item_name):
            continue
        out.append(device_label(item_name))
    return out


def next_state_after_toggle(current_active: bool) -> bool:
    """ボタンを1回押したあとに期待される状態。

    ボタンは押すたびに反転する（値を指定して設定するのではない）ので、
    「今どうなっているか」を先に読んでからでないと結果が分からない。
    """
    return not current_active
