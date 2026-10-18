# -*- coding: utf-8 -*-
"""OBSへの操作・取得（ReqClient の薄いラッパ）。

client 引数は obsws_python.ReqClient 互換のオブジェクト。
テストでフェイクを渡せるよう、このモジュールは obsws_python を
直接 import しない。
"""
from __future__ import annotations

from . import props
from .state import AudioInput, SceneItem, Snapshot, SourceFilter

# メディア操作の識別子は props 側に定義してある（純モジュールなので
# テストから wx も obsws も無しに参照できる）。ここから再輸出しておく。
MEDIA_PLAY = props.MEDIA_PLAY
MEDIA_PAUSE = props.MEDIA_PAUSE
MEDIA_STOP = props.MEDIA_STOP
MEDIA_RESTART = props.MEDIA_RESTART


def fetch_snapshot(client) -> Snapshot:
    """OBSの現在状態をまとめて取得する。"""
    snap = Snapshot(connected=True)
    try:
        ver = client.get_version()
        snap.obs_version = str(getattr(ver, "obs_version", "") or "")
    except Exception:
        pass

    stream = client.get_stream_status()
    snap.streaming = bool(getattr(stream, "output_active", False))
    snap.stream_timecode = str(
        getattr(stream, "output_timecode", "") or "00:00:00")

    record = client.get_record_status()
    snap.recording = bool(getattr(record, "output_active", False))
    snap.record_paused = bool(getattr(record, "output_paused", False))
    snap.record_timecode = str(
        getattr(record, "output_timecode", "") or "00:00:00")

    scene_list = client.get_scene_list()
    names: list[str] = []
    for item in getattr(scene_list, "scenes", []) or []:
        if isinstance(item, dict):
            name = item.get("sceneName", "")
            if name:
                names.append(name)
    # OBSは末尾側が画面上段になる並びで返すため、UI表示用に反転する
    names.reverse()
    snap.scenes = names
    snap.current_scene = str(
        getattr(scene_list, "current_program_scene_name", "") or "")

    snap.audio_inputs = fetch_audio_inputs(client)
    return snap


def fetch_audio_inputs(client) -> list[AudioInput]:
    """音声を持つ入力の一覧（ミュート状態つき）。

    GetInputMute は音声を持たない入力に対してエラーになるため、
    それを利用して音声入力だけを抽出する。
    """
    result: list[AudioInput] = []
    resp = client.get_input_list()
    for item in getattr(resp, "inputs", []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get("inputName", "")
        kind = item.get("inputKind", "")
        if not name:
            continue
        try:
            mute_resp = client.get_input_mute(name)
        except Exception:
            continue  # 音声を持たない入力
        muted = bool(getattr(mute_resp, "input_muted", False))
        result.append(AudioInput(
            name=name, kind=kind, muted=muted,
            volume_db=fetch_volume_db(client, name)))
    return result


def fetch_volume_db(client, name: str) -> float | None:
    """入力の音量(dB)を取得する。取れなければ None。

    音量を持たない入力もあり得るので、取れないことを失敗にはしない
    （一覧の表示から音量が消えるだけで、他の操作は続けられる）。
    """
    try:
        resp = client.get_input_volume(name)
    except Exception:
        return None
    value = getattr(resp, "input_volume_db", None)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def set_volume_db(client, name: str, db: float) -> None:
    """入力の音量(dB)を設定する。範囲は呼び出し側で core.volume で丸めておく。"""
    client.set_input_volume(name, vol_db=db)


def fetch_source_filters(client, source_name: str) -> list[SourceFilter]:
    """ソースのフィルター一覧を取得する。取れなければ空リスト。"""
    return fetch_source_filters_checked(client, source_name)[1]


def fetch_source_filters_checked(
    client, source_name: str
) -> tuple[bool, list[SourceFilter]]:
    """フィルター一覧を (取得できたか, 一覧) で返す。

    OBS が返す並びは index 昇順（先頭が一番上）。OBS本体のフィルター一覧の
    表示順と同じなので、そのまま使う（シーンのように反転しない）。

    ★「フィルターが1つも無い」と「通信が届かなかった」を呼ぶ側が
    区別できるようにする。空リストで潰すと、接続が切れているのに
    「フィルターが見つかりません」と読み上げ、一覧まで消してしまう
    （利用者は原因を取り違えて探し続けることになる）。
    """
    if not source_name:
        return True, []
    try:
        resp = client.get_source_filter_list(source_name)
    except Exception:
        return False, []
    result: list[SourceFilter] = []
    for item in getattr(resp, "filters", []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get("filterName", "")
        if not name:
            continue
        result.append(SourceFilter(
            name=name,
            kind=item.get("filterKind", ""),
            enabled=bool(item.get("filterEnabled", False)),
            index=int(item.get("filterIndex", 0)),
        ))
    return True, result


def set_filter_enabled(
    client, source_name: str, filter_name: str, enabled: bool
) -> None:
    """フィルターの有効・無効を設定する。"""
    client.set_source_filter_enabled(source_name, filter_name, enabled)


def fetch_filter_kind(client, source_name: str, filter_name: str) -> str:
    """フィルターの種別を取得する。取れなければ空文字。"""
    try:
        resp = client.get_source_filter(source_name, filter_name)
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(resp, "filter_kind", "") or "")


def fetch_filter_settings(client, source_name: str, filter_name: str) -> dict:
    """フィルターの設定を取得する（明示的に保存されている分だけ）。

    ★作った直後は空の辞書が返る（実測）。表示には必ず
    fetch_merged_filter_settings を使うこと。
    """
    try:
        resp = client.get_source_filter(source_name, filter_name)
    except Exception:  # noqa: BLE001
        return {}
    value = getattr(resp, "filter_settings", None)
    return dict(value) if isinstance(value, dict) else {}


def fetch_filter_default_settings(client, kind: str) -> dict:
    """フィルター種別の既定設定を取得する。取れなければ空辞書。"""
    if not kind:
        return {}
    try:
        resp = client.get_source_filter_default_settings(kind)
    except Exception:  # noqa: BLE001
        return {}
    value = getattr(resp, "default_filter_settings", None)
    return dict(value) if isinstance(value, dict) else {}


def fetch_merged_filter_settings(
    client, source_name: str, filter_name: str, kind: str = ""
) -> tuple[str, dict]:
    """(種別, 既定値に現在値を重ねた設定) を返す。

    種別を省いたときは問い合わせ直す。入力の fetch_merged_settings と
    同じ理由で、既定とのマージが要る（現在値だけでは既定のままの項目が
    読めない）。
    """
    from . import filters  # 循環参照を避けるため関数内 import

    try:
        resp = client.get_source_filter(source_name, filter_name)
    except Exception:  # noqa: BLE001
        return (kind, {})
    if not kind:
        kind = str(getattr(resp, "filter_kind", "") or "")
    current = getattr(resp, "filter_settings", None)
    current = dict(current) if isinstance(current, dict) else {}
    defaults = fetch_filter_default_settings(client, kind)
    return (kind, filters.merge_defaults(defaults, current))


def apply_filter_settings(
    client, source_name: str, filter_name: str, settings: dict
) -> None:
    """フィルターの設定を変更する（常に上書きマージ）。

    ★overlay を引数に取らないのは意図的。apply_input_settings と同じ理由で、
    overlay=False は指定しなかった設定を既定へ戻してしまう。
    """
    client.set_source_filter_settings(
        source_name, filter_name, dict(settings or {}), True)


def create_filter(
    client, source_name: str, filter_name: str, kind: str
) -> None:
    """フィルターを作る（既定設定で）。

    ★async_delay_filter は作ろうとしても作られない（エラーも出ない）ことを
    実測で確認済み。呼び出し側は core/filters.py の候補一覧を使うこと。
    """
    client.create_source_filter(source_name, filter_name, kind)


def remove_filter(client, source_name: str, filter_name: str) -> None:
    """フィルターを削除する。"""
    client.remove_source_filter(source_name, filter_name)


def set_filter_index(
    client, source_name: str, filter_name: str, index: int
) -> None:
    """フィルターの並び順を変える（音声は順番で効き方が変わる）。"""
    client.set_source_filter_index(source_name, filter_name, index)


def fetch_scene_items(client, scene_name: str) -> list[SceneItem]:
    """シーン内のソース一覧を取得する。取れなければ空リスト。"""
    return fetch_scene_items_checked(client, scene_name)[1]


def fetch_scene_items_checked(
    client, scene_name: str
) -> tuple[bool, list[SceneItem]]:
    """シーン内のソース一覧を (取得できたか, 一覧) で返す。

    OBS が返す並びは sceneItemIndex 昇順で、index が大きいほど画面の手前
    （上に重なる）。OBS本体のソース一覧パネルは手前が上に表示されるので、
    表示に合わせるため index 降順（手前＝先頭）にして返す。

    ★「空のシーン」と「通信が届かなかった」を呼ぶ側が区別できるように
    する（fetch_source_filters_checked と同じ理由）。
    """
    if not scene_name:
        return True, []
    try:
        resp = client.get_scene_item_list(scene_name)
    except Exception:
        return False, []
    result: list[SceneItem] = []
    for item in getattr(resp, "scene_items", []) or []:
        if not isinstance(item, dict):
            continue
        iid = item.get("sceneItemId")
        name = item.get("sourceName", "")
        if iid is None or not name:
            continue
        # 現在の映像サイズ。GetSceneItemList の応答に既に入っているので
        # 追加の問い合わせは要らない。
        width = height = 0.0
        try:
            tr = item.get("sceneItemTransform") or {}
            width = float(tr.get("sourceWidth", 0.0) or 0.0)
            height = float(tr.get("sourceHeight", 0.0) or 0.0)
        except (TypeError, ValueError):
            width = height = 0.0
        result.append(SceneItem(
            item_id=int(iid),
            name=name,
            enabled=bool(item.get("sceneItemEnabled", True)),
            kind=item.get("inputKind") or item.get("sourceType", ""),
            index=int(item.get("sceneItemIndex", 0)),
            source_width=width,
            source_height=height,
        ))
    result.sort(key=lambda s: s.index, reverse=True)
    return True, result


def set_scene_item_enabled(
    client, scene_name: str, item_id: int, enabled: bool
) -> None:
    """シーン内ソースの表示・非表示を設定する。"""
    client.set_scene_item_enabled(scene_name, item_id, enabled)


def set_scene_item_index(
    client, scene_name: str, item_id: int, index: int
) -> None:
    """シーン内ソースの重なり順を変える（index が大きいほど手前）。

    ★可視性には一切触れないので、音は止まらない。映像の切り替えを
    「非表示」ではなく「重なり順」で行うのは、非表示にすると音まで
    消えてしまい、目で確認できない利用者には気づけない事故になるため。
    """
    client.set_scene_item_index(scene_name, item_id, index)


def fetch_stats(client) -> dict:
    """OBSの統計を読み上げ用の辞書にまとめる。取れない値は入れない。"""
    try:
        s = client.get_stats()
    except Exception:
        return {}
    out: dict = {}

    def put(key, attr):
        val = getattr(s, attr, None)
        if isinstance(val, (int, float)):
            out[key] = val

    put("cpu", "cpu_usage")
    put("fps", "active_fps")
    put("disk_free_mb", "available_disk_space")
    put("memory_mb", "memory_usage")
    put("render_total", "render_total_frames")
    put("render_skipped", "render_skipped_frames")
    put("output_total", "output_total_frames")
    put("output_skipped", "output_skipped_frames")
    return out


def toggle_virtual_cam(client) -> None:
    """仮想カメラのオン・オフを切り替える。"""
    client.toggle_virtual_cam()


def is_virtual_cam_active(client) -> bool:
    """仮想カメラが動作中か。"""
    try:
        return bool(getattr(client.get_virtual_cam_status(),
                            "output_active", False))
    except Exception:
        return False


def toggle_record_pause(client) -> None:
    """録画の一時停止・再開を切り替える。"""
    client.toggle_record_pause()


class ReplayBufferUnavailable(Exception):
    """リプレイバッファがOBSで無効なことを表す。"""


class ReplayBufferStarting(Exception):
    """リプレイバッファを今起動したところで、まだ保存できないことを表す。"""


def save_replay_buffer(client) -> None:
    """リプレイバッファを保存する（直近の数十秒をファイルへ）。

    OBSの[設定→出力]でリプレイバッファが無効だと 604 で失敗する。
    その場合は ReplayBufferUnavailable にして、UI側で有効化を案内できる
    ようにする。

    有効だが未起動のときは起動だけ行い、ReplayBufferStarting を送出する。
    起動は非同期で、直後に保存を投げても「出力が動いていない」で失敗するし、
    成功しても中身のほぼ無いリプレイになる。UI側は「起動した。少し待って
    もう一度」と案内する。
    """
    try:
        active = getattr(client.get_replay_buffer_status(),
                         "output_active", None)
    except Exception as exc:
        raise ReplayBufferUnavailable(str(exc)) from exc
    if not active:
        # 無効か、有効だが未起動。起動を試みて、それも無効なら案内へ。
        try:
            client.start_replay_buffer()
        except Exception as exc:
            raise ReplayBufferUnavailable(str(exc)) from exc
        raise ReplayBufferStarting()
    client.save_replay_buffer()


# ------------------------------------------------------------
# 録画（状態・チャプター・設定の読み取り）
# ------------------------------------------------------------
def fetch_record_status(client) -> tuple[bool, bool, str]:
    """(録画中か, 一時停止中か, タイムコード) を返す。取れなければ既定値。

    一時停止は録画中のまま止まっている状態なので、active は True のまま
    paused だけが立つ。両方を返さないと状態を言い分けられない。
    """
    try:
        resp = client.get_record_status()
    except Exception:  # noqa: BLE001
        return (False, False, "00:00:00")
    return (
        bool(getattr(resp, "output_active", False)),
        bool(getattr(resp, "output_paused", False)),
        str(getattr(resp, "output_timecode", "") or "00:00:00"),
    )


class RecordChapterUnsupported(Exception):
    """今の録画フォーマットではチャプターを打てないことを表す。"""


def create_record_chapter(client, name: str = "") -> None:
    """録画中のファイルにチャプター（しおり）を打つ。

    ★対応フォーマットはハイブリッドMP4だけ（OBS 30.2 時点）。それ以外だと
    OBS 側が拒否するので、RecordChapterUnsupported に変換して UI 側で
    「フォーマットを変えてください」と案内できるようにする。
    録画していないときも拒否されるが、そちらは呼び出し前に状態で弾く。
    """
    try:
        client.create_record_chapter(name or None)
    except Exception as exc:  # noqa: BLE001
        raise RecordChapterUnsupported(str(exc)) from exc


def fetch_record_output_kind(client) -> str:
    """今OBSが録画に使っている出力の種別。取れなければ空文字。

    ★設定の録画フォーマットとは別物。フォーマットを変えても起動中のOBSは
    出力を作り直さないので、両者はずれ得る（実測で確認）。チャプターが
    本当に使えるかは、設定ではなくこちらで判定する。
    """
    from . import recording  # 循環参照を避けるため関数内 import

    try:
        resp = client.get_output_list()
    except Exception:  # noqa: BLE001
        return ""
    item = recording.pick_record_output(getattr(resp, "outputs", None) or [])
    if item is None:
        return ""
    return str(item.get("outputKind", "") or "")


def fetch_record_directory(client) -> str:
    """録画の保存先フォルダ。取れなければ空文字。

    出力モード（簡易・詳細）による設定キーの違いを OBS 側が吸収して
    「実際に使われるフォルダ」を返してくれるので、設定を直接読むより確実。
    """
    try:
        resp = client.get_record_directory()
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(resp, "record_directory", "") or "")


def fetch_profile_parameter(client, category: str, name: str) -> str:
    """プロファイル設定を1つ読む。取れなければ空文字。

    値が未設定のときは OBS が既定値を別に返すので、そちらへ落とす
    （設定ファイルに書かれていない＝既定のまま、を正しく読むため）。
    """
    try:
        resp = client.get_profile_parameter(category, name)
    except Exception:  # noqa: BLE001
        return ""
    value = getattr(resp, "parameter_value", None)
    if value is None or value == "":
        value = getattr(resp, "default_parameter_value", None)
    return str(value or "")


def apply_profile_parameter(client, category: str, name: str, value: str) -> None:
    """プロファイル設定を1つ書き換える。

    ★OBS本体の[設定]画面と同じ場所を触る。録画フォーマットのように
    「次に録画を始めたとき」から効く設定なので、録画中の変更は避けること。
    """
    client.set_profile_parameter(category, name, str(value))


def fetch_record_settings(client) -> dict:
    """録画設定を読み上げ用の辞書にまとめる。

    OBS本体の[設定→出力]はスクリーンリーダーで読めない領域があるため、
    ここで必要な項目だけを集める。出力モードでセクションもキー名も変わる
    ので、モードを先に読んでから引く（recording.output_section を使う）。
    """
    from . import recording  # 循環参照を避けるため関数内 import

    mode = fetch_profile_parameter(client, "Output", "Mode")
    section = recording.output_section(mode)
    out: dict = {
        "mode": mode,
        "section": section,
        "directory": fetch_record_directory(client),
        "format": fetch_profile_parameter(client, section, "RecFormat2"),
        "encoder": fetch_profile_parameter(client, section, "RecEncoder"),
        "tracks": fetch_profile_parameter(client, section, "RecTracks"),
        "filename_format": fetch_profile_parameter(
            client, "Output", "FilenameFormatting"),
        # 設定ではなく「今動いている出力」の種別。設定を変えても OBS を
        # 再起動するまで変わらないので、チャプターの可否はこちらで判定する
        "output_kind": fetch_record_output_kind(client),
    }
    if section == recording.SECTION_SIMPLE:
        # 簡易出力にだけある「録画品質」。詳細出力ではエンコーダ設定が
        # そのまま品質を決めるので存在しない
        out["quality"] = fetch_profile_parameter(client, section, "RecQuality")
    # 空き容量は統計側から取る（保存先のあるドライブの値が返る）
    stats = fetch_stats(client)
    if "disk_free_mb" in stats:
        out["disk_free_mb"] = stats["disk_free_mb"]
    return out


def fetch_last_replay_path(client) -> str:
    """最後に保存したリプレイのファイルパス。取れなければ空文字。"""
    try:
        resp = client.get_last_replay_buffer_replay()
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(resp, "saved_replay_path", "") or "")


def start_stream(client) -> None:
    client.start_stream()


def stop_stream(client) -> None:
    client.stop_stream()


def start_record(client) -> None:
    client.start_record()


def stop_record(client) -> None:
    client.stop_record()


def set_scene(client, name: str) -> None:
    client.set_current_program_scene(name)


def toggle_mute(client, name: str) -> None:
    client.toggle_input_mute(name)


def set_mute(client, name: str, muted: bool) -> None:
    client.set_input_mute(name, muted)


# ------------------------------------------------------------
# ソース設定（プロパティ）
# ------------------------------------------------------------
def fetch_input_settings(client, name: str) -> dict:
    """入力の設定を取得する（明示的に保存されている分だけ）。

    既定のままの項目は入っていないので、表示には fetch_merged_settings
    を使うこと。
    """
    resp = client.get_input_settings(name)
    value = getattr(resp, "input_settings", None)
    return dict(value) if isinstance(value, dict) else {}


def fetch_input_kind(client, name: str) -> str:
    """入力の種別を取得する。取れなければ空文字。

    GetInputSettings の応答に種別も入っているので1回の問い合わせで済む。
    """
    try:
        resp = client.get_input_settings(name)
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(resp, "input_kind", "") or "")


def fetch_input_default_settings(client, kind: str) -> dict:
    """種別の既定設定を取得する。取れなければ空辞書。"""
    try:
        resp = client.get_input_default_settings(kind)
    except Exception:  # noqa: BLE001
        return {}
    value = getattr(resp, "default_input_settings", None)
    return dict(value) if isinstance(value, dict) else {}


def fetch_merged_settings(client, name: str, kind: str = "") -> dict:
    """既定値に現在値を重ねた「今の設定」を返す。

    kind を省いたときは入力から引き直す。
    """
    if not kind:
        kind = fetch_input_kind(client, name)
    defaults = fetch_input_default_settings(client, kind) if kind else {}
    current = fetch_input_settings(client, name)
    return props.merge_settings(defaults, current)


def fetch_property_items(client, name: str, prop: str) -> list[dict]:
    """プロパティの選択肢一覧を取得する。取れなければ空リスト。

    返る各要素は {"itemName", "itemEnabled", "itemValue"}。
    ★obsws-python が snake_case にするのは応答のトップレベルだけなので、
    中身のキーは camelCase のまま（core/setup.py も同じ流儀）。
    """
    try:
        resp = client.get_input_properties_list_property_items(name, prop)
    except Exception:  # noqa: BLE001
        return []
    items = getattr(resp, "property_items", None) or []
    return [it for it in items if isinstance(it, dict)]


def fetch_input_names_by_kind(client, kind: str) -> list[str]:
    """指定種別の入力名を並べる（設定のソース名が合わないときの選び直し用）。"""
    try:
        resp = client.get_input_list()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for it in getattr(resp, "inputs", []) or []:
        if not isinstance(it, dict):
            continue
        if it.get("inputKind") == kind and it.get("inputName"):
            out.append(str(it["inputName"]))
    return out


def apply_input_settings(client, name: str, settings: dict) -> None:
    """入力の設定を変更する（常に上書きマージ）。

    ★overlay を引数に取らないのは意図的。overlay=False は指定しなかった
    設定を既定値へ戻してしまうため、編集用途では絶対に使わない。
    選べないようにして誤用を構造的に防ぐ。
    """
    client.set_input_settings(name, dict(settings or {}), True)


# ------------------------------------------------------------
# シーン（作成・改名・削除・トランジション）
# ------------------------------------------------------------
def fetch_scene_names(client) -> list[str]:
    """シーン名を画面の並び（上が先頭）で返す。

    fetch_snapshot と同じく、OBSが返す配列は末尾が画面上段なので反転する。
    """
    try:
        resp = client.get_scene_list()
    except Exception:  # noqa: BLE001
        return []
    names = [str(s["sceneName"]) for s in getattr(resp, "scenes", []) or []
             if isinstance(s, dict) and s.get("sceneName")]
    names.reverse()
    return names


def create_scene(client, name: str) -> None:
    """シーンを作る。

    ★作っても現在のシーンは変わらない（実測で確認）。配信中に足しても
    画面が飛ばない。
    """
    client.create_scene(name)


def remove_scene(client, name: str) -> None:
    """シーンを削除する。

    ★そのシーンでしか使っていないソースは一緒に失われる。他のシーンにも
    置いてあるソースは残る（実測で確認）。呼び出し側で必ず確認を取ること。
    """
    client.remove_scene(name)


def rename_scene(client, old_name: str, new_name: str) -> None:
    """シーンの名前を変える。"""
    client.set_scene_name(old_name, new_name)


def fetch_transitions(client) -> list:
    """使えるトランジションの一覧。取れなければ空リスト。"""
    from . import scenes  # 循環参照を避けるため関数内 import

    try:
        resp = client.get_scene_transition_list()
    except Exception:  # noqa: BLE001
        return []
    return scenes.parse_transitions(getattr(resp, "transitions", None) or [])


def fetch_scene_transition(client, scene_name: str):
    """シーンごとのトランジション設定を読む。

    設定されていなければ name も duration も None が返る
    （＝全体の設定に従う。実測で確認）。
    """
    from . import scenes  # 循環参照を避けるため関数内 import

    try:
        resp = client.get_scene_scene_transition_override(scene_name)
    except Exception:  # noqa: BLE001
        return scenes.SceneTransition()
    name = getattr(resp, "transition_name", None)
    duration = getattr(resp, "transition_duration", None)
    return scenes.SceneTransition(
        name=str(name or scenes.USE_GLOBAL),
        duration_ms=int(duration) if isinstance(duration, (int, float))
        else None)


def apply_scene_transition(
    client, scene_name: str, name: str = "", duration_ms=None
) -> None:
    """シーンごとのトランジションを設定する。

    name を空にすると解除して全体の設定に戻る（OBSへは None を送る。
    実測で解除できることを確認済み）。
    """
    client.set_scene_scene_transition_override(
        scene_name, name or None, duration_ms)


def fetch_special_input_names(client) -> list[str]:
    """グローバル音声デバイスの名前を返す。

    ★OBS本体の[設定→音声]で決めるマイク・デスクトップ音声のこと。
    これらは**シーンに属さず、全シーンで常に有効**なので、シーンへ
    足す必要が無い（足せてしまうが、一覧に二重に現れて混乱するだけ）。
    実測: この環境では mic1 が「マイク」で、シーンのソース一覧には
    現れないのに音声入力一覧には出る。
    """
    try:
        resp = client.get_special_inputs()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for attr in ("desktop1", "desktop2", "mic1", "mic2", "mic3", "mic4"):
        value = getattr(resp, attr, None)
        if value:
            out.append(str(value))
    return out


def add_source_to_scene(client, scene_name: str, source_name: str) -> None:
    """既にあるソースを、別のシーンにも置く。

    ★コピーではなく同じソースを共有する。片方で設定を変えると両方に効く
    （マイクを2つのシーンに置く、といった使い方のためのもの）。
    """
    client.create_scene_item(scene_name, source_name, True)


def fetch_input_list_raw(client):
    """入力一覧の生の応答を返す（名前の重複を避けるためだけに使う）。"""
    return client.get_input_list()


def fetch_input_names(client) -> list[str]:
    """すべての入力名を並べる（種別を問わない）。"""
    try:
        resp = client.get_input_list()
    except Exception:  # noqa: BLE001
        return []
    return [str(it["inputName"]) for it in getattr(resp, "inputs", []) or []
            if isinstance(it, dict) and it.get("inputName")]


def create_source(client, scene: str, name: str, kind: str) -> None:
    """新しいソースを既定設定で作り、シーンへ置く。

    ★設定は空で作る。既定のまま作って、あとから設定ダイアログで
    詰めてもらう方針（作成時に設定まで組み立てると、種別ごとの
    分岐がここに溜まってしまう）。
    シーンアイテムは有効にする（作った直後から見える・聞こえる）。
    """
    client.create_input(scene, name, kind, {}, True)


def remove_source(client, name: str) -> None:
    """ソースを削除する。

    ★これは入力そのものの削除。**すべてのシーンから消える**し、
    設定も失われる。呼び出し側で必ず確認を取ること。
    """
    client.remove_input(name)


def fetch_creatable_kinds(client) -> list[str]:
    """このOBSで作れる入力の種別を並べる。取れなければ空リスト。

    こちらの表（core/sources.py）に載っていても、OBSの版や環境に
    よっては存在しないことがあるので、突き合わせに使う。
    """
    try:
        resp = client.get_input_kind_list(False)
    except Exception:  # noqa: BLE001
        return []
    return [str(k) for k in getattr(resp, "input_kinds", None) or []]


def create_media_input(client, scene: str, name: str, path: str) -> None:
    """ローカル音声ファイル再生用のメディアソースを作成する。

    restart_on_activate は OBS の既定が True だが、True のままだと
    シーンを切り替えるたびに勝手に頭出し・停止が起き、こちらが起こして
    いない再生イベントが飛んで読み上げが暴れる。BGM 用途では False。
    looping=True にしておくと終端で頭に戻るだけになり、周回ごとの
    「再生が終わりました」も飛ばない。
    """
    client.create_input(
        scene, name, props.MEDIA_KIND,
        {
            "is_local_file": True,
            "local_file": path,
            "looping": True,
            "restart_on_activate": False,
            "clear_on_media_end": False,
        },
        True,
    )


def trigger_media_action(client, name: str, action: str) -> None:
    """メディア操作（再生・一時停止・停止・最初から）を送る。

    ★メディアでない入力に投げても成功が返り、OBS側で黙って捨てられる。
    呼び出し前に種別を確認すること。
    """
    client.trigger_media_input_action(name, action)


def fetch_media_status(client, name: str):
    """(再生状態, 再生位置ms, 長さms) を返す。取れなければ ("", None, None)。

    位置と長さは再生中・一時停止のときしか返らない（それ以外は None）。
    """
    try:
        resp = client.get_media_input_status(name)
    except Exception:  # noqa: BLE001
        return ("", None, None)
    state = str(getattr(resp, "media_state", "") or "")
    cursor = getattr(resp, "media_cursor", None)
    duration = getattr(resp, "media_duration", None)
    if not isinstance(cursor, (int, float)):
        cursor = None
    if not isinstance(duration, (int, float)):
        duration = None
    return (state, cursor, duration)


def fetch_monitor_type(client, name: str) -> str:
    """音声モニタリングの設定を取得する。音声を持たない入力なら空文字。"""
    try:
        resp = client.get_input_audio_monitor_type(name)
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(resp, "monitor_type", "") or "")


def set_monitor_type(client, name: str, mon_type: str) -> None:
    """音声モニタリングを設定する（自分の耳に返すかどうか）。

    OBSの既定は「オフ」＝配信・録画には乗るが自分には聞こえない。
    モニターの出力先デバイスは OBS 本体の[設定→音声]側の設定で、
    obs-websocket からは変更できない（読むこともできない）。
    """
    client.set_input_audio_monitor_type(name, mon_type)


# ------------------------------------------------------------
# カメラ（映像キャプチャデバイス）
# ------------------------------------------------------------
def press_properties_button(client, name: str, prop: str) -> None:
    """入力のプロパティにあるボタンを押す。

    ★カメラの有効・無効はこれで切り替える。設定として active を書いても
    値が変わるだけでデバイスは止まらない（実測で確認）。詳細は
    core/camera.py の冒頭。
    """
    client.press_input_properties_button(name, prop)


def toggle_camera_active(client, name: str) -> None:
    """カメラの有効・無効を切り替える。

    ボタンは押すたびに反転するので、結果を知るには押す前の状態を
    読んでおくこと（camera.next_state_after_toggle）。反映には
    1〜2秒かかるので、読み上げは待ってから確かめる。
    """
    from . import camera  # 循環参照を避けるため関数内 import

    press_properties_button(client, name, camera.ACTIVATE_BUTTON)


def fetch_camera_names(client) -> list[str]:
    """映像キャプチャデバイスの入力名を並べる。"""
    from . import camera  # 循環参照を避けるため関数内 import

    return fetch_input_names_by_kind(client, camera.CAMERA_KIND)


def fetch_camera_state(client, name: str, scene_name: str = ""):
    """カメラ1台の状態を読む（設定・機材名・映像の有無・表示状態）。

    ★active は設定から読む。書いた値とは違い、読んだ値は実態と一致する
    （ボタンで切り替えたときに OBS が更新するため。実測で確認）。
    映像が来ているかは、設定ではなくシーンアイテムの映像サイズで見る。
    """
    from . import camera  # 循環参照を避けるため関数内 import

    settings = fetch_merged_settings(client, name, camera.CAMERA_KIND)
    device_id = str(settings.get("video_device_id", "") or "")
    # 機材名は選択肢一覧から引く（設定値はデバイスのパスで読み上げに向かない）
    device_name = ""
    for it in fetch_property_items(client, name, "video_device_id"):
        if str(it.get("itemValue", "") or "") == device_id:
            device_name = str(it.get("itemName", "") or "")
            break
    width = 0.0
    visible = None
    if scene_name:
        for item in fetch_scene_items(client, scene_name):
            if item.name == name:
                width = item.source_width
                visible = item.enabled
                break
    return camera.build_state(
        name, settings, device_name, width, visible)


def fetch_unused_camera_devices(client, camera_names=None) -> list[str]:
    """つながっているのに、どのソースでも使っていない機材の名前。

    「ウェブカメラはつないであるのにOBSに出ていない」を知らせるため。
    候補一覧はどのカメラ入力から引いても同じ（機材はPCに1組しかない）
    ので、1つあれば引ける。
    """
    from . import camera  # 循環参照を避けるため関数内 import

    names = list(camera_names if camera_names is not None
                 else fetch_camera_names(client))
    if not names:
        return []
    used = []
    for name in names:
        settings = fetch_merged_settings(client, name, camera.CAMERA_KIND)
        value = settings.get("video_device_id")
        if value:
            used.append(value)
    items = fetch_property_items(client, names[0], "video_device_id")
    return camera.unused_devices(items, used)


def open_properties_dialog(client, name: str) -> None:
    """OBS本体側のプロパティ画面を開く（未対応種別の逃げ道）。

    OBS側にモーダルが出て obs_navi からは閉じられないので、呼んだ直後に
    必ず案内を読むこと。
    """
    client.open_input_properties_dialog(name)


# ------------------------------------------------------------
# 録画の音声トラック割り当て（core/tracks.py）
# ------------------------------------------------------------
def fetch_input_audio_tracks(client, name: str):
    """入力がどのトラックへ音を出しているか（トラック1〜6のオン・オフ）。

    取れなければ None（音声を持たない入力・接続断）。空の並びと区別する。
    """
    from . import tracks  # 循環参照を避けるため関数内 import

    try:
        resp = client.get_input_audio_tracks(name)
    except Exception:  # noqa: BLE001
        return None
    raw = getattr(resp, "input_audio_tracks", None)
    if not isinstance(raw, dict):
        return None
    return tracks.parse_input_tracks(raw)


def set_input_audio_track(client, name: str, number: int, on: bool) -> None:
    """入力のトラック1本だけを入り切りする（ほかのトラックは触らない）。

    ★SetInputAudioTracks は渡したトラックだけを書き換える。全部を送ると、
    読んでから送るまでの間に OBS 本体で変えられた分を巻き戻してしまう。
    """
    client.set_input_audio_tracks(name, {str(int(number)): bool(on)})


def fetch_record_tracks(client) -> dict:
    """録画するトラックの設定を読む。

    返すのは {"section", "tracks"（並び。読めなければ None）, "quality"}。
    出力モードでセクションが変わる（簡易=SimpleOutput / 詳細=AdvOut）。
    """
    from . import recording, tracks  # 循環参照を避けるため関数内 import

    mode = fetch_profile_parameter(client, "Output", "Mode")
    section = recording.output_section(mode)
    raw = fetch_profile_parameter(client, section, tracks.REC_TRACKS_KEY)
    quality = ""
    if section == recording.SECTION_SIMPLE:
        quality = fetch_profile_parameter(client, section, "RecQuality")
    return {"section": section, "tracks": tracks.mask_to_tracks(raw),
            "quality": quality}


def apply_record_tracks(client, section: str, states) -> None:
    """録画するトラックを書く（RecTracks）。

    ★次に録画を始めたときから効く（録画フォーマットと同じく、動いている
    録画には効かない）。呼ぶ側で録画中は断ること。
    """
    from . import tracks  # 循環参照を避けるため関数内 import

    apply_profile_parameter(client, section, tracks.REC_TRACKS_KEY,
                            str(tracks.tracks_to_mask(states)))
