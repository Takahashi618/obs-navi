# -*- coding: utf-8 -*-
"""アプリケーション音声キャプチャ入力の作成（スクリーンリーダー音声用）。

OBSの「アプリケーション音声キャプチャ」(wasapi_process_output_capture) を
WebSocket経由でGUIレスに作成する。対象プロセスは window 文字列で指定し、
priority=2（タイトル一致、なければ同じ実行ファイルのウィンドウを探す）で
タイトルが変わっても実行ファイル名で捕捉し続ける。

window 文字列の形式: "タイトル:ウィンドウクラス:実行ファイル名"
（各要素内の ':' は OBS 側で "#3A" にエスケープされるため、区切りの ':' は
純粋に3要素の境界にのみ現れる）
"""
from __future__ import annotations

APP_AUDIO_KIND = "wasapi_process_output_capture"
WINDOW_PROP = "window"
# マッチ方式: 2 = タイトル一致、なければ同じ実行ファイルのウィンドウを探す
MATCH_PRIORITY_EXE = 2


def parse_window_exe(window_value: str) -> str:
    """window 文字列から実行ファイル名を取り出す。

    "タイトル:クラス:実行ファイル" の最後の要素を返す。
    実行ファイル名に ':' は含まれないため、最後の ':' 以降が実行ファイル。
    """
    if not window_value:
        return ""
    return window_value.rsplit(":", 1)[-1]


def pick_process_window(items, exe_name: str) -> str | None:
    """プロパティ項目一覧から、実行ファイル名が一致する最初の window 値を返す。

    items は GetInputPropertiesListPropertyItems の property_items。
    各要素は {"itemName", "itemValue", "itemEnabled"}。
    大文字小文字は無視して比較する。見つからなければ None。
    """
    exe_lower = exe_name.lower()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        value = it.get("itemValue", "")
        if isinstance(value, str) and parse_window_exe(value).lower() == exe_lower:
            return value
    return None


def input_exists(client, name: str) -> bool:
    """指定名の入力が既に存在するか。"""
    resp = client.get_input_list()
    for it in getattr(resp, "inputs", []) or []:
        if isinstance(it, dict) and it.get("inputName") == name:
            return True
    return False


def rename_input(client, old_name: str, new_name: str) -> None:
    """入力の名前を変更する。"""
    client.set_input_name(old_name, new_name)


def create_sr_audio_input(
    client,
    scene_name: str,
    input_name: str,
    exe_name: str,
    priority: int = MATCH_PRIORITY_EXE,
    remove_if_not_found: bool = True,
) -> str | None:
    """スクリーンリーダー音声用のアプリ音声キャプチャ入力を作成する。

    手順:
      1. 既定設定で入力を作成（この時点では対象未設定）
      2. その入力の window プロパティ一覧を取得し、対象実行ファイルを探す
      3. 見つかれば window と priority を設定し、ミュートして window 値を返す
      4. 見つからなければ:
         - remove_if_not_found=True: 作りかけの入力を削除して None を返す
           （空の未ターゲット入力を残さない。後で作り直せるようにする）
         - remove_if_not_found=False: 入力を残しミュートして None を返す

    返り値: 設定した window 値。対象プロセスが見つからなければ None。
    """
    # 1. 空設定で作成。シーンアイテムは有効（音声を能動的に扱わせる）
    client.create_input(scene_name, input_name, APP_AUDIO_KIND, {}, True)

    # 2. 作成した入力から選択可能なプロセス一覧を取得
    items_resp = client.get_input_properties_list_property_items(
        input_name, WINDOW_PROP)
    items = getattr(items_resp, "property_items", None) or []
    value = pick_process_window(items, exe_name)

    if value:
        # 3. 見つかった: 対象を設定してミュート
        client.set_input_settings(
            input_name, {"window": value, "priority": priority}, True)
        client.set_input_mute(input_name, True)
        return value

    # 4. 見つからない
    if remove_if_not_found:
        client.remove_input(input_name)
    else:
        client.set_input_mute(input_name, True)
    return None


# ------------------------------------------------------------
# デバイスキャプチャ（録音デバイスを直接捕捉。仮想ケーブル経由のSR向け）
# ------------------------------------------------------------
DEVICE_INPUT_KIND = "wasapi_input_capture"
DEVICE_PROP = "device_id"


def pick_device_id(items, name_match: str) -> str | None:
    """プロパティ項目一覧から、名前に name_match を含む device_id を返す。

    items は GetInputPropertiesListPropertyItems の property_items。
    各要素は {"itemName", "itemValue"(=device_id)}。
    大文字小文字を無視して部分一致。見つからなければ None。
    「既定(default)」は除外する。
    """
    needle = name_match.lower()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("itemName", ""))
        value = str(it.get("itemValue", ""))
        if not value or value == "default":
            continue
        if needle in name.lower():
            return value
    return None


def create_device_capture_input(
    client,
    scene_name: str,
    input_name: str,
    device_match: str,
    remove_if_not_found: bool = True,
) -> str | None:
    """録音デバイスキャプチャ入力を作成する。

    手順:
      1. 既定設定で入力を作成
      2. その入力の device_id 一覧から、名前が device_match を含むものを探す
      3. 見つかれば device_id を設定し、ミュートして device_id を返す
      4. 見つからなければ作りかけを削除（既定）または残してミュートし None

    返り値: 設定した device_id。見つからなければ None。
    """
    client.create_input(scene_name, input_name, DEVICE_INPUT_KIND, {}, True)

    items_resp = client.get_input_properties_list_property_items(
        input_name, DEVICE_PROP)
    items = getattr(items_resp, "property_items", None) or []
    device_id = pick_device_id(items, device_match)

    if device_id:
        client.set_input_settings(
            input_name, {"device_id": device_id}, True)
        client.set_input_mute(input_name, True)
        return device_id

    if remove_if_not_found:
        client.remove_input(input_name)
    else:
        client.set_input_mute(input_name, True)
    return None


def create_sr_source_input(client, scene_name: str, source: dict) -> str | None:
    """sr_sources の1要素から、その方式に応じた入力を作成する。

    method="app"    → アプリ音声キャプチャ（exe を対象）
    method="device" → デバイスキャプチャ（device_match の録音デバイス）
    返り値: 設定できた識別値（window または device_id）。失敗時 None。
    """
    name = source.get("name", "")
    method = source.get("method", "app")
    if method == "device":
        return create_device_capture_input(
            client, scene_name, name, source.get("device_match", ""))
    return create_sr_audio_input(
        client, scene_name, name, source.get("exe", ""))
