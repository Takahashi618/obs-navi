# -*- coding: utf-8 -*-
"""録画の音声トラック割り当ての純ロジック（wx・obsws 非依存）。

解く問題:
録画するとき、ゲームの音・スクリーンリーダーの声・マイクを別々の
トラックに分けておくと、後で音量を直せる（編集の後工程で）。
OBS 本体でこれを決める場所は2つあり、どちらも目で見るチェックの表の作りで、
スクリーンリーダーでは扱いにくい。

★0.19.0 で足した。このファイルは OS に依存しない。

1. ソースごとに、どのトラックへ音を出すか（オーディオの詳細プロパティ）
   → obs-websocket の GetInputAudioTracks / SetInputAudioTracks。
     値は {"1": true, "2": false, …, "6": false} の形
2. 録画するトラックはどれか（設定→出力→録画の「音声トラック」）
   → プロファイル設定の RecTracks。**ビットの合計**
     （トラック1が 1、トラック2が 2、トラック3が 4 … トラック1〜4 なら 15）。
     出力モードが簡易なら SimpleOutput、詳細なら AdvOut のセクションにある

★2つが噛み合っていないと音が録れない（ソースはトラック5へ出しているのに、
録画はトラック1〜4しか録らない、など）。画面を見ないと気づけないので、
食い違いを言い当てる（unrecorded_inputs）。

★RecTracks をそのまま読むと「音声トラック 15」のように聞こえ、
トラック15があるように誤解する（0.10.0 の「録画設定の確認」がそうだった）。
読み上げは必ず track_list_text を通す。
"""
from __future__ import annotations

# OBS の音声トラックの数（OBS 本体の表と同じ6本）
TRACK_COUNT = 6
TRACK_NUMBERS = tuple(range(1, TRACK_COUNT + 1))

# プロファイル設定のキー（簡易・詳細のどちらのセクションでも同じ名前）
REC_TRACKS_KEY = "RecTracks"

# 勧める割り当て（マニュアルの表と同じ）。
# トラック1は「全部入り」＝配信と同じ音。2〜4 で別々に直せる。
# ★自動では当てない。どのソースがゲームの音かは名前からは決められない
#   ので、案内（読み上げ）に使うだけ
RECOMMENDED = (
    ("ゲームや音楽の音", (1, 2)),
    ("スクリーンリーダーの声", (1, 3)),
    ("マイク", (1, 4)),
)


def parse_input_tracks(raw) -> tuple[bool, ...]:
    """GetInputAudioTracks の値を、トラック1〜6のオン・オフの並びにする。

    キーは文字列（"1"）でも整数でもよい。無いトラックはオフとみなす。
    """
    data = raw if isinstance(raw, dict) else {}
    out = []
    for n in TRACK_NUMBERS:
        value = data.get(str(n), data.get(n, False))
        out.append(bool(value))
    return tuple(out)


def tracks_payload(states) -> dict:
    """オン・オフの並びを SetInputAudioTracks に渡す形にする。"""
    states = tuple(states)
    return {str(n): bool(states[n - 1]) for n in TRACK_NUMBERS
            if n - 1 < len(states)}


def toggled(states, number: int) -> tuple[bool, ...]:
    """トラック number（1始まり）だけを反転した並び。範囲外ならそのまま。"""
    out = list(states)
    if 1 <= number <= len(out):
        out[number - 1] = not out[number - 1]
    return tuple(out)


def mask_to_tracks(value) -> tuple[bool, ...] | None:
    """RecTracks（ビットの合計）をオン・オフの並びにする。読めなければ None。"""
    try:
        mask = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if mask < 0:
        return None
    return tuple(bool(mask & (1 << (n - 1))) for n in TRACK_NUMBERS)


def tracks_to_mask(states) -> int:
    """オン・オフの並びを RecTracks（ビットの合計）にする。"""
    mask = 0
    for i, on in enumerate(tuple(states)[:TRACK_COUNT]):
        if on:
            mask |= 1 << i
    return mask


def on_numbers(states) -> list[int]:
    """オンのトラックの番号（1始まり）。"""
    return [i + 1 for i, on in enumerate(tuple(states)) if on]


def track_list_text(states) -> str:
    """オンのトラックを読み上げ用にする。

    「トラック1」「トラック1と2」「トラック1から4」「トラック1、3、5」。
    続いている3本以上は「から」でまとめる（全部を読むと長い）。
    どれもオンでなければ空文字（呼ぶ側が「どこにも出していない」と言う）。
    """
    nums = on_numbers(states)
    if not nums:
        return ""
    if len(nums) == 1:
        return f"トラック{nums[0]}"
    if len(nums) == 2:
        return f"トラック{nums[0]}と{nums[1]}"
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"トラック{nums[0]}から{nums[-1]}"
    return "トラック" + "、".join(str(n) for n in nums)


def unrecorded_inputs(input_tracks: dict, recorded) -> list[str]:
    """録画されるトラックに1本も出していない入力の名前（並びは元の順）。

    input_tracks は {入力名: オン・オフの並び}。recorded は録画する
    トラックのオン・オフの並び（RecTracks を mask_to_tracks したもの）。
    ★どのトラックにも出していない入力も含める（そもそも録れない）。
    """
    rec = tuple(recorded or ())
    out = []
    for name, states in (input_tracks or {}).items():
        if not any(on and i < len(rec) and rec[i]
                   for i, on in enumerate(tuple(states))):
            out.append(name)
    return out


def simple_mode_note(section: str, rec_quality: str) -> str:
    """簡易出力で、トラックの設定が効かない場合の注意。効くなら空文字。

    ★簡易出力（OBS の日本語表示では出力モード「基本」）で録画品質が
    「配信と同じ」（RecQuality=Stream）のときは、
    録画は配信と同じ音（1本）になり、RecTracks は使われない。
    """
    if section == "SimpleOutput" and str(rec_quality or "") == "Stream":
        return ("出力モードが基本で、録画品質が配信と同じなので、"
                "録画のトラックの設定は効きません。OBS本体の設定の出力で、"
                "出力モードを詳細にするか、録画品質を配信と同じ以外にしてください")
    return ""
