# -*- coding: utf-8 -*-
"""config モジュールのテスト（一時ディレクトリで読み書きを検証）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Config, read_obs_websocket_config  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        c = Config(host="127.0.0.1", port=4455, silence_seconds=45.0)
        c.save(p)
        loaded = Config.load(p)
        check("host往復", loaded.host == "127.0.0.1", loaded.host)
        check("silence_seconds往復", loaded.silence_seconds == 45.0,
              str(loaded.silence_seconds))


def test_sr_sources_default_and_roundtrip() -> None:
    c = Config()
    names = [s["name"] for s in c.sr_sources]
    check("既定でNVDA音声を含む", "NVDA音声" in names, str(names))
    check("既定でPC-Talker音声を含む", "PC-Talker音声" in names, str(names))
    nvda = next(s for s in c.sr_sources if s["name"] == "NVDA音声")
    check("NVDAはデバイス方式", nvda["method"] == "device", str(nvda))
    check("NVDAはCABLE Outputを対象",
          nvda["device_match"] == "CABLE Output", str(nvda))
    check("NVDAのキーはF8", nvda["key"] == "F8", str(nvda))
    pct = next(s for s in c.sr_sources if s["name"] == "PC-Talker音声")
    check("PC-Talkerはアプリ方式", pct["method"] == "app", str(pct))
    check("PC-Talkerの対象はPCTalker.exe",
          pct["exe"] == "PCTalker.exe", str(pct))
    check("PC-TalkerのキーはF9", pct["key"] == "F9", str(pct))
    # カスタム値の往復
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        custom = Config(sr_sources=[
            {"name": "テスト音声", "exe": "test.exe", "key": "F10"},
        ])
        custom.save(p)
        loaded = Config.load(p)
        check("SRソース往復", loaded.sr_sources[0]["name"] == "テスト音声",
              str(loaded.sr_sources))


def test_unknown_keys_ignored() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(
            json.dumps({"host": "h", "unknown_field": 1,
                        "sr_audio_input_name": "旧フィールド"}),
            encoding="utf-8")
        loaded = Config.load(p)
        check("未知キーを無視", loaded.host == "h", loaded.host)
        check("既定値を維持", loaded.port == 4455, str(loaded.port))
        # 旧フィールドは無視され、sr_sources は既定に戻る
        check("旧SRフィールドを無視しSRソースは既定",
              any(s["name"] == "NVDA音声" for s in loaded.sr_sources),
              str(loaded.sr_sources))


def test_missing_creates_default() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        loaded = Config.load(p)
        check("無ファイルで既定生成", p.exists())
        check("既定host", loaded.host == "localhost", loaded.host)


def test_read_obs_ws_config() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "obs.json"
        p.write_text(json.dumps({
            "server_enabled": True,
            "server_port": 4455,
            "server_password": "secret123",
        }), encoding="utf-8")
        info = read_obs_websocket_config(p)
        check("OBS設定を読める", info is not None)
        if info is not None:
            check("enabled", info.enabled is True)
            check("port", info.port == 4455, str(info.port))
            check("password", info.password == "secret123", info.password)


def test_read_obs_ws_missing() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "nope.json"
        info = read_obs_websocket_config(p)
        check("欠損時はNone", info is None)


def test_read_obs_ws_non_dict() -> None:
    """破損して null や配列になったファイルでも例外を漏らさず None を返すこと。

    以前は raw.get(...) の AttributeError が素通りし、resolve_connection
    経由で接続処理まで突き抜けて無言で落ちていた。
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "obs.json"
        p.write_text("null", encoding="utf-8")
        check("nullはNone", read_obs_websocket_config(p) is None)
        p.write_text("[1, 2]", encoding="utf-8")
        check("配列はNone", read_obs_websocket_config(p) is None)
        p.write_text('"文字列"', encoding="utf-8")
        check("文字列はNone", read_obs_websocket_config(p) is None)


def test_corrupt_file_blocks_save() -> None:
    """壊れた設定ファイルを既定値で上書きしないこと（_unsaveable の要）。"""
    broken = "{ これはJSONではない"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(broken, encoding="utf-8")
        loaded = Config.load(p)
        check("破損ファイルでも既定値で起動できる",
              loaded.host == "localhost", loaded.host)
        loaded.save(p)  # 保存はブロックされ、ファイルは無傷のはず
        check("破損ファイルを既定値で上書きしない",
              p.read_text(encoding="utf-8") == broken)


def test_non_dict_file_blocks_save() -> None:
    """トップレベルが辞書でないJSONも同様に保護されること。"""
    content = "[1, 2, 3]"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(content, encoding="utf-8")
        loaded = Config.load(p)
        check("非辞書JSONでも既定値で起動できる",
              loaded.host == "localhost", loaded.host)
        loaded.save(p)
        check("非辞書JSONを上書きしない",
              p.read_text(encoding="utf-8") == content)


def test_normal_config_still_saves() -> None:
    """破損時の保存ブロックが、正常なファイルの保存を妨げないこと。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        Config().save(p)
        loaded = Config.load(p)
        loaded.host = "example"
        loaded.save(p)
        saved = json.loads(p.read_text(encoding="utf-8"))
        check("正常ファイルは保存できる", saved["host"] == "example",
              str(saved.get("host")))


def test_sr_sources_normalized() -> None:
    """手編集で壊れた sr_sources でも起動時に KeyError で死なないこと。"""
    c = Config(sr_sources=None)
    check("nullは既定へ",
          any(s["name"] == "NVDA音声" for s in c.sr_sources),
          str(c.sr_sources))
    c = Config(sr_sources="NVDA")
    check("文字列は既定へ",
          any(s["name"] == "NVDA音声" for s in c.sr_sources),
          str(c.sr_sources))
    c = Config(sr_sources=[
        "ゴミ", {"exe": "x.exe"}, {"name": "正しい", "key": "F10"}])
    names = [s["name"] for s in c.sr_sources]
    check("不正エントリを除去し正しいものだけ残す", names == ["正しい"],
          str(names))
    c = Config(sr_sources=["ゴミ", {"exe": "x.exe"}])
    check("全要素が不正なら既定へ（書き損じとみなす）",
          any(s["name"] == "NVDA音声" for s in c.sr_sources),
          str(c.sr_sources))
    check("空リストは「使わない」の意図として尊重",
          Config(sr_sources=[]).sr_sources == [])


def test_game_switch_lists_normalized() -> None:
    """audio_sources / extra_kinds の型ゆれを配列へ正規化すること。"""
    c = Config(game_switch={"audio_sources": "ゲーム音"})
    check("文字列の audio_sources は配列へ",
          c.game_switch["audio_sources"] == ["ゲーム音"],
          str(c.game_switch["audio_sources"]))
    c = Config(game_switch={"audio_sources": 5})
    check("不正型の audio_sources は既定へ",
          c.game_switch["audio_sources"] == ["ゲーム音"],
          str(c.game_switch["audio_sources"]))
    c = Config(game_switch={"audio_sources": ["ゲーム音", 3, ""]})
    check("配列内の不正要素は落とす",
          c.game_switch["audio_sources"] == ["ゲーム音"],
          str(c.game_switch["audio_sources"]))
    c = Config(video_switch={"extra_kinds": "foo_source"})
    check("文字列の extra_kinds は配列へ",
          c.video_switch["extra_kinds"] == ["foo_source"],
          str(c.video_switch["extra_kinds"]))


def test_record_defaults() -> None:
    """録画まわりの既定値が揃っていること（設定ファイルが古くても補う）。"""
    c = Config()
    check("一時停止の再通知は5分", c.record["pause_reminder_seconds"] == 300.0)
    check("空き容量の警告は10GB", c.record["disk_warn_mb"] == 10240.0)
    check("強い警告は2GB", c.record["disk_critical_mb"] == 2048.0)
    check("空き容量を見る間隔は60秒", c.record["disk_check_seconds"] == 60.0)
    check("ファイル名を読む", c.record["announce_file_name"] is True)
    check("一時停止キー", c.record["pause_hotkey"] == "F5")
    check("チャプターキー", c.record["chapter_hotkey"] == "F12")
    # 古い設定ファイル（record が無い）でもキーが揃うこと
    old = Config(record={"disk_warn_mb": 5120.0})
    check("足りないキーは既定で埋まる",
          old.record["pause_reminder_seconds"] == 300.0)
    check("書いた値は残る", old.record["disk_warn_mb"] == 5120.0)


def test_record_numbers_normalized() -> None:
    """手編集で型が崩れても、タイマーの中で落ちないよう数値へ寄せること。"""
    c = Config(record={"pause_reminder_seconds": "600"})
    check("数字の文字列は数値へ",
          c.record["pause_reminder_seconds"] == 600.0,
          repr(c.record["pause_reminder_seconds"]))
    c = Config(record={"disk_warn_mb": None})
    check("nullは既定へ", c.record["disk_warn_mb"] == 10240.0,
          repr(c.record["disk_warn_mb"]))
    c = Config(record={"disk_check_seconds": "はやく"})
    check("読めない文字列は既定へ", c.record["disk_check_seconds"] == 60.0,
          repr(c.record["disk_check_seconds"]))
    # ★0 は「無効にする」という意図なので、既定へ戻してはいけない
    c = Config(record={"pause_reminder_seconds": 0})
    check("0は無効の意図として尊重",
          c.record["pause_reminder_seconds"] == 0.0,
          repr(c.record["pause_reminder_seconds"]))
    c = Config(record={"disk_warn_mb": -5})
    check("負値は0（無効）へ寄せる", c.record["disk_warn_mb"] == 0.0,
          repr(c.record["disk_warn_mb"]))
    c = Config(record="こわれた")
    check("record自体が不正型なら既定へ",
          c.record["pause_reminder_seconds"] == 300.0)


def test_level_read_defaults() -> None:
    c = Config()
    check("既定は名前順（順番の指定なし）", c.level_read["order"] == [],
          str(c.level_read))
    check("既定はミュートも読む", c.level_read["skip_muted"] is False,
          str(c.level_read))
    # 古い設定ファイル（level_read が無い）でも読める
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(json.dumps({"host": "localhost"}), encoding="utf-8")
        loaded = Config.load(p)
        check("項目が無い設定でも既定で補う",
              loaded.level_read == {"order": [], "skip_muted": False},
              str(loaded.level_read))


def test_level_read_normalized() -> None:
    # 手編集で壊れていても落ちない形に寄せる
    c = Config(level_read={"order": "マイク", "skip_muted": 1})
    check("文字列1つは配列へ", c.level_read["order"] == ["マイク"],
          str(c.level_read))
    check("真偽値へ寄せる", c.level_read["skip_muted"] is True,
          str(c.level_read))
    c = Config(level_read={"order": ["マイク", "", 5, "マイク", "BGM"]})
    check("空・非文字列・重複を落とす",
          c.level_read["order"] == ["マイク", "BGM"], str(c.level_read))
    c = Config(level_read="こわれている")
    check("辞書でなければ既定へ",
          c.level_read == {"order": [], "skip_muted": False},
          str(c.level_read))


def test_level_read_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        c = Config(level_read={"order": ["ゲーム音", "マイク"],
                               "skip_muted": True})
        c.save(p)
        loaded = Config.load(p)
        check("順番が往復", loaded.level_read["order"] == ["ゲーム音", "マイク"],
              str(loaded.level_read))
        check("ミュート設定が往復", loaded.level_read["skip_muted"] is True,
              str(loaded.level_read))


def test_list_order_defaults_and_normalized() -> None:
    c = Config()
    check("既定はOBSと同じ順（指定なし）",
          c.list_order == {"scenes": [], "items": []}, str(c.list_order))
    c = Config(list_order={"scenes": "配信", "items": ["A", "", 5, "A", "B"]})
    check("文字列1つは配列へ", c.list_order["scenes"] == ["配信"],
          str(c.list_order))
    check("空・非文字列・重複を落とす",
          c.list_order["items"] == ["A", "B"], str(c.list_order))
    c = Config(list_order="こわれている")
    check("辞書でなければ既定へ",
          c.list_order == {"scenes": [], "items": []}, str(c.list_order))
    # 古い設定ファイル（list_order が無い）でも読める
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        p.write_text(json.dumps({"host": "localhost"}), encoding="utf-8")
        loaded = Config.load(p)
        check("項目が無い設定でも既定で補う",
              loaded.list_order == {"scenes": [], "items": []},
              str(loaded.list_order))


def test_list_order_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        c = Config(list_order={"scenes": ["雑談", "配信"], "items": ["BGM"]})
        c.save(p)
        loaded = Config.load(p)
        check("シーンの並びが往復",
              loaded.list_order["scenes"] == ["雑談", "配信"],
              str(loaded.list_order))
        check("ソースの並びが往復",
              loaded.list_order["items"] == ["BGM"], str(loaded.list_order))


def test_skip_muted_accepts_hand_edited_text() -> None:
    """★"false" を True にしない。

    設定は手編集も想定しているので、文字列で書かれた真偽値を bool() に
    かけると書いた本人の意図と逆に効く（"false" は空でないので True）。
    画面が見えないと、ミュート中が読み上げから消えた理由に辿り着けない。
    """
    for text, want in (("false", False), ("0", False), ("no", False),
                       ("off", False), ("", False),
                       ("true", True), ("1", True), ("yes", True)):
        c = Config(level_read={"order": [], "skip_muted": text})
        check(f"文字列 {text!r} は {want}",
              c.level_read["skip_muted"] is want, str(c.level_read))
    c = Config(level_read={"order": [], "skip_muted": None})
    check("null は既定（読む）", c.level_read["skip_muted"] is False,
          str(c.level_read))


def test_save_reports_whether_it_wrote() -> None:
    """★書けたかどうかを呼ぶ側が判るようにする。

    読めなかった設定を上書きしないのは正しいが、黙って何もしないと
    「保存しました」と読み上げてしまい、再起動して初めて消えていると
    分かる（耳では確かめようが無い）。
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cfg.json"
        check("書けたら True", Config().save(p) is True, "")
        blocked = Config._unsaveable()
        check("読めなかった設定は保存しない", blocked.save(p) is False, "")
        check("保存禁止を外から見られる", blocked.save_blocked is True, "")
        check("普通の設定は禁止でない", Config().save_blocked is False, "")


def test_rename_follows_every_name_keyed_setting() -> None:
    """★名前で覚えている設定は全部追従させる。

    1つでも漏れると「名前を変えただけで機能が黙って止まる」。
    UI 層ではなくここに置いてあるのは、漏れをテストで見つけるため。
    """
    c = Config()
    c.sr_sources = [{"name": "NVDA音声", "key": "F8"}]
    c.game_switch["video_source"] = "ゲームキャプチャ"
    c.game_switch["audio_sources"] = ["ゲーム音", "NVDA音声"]
    c.bgm["source_name"] = "BGM"
    c.level_read["order"] = ["NVDA音声", "マイク"]
    c.list_order["items"] = ["NVDA音声"]
    c.list_order["scenes"] = ["配信"]
    check("入力名の変更が通る", c.rename_input("NVDA音声", "読み上げ音声"))
    check("スクリーンリーダー音声", c.sr_sources[0]["name"] == "読み上げ音声",
          str(c.sr_sources))
    check("ゲーム切り替えの音声",
          c.game_switch["audio_sources"] == ["ゲーム音", "読み上げ音声"],
          str(c.game_switch))
    check("レベル読み上げの順番",
          c.level_read["order"] == ["読み上げ音声", "マイク"],
          str(c.level_read))
    check("ソース一覧の並び順", c.list_order["items"] == ["読み上げ音声"],
          str(c.list_order))
    check("シーンの並びは触らない", c.list_order["scenes"] == ["配信"],
          str(c.list_order))
    check("ゲーム映像も追従", c.rename_input("ゲームキャプチャ", "ゲーム画面")
          and c.game_switch["video_source"] == "ゲーム画面",
          str(c.game_switch))
    check("BGMも追従", c.rename_input("BGM", "音楽")
          and c.bgm["source_name"] == "音楽", str(c.bgm))
    check("シーン名はシーンの並びだけ",
          c.rename_scene("配信", "本番")
          and c.list_order["scenes"] == ["本番"], str(c.list_order))
    check("変化が無ければ False", c.rename_input("居ない", "誰か") is False)
    check("同じ名前なら False", c.rename_input("マイク", "マイク") is False)
    # 新しい名前が既にあるときは重複を作らず古い方を消す
    c2 = Config()
    c2.level_read["order"] = ["A", "B"]
    c2.rename_input("A", "B")
    check("重複を作らない", c2.level_read["order"] == ["B"],
          str(c2.level_read))


def run() -> tuple[int, int]:
    for fn in (
        test_roundtrip,
        test_sr_sources_default_and_roundtrip,
        test_unknown_keys_ignored,
        test_missing_creates_default,
        test_read_obs_ws_config,
        test_read_obs_ws_missing,
        test_read_obs_ws_non_dict,
        test_corrupt_file_blocks_save,
        test_non_dict_file_blocks_save,
        test_normal_config_still_saves,
        test_sr_sources_normalized,
        test_game_switch_lists_normalized,
        test_record_defaults,
        test_record_numbers_normalized,
        test_level_read_defaults,
        test_level_read_normalized,
        test_level_read_roundtrip,
        test_list_order_defaults_and_normalized,
        test_list_order_roundtrip,
        test_skip_muted_accepts_hand_edited_text,
        test_save_reports_whether_it_wrote,
        test_rename_follows_every_name_keyed_setting,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _results.append((f"{fn.__name__} が例外で失敗", False, repr(exc)))
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    return passed, failed


def results() -> list[tuple[str, bool, str]]:
    return _results


if __name__ == "__main__":
    p, f = run()
    for nm, ok, detail in _results:
        mark = "OK" if ok else "NG"
        line = f"[{mark}] {nm}"
        if not ok and detail:
            line += f" -> {detail}"
        print(line)
    print(f"config: {p} passed, {f} failed")
