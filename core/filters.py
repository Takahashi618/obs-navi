# -*- coding: utf-8 -*-
"""音声フィルターの設定項目の表と、その純ロジック（wx・obsws非依存）。

解く問題:
OBS本体のフィルター画面はスクリーンリーダーで読めない（このプロジェクトの
出発点にある弱点そのもの）。0.7.0 でフィルターの一覧とオン・オフはできる
ようにしたが、**中身の設定（ノイズ抑制の強さ、コンプレッサーの比率など）は
触れないまま**だった。ここはその設定を扱えるようにするための表。

props.py と同じ方針:
- obs-websocket は**フィルターのプロパティ一覧を返すAPIを持たない**
  （入力用の GetInputPropertiesListPropertyItems に相当するものが無い）。
  そのため扱う項目はここで手で定義する
- 載せるのは実測で確認できたキーだけ。推測でキーを書くと overlay=True で
  「誰も読まない設定キー」を書き込む事故になる
- 表に無い種別は UI 側で「このアプリでは変えられません」に縮退する

★キーと既定値は 2026-08-27 に実機（OBS 32.2.2）の
  GetSourceFilterDefaultSettings で実測した値。
★数値の範囲は OBS本体のスライダーの範囲に合わせてある。これだけは
  APIから取れないので、外れていたら実機で確かめて直すこと。範囲を外しても
  OBSは値を受け取ってしまい、本体の画面に出ない値になるだけで害は小さい。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# フィルター設定を書くときは常に上書きマージ。props.apply_input_settings と
# 同じ理由（overlay=False は指定しなかった設定を既定へ戻す）。


@dataclass(frozen=True)
class FilterProp:
    """フィルターの編集できる設定項目1つの定義。"""

    key: str            # OBSのfilterSettingsのキー
    label: str          # 日本語ラベル（そのまま読み上げ名になる）
    type: str           # "float" | "int" | "choice" | "bool" | "source"
    min_value: float = 0.0
    max_value: float = 0.0
    unit: str = ""      # 読み上げに付ける単位（「デシベル」「ミリ秒」など）
    # type="choice" のときの選択肢。(OBSに渡す値, 読み上げ用の日本語)
    choices: tuple = ()
    # その項目が意味を持つ条件（key, value）。合わないときは一覧に出さない。
    # 例: ノイズ抑制の抑制レベルは method=speex のときだけ効く
    depends_on: tuple = ()


# ノイズ抑制の方式。実測の既定は v2 が rnnoise、旧版が speex。
# NVIDIA のノイズ除去は専用SDKが入っている環境にだけ現れるが、
# 一覧に出せるかを API から判定できないので載せない
# （選べない値を読み上げても選択肢が増えるだけで判断を惑わせる）。
#
# ★選択肢のラベルに読点を入れないこと。一覧の行は「ラベル、値」の形なので、
#   値に読点が入ると区切りが分からなくなる（「方式、標準、品質重視」が
#   3項目に聞こえる）。props.py の PRIORITY_JP が同じ理由で読点を避けている。
#   説明を足したいときは空白で区切る。
_SUPPRESS_METHODS = (
    ("rnnoise", "標準 品質がよい"),
    ("speex", "軽量 CPUに優しい"),
)
_DETECTORS = (
    ("RMS", "平均 なめらか"),
    ("peak", "ピーク 素早い"),
)
_EXPANDER_PRESETS = (
    ("expander", "エキスパンダー ゆるやかに下げる"),
    ("gate", "ゲート しっかり閉じる"),
)

# 種別 → 編集できる項目。使用頻度順に並べる（先頭ほど触ることが多い）。
FILTER_TABLE: dict[str, list[FilterProp]] = {
    "noise_suppress_filter_v2": [
        FilterProp("method", "方式", "choice", choices=_SUPPRESS_METHODS),
        FilterProp("suppress_level", "抑制レベル", "int",
                   min_value=-60, max_value=0, unit="デシベル",
                   depends_on=("method", "speex")),
    ],
    "noise_suppress_filter": [
        FilterProp("method", "方式", "choice", choices=_SUPPRESS_METHODS),
        FilterProp("suppress_level", "抑制レベル", "int",
                   min_value=-60, max_value=0, unit="デシベル",
                   depends_on=("method", "speex")),
    ],
    "noise_gate_filter": [
        FilterProp("open_threshold", "開くしきい値", "float",
                   min_value=-96.0, max_value=0.0, unit="デシベル"),
        FilterProp("close_threshold", "閉じるしきい値", "float",
                   min_value=-96.0, max_value=0.0, unit="デシベル"),
        FilterProp("attack_time", "開く速さ", "int",
                   min_value=0, max_value=500, unit="ミリ秒"),
        FilterProp("hold_time", "開いたままの時間", "int",
                   min_value=0, max_value=1000, unit="ミリ秒"),
        FilterProp("release_time", "閉じる速さ", "int",
                   min_value=0, max_value=1000, unit="ミリ秒"),
    ],
    "compressor_filter": [
        FilterProp("ratio", "比率", "float",
                   min_value=1.0, max_value=32.0, unit="対1"),
        FilterProp("threshold", "しきい値", "float",
                   min_value=-60.0, max_value=0.0, unit="デシベル"),
        FilterProp("attack_time", "効き始める速さ", "int",
                   min_value=1, max_value=500, unit="ミリ秒"),
        FilterProp("release_time", "戻る速さ", "int",
                   min_value=1, max_value=1000, unit="ミリ秒"),
        FilterProp("output_gain", "出力ゲイン", "float",
                   min_value=-32.0, max_value=32.0, unit="デシベル"),
        FilterProp("sidechain_source", "サイドチェーンの元", "source"),
    ],
    "upward_compressor_filter": [
        FilterProp("ratio", "比率", "float",
                   min_value=1.0, max_value=20.0, unit="対1"),
        FilterProp("threshold", "しきい値", "float",
                   min_value=-60.0, max_value=0.0, unit="デシベル"),
        FilterProp("attack_time", "効き始める速さ", "int",
                   min_value=1, max_value=500, unit="ミリ秒"),
        FilterProp("release_time", "戻る速さ", "int",
                   min_value=1, max_value=1000, unit="ミリ秒"),
        FilterProp("output_gain", "出力ゲイン", "float",
                   min_value=-32.0, max_value=32.0, unit="デシベル"),
        FilterProp("knee_width", "かかり始めのなめらかさ", "int",
                   min_value=0, max_value=20, unit="デシベル"),
        FilterProp("detector", "検出のしかた", "choice", choices=_DETECTORS),
    ],
    "limiter_filter": [
        FilterProp("threshold", "しきい値", "float",
                   min_value=-60.0, max_value=0.0, unit="デシベル"),
        FilterProp("release_time", "戻る速さ", "int",
                   min_value=1, max_value=1000, unit="ミリ秒"),
    ],
    "expander_filter": [
        FilterProp("ratio", "比率", "float",
                   min_value=1.0, max_value=20.0, unit="対1"),
        FilterProp("threshold", "しきい値", "float",
                   min_value=-60.0, max_value=0.0, unit="デシベル"),
        FilterProp("attack_time", "効き始める速さ", "int",
                   min_value=1, max_value=100, unit="ミリ秒"),
        FilterProp("release_time", "戻る速さ", "int",
                   min_value=1, max_value=1000, unit="ミリ秒"),
        FilterProp("output_gain", "出力ゲイン", "float",
                   min_value=-32.0, max_value=32.0, unit="デシベル"),
        FilterProp("detector", "検出のしかた", "choice", choices=_DETECTORS),
        FilterProp("presets", "動作の型", "choice", choices=_EXPANDER_PRESETS),
    ],
    "gain_filter": [
        FilterProp("db", "ゲイン", "float",
                   min_value=-30.0, max_value=30.0, unit="デシベル"),
    ],
    "basic_eq_filter": [
        FilterProp("low", "低音", "float",
                   min_value=-20.0, max_value=20.0, unit="デシベル"),
        FilterProp("mid", "中音", "float",
                   min_value=-20.0, max_value=20.0, unit="デシベル"),
        FilterProp("high", "高音", "float",
                   min_value=-20.0, max_value=20.0, unit="デシベル"),
    ],
    # 設定を持たないが、オン・オフだけで意味があるフィルター。
    # 表には空で載せる（「変えられません」ではなく「設定はありません」と
    # 言い分けるため）。
    "invert_polarity_filter": [],
}


@dataclass
class FilterKindInfo:
    """追加できるフィルター1種類の情報（一覧に出すため）。"""

    kind: str
    label: str          # 読み上げ用の名前
    hint: str = ""      # 何のためのものかの一言
    props: list = field(default_factory=list)


# 音声入力に追加できるフィルター。よく使う順に並べる。
# ★async_delay_filter（音声遅延）は載せていない。obs-websocket の
#   CreateSourceFilter で作ろうとしても**作られない**ことを実測で確認した
#   （エラーも出ず一覧に現れない）。作れないものを候補に出すと、選んでも
#   何も起きない機能になるため外してある。
# ★vst_filter は載せていない。プラグインのパスとバイナリの状態を持つので、
#   このアプリの数値入力では設定できない。
AUDIO_FILTER_KINDS: list[FilterKindInfo] = [
    FilterKindInfo(
        "noise_suppress_filter_v2", "ノイズ抑制",
        "エアコンやパソコンのファンなど、ずっと鳴っている音を減らします"),
    FilterKindInfo(
        "noise_gate_filter", "ノイズゲート",
        "小さい音のときは音を止めます。話していない間の物音を消せます"),
    FilterKindInfo(
        "compressor_filter", "コンプレッサー",
        "大きい音を抑えて音量を揃えます。声が聞き取りやすくなります"),
    FilterKindInfo(
        "limiter_filter", "リミッター",
        "決めた大きさを超えないようにします。音割れを防げます"),
    FilterKindInfo(
        "gain_filter", "ゲイン",
        "音量を上げ下げします。マイクが小さいときに使います"),
    FilterKindInfo(
        "basic_eq_filter", "イコライザー",
        "低音・中音・高音の量を変えます"),
    FilterKindInfo(
        "expander_filter", "エキスパンダー",
        "小さい音をさらに小さくします。ノイズゲートよりゆるやかです"),
    FilterKindInfo(
        "upward_compressor_filter", "アップワードコンプレッサー",
        "小さい音を持ち上げます。ささやき声を聞こえやすくします"),
    FilterKindInfo(
        "invert_polarity_filter", "位相反転",
        "音の波を反転します。2本のマイクが打ち消し合うときに使います"),
]

# 「マイクに入れるならまずこれ」の並び。追加ダイアログの初期選択に使う。
RECOMMENDED_FIRST = "noise_suppress_filter_v2"

# サイドチェーンの「なし」を表すOBS側の値。
SIDECHAIN_NONE = "none"


def specs_for_kind(kind: str) -> list[FilterProp]:
    """種別の編集できる項目一覧。表に無い種別なら空リスト。

    ★空リストは2つの意味を持ち得るので、呼び出し側は is_known_kind と
    合わせて使うこと（表にあって項目0＝設定なし／表に無い＝非対応）。
    """
    return FILTER_TABLE.get(kind, [])


def is_known_kind(kind: str) -> bool:
    """この種別を表で扱っているか。"""
    return kind in FILTER_TABLE


def visible_specs(kind: str, settings: dict | None) -> list[FilterProp]:
    """今の設定値で意味を持つ項目だけを返す。

    ノイズ抑制の「抑制レベル」は方式が speex のときしか効かない。
    効かない項目を一覧に出すと、変えても何も起きない行を触らせることに
    なるので、条件に合うものだけ出す。
    """
    values = settings or {}
    out: list[FilterProp] = []
    for spec in specs_for_kind(kind):
        if spec.depends_on:
            key, want = spec.depends_on
            if values.get(key) != want:
                continue
        out.append(spec)
    return out


def clamp(spec: FilterProp, value):
    """値を項目の範囲へ収める。数値でなければそのまま返す。"""
    if spec.type not in ("float", "int"):
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num != num:  # NaN
        return spec.min_value
    num = max(spec.min_value, min(spec.max_value, num))
    return int(round(num)) if spec.type == "int" else round(num, 3)


def choice_label(spec: FilterProp, value) -> str:
    """選択肢の値を読み上げ用の日本語にする。無ければ値そのまま。"""
    for raw, label in spec.choices:
        if raw == value:
            return label
    return str(value)


def merge_defaults(defaults: dict | None, current: dict | None) -> dict:
    """既定値の上に現在値を重ねる。

    GetSourceFilter は「明示的に保存されている値」しか返さない
    （作った直後は空の辞書。実測で確認）。そのため現在値の表示には
    必ず既定値とのマージが要る。props.merge_settings と同じ理由。
    """
    out: dict = dict(defaults or {})
    out.update(current or {})
    return out


def free_filter_name(base: str, existing) -> str:
    """既存と衝突しないフィルター名を作る。

    同じ種別を2つ足すこと自体は正当（例: 段の違うコンプレッサー）なので、
    名前だけ空いているものに変える。
    """
    names = set(existing or ())
    if base not in names:
        return base
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in names:
            return candidate
    return base
