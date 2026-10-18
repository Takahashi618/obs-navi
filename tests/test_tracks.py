# -*- coding: utf-8 -*-
"""録画の音声トラック割り当てのテスト（core/tracks.py と、その要求・読み上げ）。

★守っていること:
- RecTracks（ビットの合計）を番号に直して読むこと。「音声トラック 15」と
  読むと、トラック15があるように聞こえる
- 録画されないトラックにしか出していないソースを言い当てること。
  画面を見ないと気づけない、音が録れない食い違い
- ソースのトラックは1本だけ書き換えること（全部を送ると、OBS 本体で
  変えた分を巻き戻す）
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import commands, speech_format, tracks  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


ON12 = (True, True, False, False, False, False)


def test_parse_and_payload() -> None:
    got = tracks.parse_input_tracks({"1": True, "2": True, "3": False})
    check("文字列のキーを読む", got == ON12, str(got))
    check("整数のキーも読む",
          tracks.parse_input_tracks({1: True, 2: True}) == ON12)
    check("無いトラックはオフ", tracks.parse_input_tracks({}) == (False,) * 6)
    check("壊れた値でも6本", len(tracks.parse_input_tracks(None)) == 6)
    payload = tracks.tracks_payload(ON12)
    check("送る形は文字列のキー",
          payload == {"1": True, "2": True, "3": False, "4": False,
                      "5": False, "6": False}, str(payload))
    check("1本だけ反転", tracks.toggled(ON12, 3)[2] is True
          and tracks.toggled(ON12, 3)[:2] == (True, True))
    check("範囲外は変えない", tracks.toggled(ON12, 9) == ON12)


def test_mask() -> None:
    check("1はトラック1", tracks.mask_to_tracks("1") == (True,) + (False,) * 5)
    check("15はトラック1から4",
          tracks.mask_to_tracks(15) == (True,) * 4 + (False,) * 2)
    check("63は全部", tracks.mask_to_tracks("63") == (True,) * 6)
    check("読めなければ None", tracks.mask_to_tracks("x") is None)
    check("空も None", tracks.mask_to_tracks("") is None)
    check("負は None", tracks.mask_to_tracks(-1) is None)
    check("並びから戻す", tracks.tracks_to_mask((True,) * 4 + (False,) * 2) == 15)
    check("往復で同じ", tracks.tracks_to_mask(tracks.mask_to_tracks(42)) == 42)


def test_track_list_text() -> None:
    f = tracks.track_list_text
    check("1本", f((True,) + (False,) * 5) == "トラック1")
    check("2本は「と」", f(ON12) == "トラック1と2")
    check("続いた3本以上は「から」",
          f((True,) * 4 + (False,) * 2) == "トラック1から4")
    check("飛び飛びは読点",
          f((True, False, True, False, True, False)) == "トラック1、3、5")
    check("無ければ空", f((False,) * 6) == "")


def test_unrecorded_and_note() -> None:
    rec = tracks.mask_to_tracks(15)            # トラック1〜4を録る
    got = tracks.unrecorded_inputs({
        "Logic": (True, True, False, False, False, False),
        "PC-Talker音声": (False,) * 4 + (True, False),  # トラック5だけ
        "マイク": (False,) * 6,                           # どこにも出さない
    }, rec)
    check("録画されないトラックだけのソースを挙げる",
          got == ["PC-Talker音声", "マイク"], str(got))
    check("簡易で配信と同じ品質なら注意",
          "効きません" in tracks.simple_mode_note("SimpleOutput", "Stream"))
    check("簡易でも別の品質なら注意しない",
          tracks.simple_mode_note("SimpleOutput", "Small") == "")
    check("詳細なら注意しない", tracks.simple_mode_note("AdvOut", "") == "")


def test_speech() -> None:
    check("行の文", speech_format.input_track_row(2, True) == "録画のトラック2、オン")
    s = speech_format.input_tracks_changed_speech("Logic", 2, True, ON12)
    check("何をしたか言う", "Logic をトラック2に出しました" in s, s)
    check("今の全体を言う", "今はトラック1と2" in s, s)
    off = speech_format.input_tracks_changed_speech(
        "Logic", 1, False, (False,) * 6)
    check("全部外したら言う", "どのトラックにも出していません" in off, off)
    check("録画の行", speech_format.record_track_row(3, False)
          == "トラック3を録画する、オフ")
    check("録画するトラックが無いと警告",
          "音の無い録画" in speech_format.record_tracks_changed_speech(
              (False,) * 6))
    check("次の録画から効くと言う",
          "次の録画から" in speech_format.record_tracks_changed_speech(ON12))
    over = speech_format.tracks_overview_speech(
        {"Logic": ON12, "マイク": (False,) * 4 + (True, False)},
        tracks.mask_to_tracks(15))
    check("録画するトラックを言う", "録画する音声はトラック1から4" in over, over)
    check("ソースごとに言う", "Logic はトラック1と2" in over, over)
    check("録画に入らないソースを言い当てる",
          "次のソースは録画に入りません。マイク" in over, over)
    check("読めないときも黙らない",
          "読めませんでした" in speech_format.tracks_overview_speech({}, None))
    rec = speech_format.tracks_recommendation_speech()
    check("おすすめは3つ",
          all(w in rec for w in ("ゲーム", "スクリーンリーダー", "マイク")), rec)
    # ★録画設定の確認で RecTracks をそのまま読まない（0.10.0 からの読み方の修正）
    summary = speech_format.record_settings_summary({"tracks": "15"})
    check("録画設定の確認はトラックの番号で読む",
          "トラック1から4" in summary and "15" not in summary, summary)


class _FakeClient:
    """トラックまわりの要求だけを持つ偽のクライアント。"""

    def __init__(self) -> None:
        self.tracks = {"Logic": {"1": True, "2": True, "3": False,
                                 "4": False, "5": False, "6": False}}
        self.sent: list = []
        self.profile = {("Output", "Mode"): "Advanced",
                        ("AdvOut", "RecTracks"): "15"}

    def get_input_audio_tracks(self, name):
        if name not in self.tracks:
            raise RuntimeError("604 does not support audio")
        return SimpleNamespace(input_audio_tracks=dict(self.tracks[name]))

    def set_input_audio_tracks(self, name, track):
        self.sent.append((name, dict(track)))
        self.tracks[name].update(track)

    def get_profile_parameter(self, category, name):
        return SimpleNamespace(
            parameter_value=self.profile.get((category, name), ""),
            default_parameter_value="")

    def set_profile_parameter(self, category, name, value):
        self.profile[(category, name)] = value


def test_commands() -> None:
    c = _FakeClient()
    check("トラックを読む", commands.fetch_input_audio_tracks(c, "Logic") == ON12)
    check("音声が無ければ None",
          commands.fetch_input_audio_tracks(c, "画像") is None)
    commands.set_input_audio_track(c, "Logic", 3, True)
    check("1本だけ送る", c.sent == [("Logic", {"3": True})], str(c.sent))
    info = commands.fetch_record_tracks(c)
    check("詳細出力のセクション", info["section"] == "AdvOut", str(info))
    check("録画するトラック", info["tracks"] == (True,) * 4 + (False,) * 2,
          str(info))
    commands.apply_record_tracks(c, "AdvOut", (True,) * 6)
    check("ビットの合計で書く", c.profile[("AdvOut", "RecTracks")] == "63",
          str(c.profile))
    c.profile[("Output", "Mode")] = "Simple"
    c.profile[("SimpleOutput", "RecQuality")] = "Stream"
    simple = commands.fetch_record_tracks(c)
    check("簡易出力は品質も読む",
          simple["section"] == "SimpleOutput" and simple["quality"] == "Stream",
          str(simple))


TESTS = [
    test_parse_and_payload,
    test_mask,
    test_track_list_text,
    test_unrecorded_and_note,
    test_speech,
    test_commands,
]


def results() -> list[tuple[str, bool, str]]:
    return _results


def run() -> tuple[int, int]:
    _results.clear()
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} が例外", False, repr(exc))
    passed = sum(1 for _n, ok, _d in _results if ok)
    return passed, len(_results) - passed


if __name__ == "__main__":
    p, f = run()
    for name, ok, detail in _results:
        print(("[OK] " if ok else "[NG] ") + name + ("" if ok else f" -> {detail}"))
    print(f"{p} passed, {f} failed")
