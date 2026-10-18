# -*- coding: utf-8 -*-
"""keymap モジュールのテスト。

★このテストが守っているのは「一覧に書いてあるキーが実際に効くこと」。
見えない利用者にとって、どのキーが何をするかは読み上げでしか確かめ
られない。一覧が実際と1つでもずれると、押しても何も起きないキーを
探し続けることになる。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import keymap  # noqa: E402
from core.config import Config  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_global_bindings_use_config_modifier() -> None:
    cfg = Config()
    got = keymap.global_bindings(cfg)
    check("割り当てがある", len(got) >= 10, str(len(got)))
    labels = {aid: keymap.global_key_label(cfg, aid) for aid, *_ in got}
    check("基準は Ctrl+Alt", labels["state"] == "Ctrl+Alt+F5",
          labels["state"])
    # 粗い刻みと後から足したものは1つ強い段（Ctrl+Alt+Shift）
    check("粗い音量は強い段",
          labels["volume_down_coarse"] == "Ctrl+Alt+Shift+F1",
          labels["volume_down_coarse"])
    check("録画一時停止は強い段",
          labels["record_pause"] == "Ctrl+Alt+Shift+F5",
          labels["record_pause"])
    check("チャプターは強い段",
          labels["chapter"] == "Ctrl+Alt+Shift+F12", labels["chapter"])
    check("カメラは強い段",
          labels["camera"] == "Ctrl+Alt+Shift+F11", labels["camera"])


def test_modifier_change_follows_config() -> None:
    """★修飾キーを変えたら、一覧の表示もついてくること。

    設定だけ変えて一覧が古いままだと、書いてあるキーが効かなくなる。
    """
    cfg = Config(global_hotkey_modifier="Ctrl+Shift")
    check("基準が変わる",
          keymap.global_key_label(cfg, "state") == "Ctrl+Shift+F5",
          keymap.global_key_label(cfg, "state"))
    # 基準に Shift があるので、強い段は Alt が足される
    check("強い段も追従",
          keymap.global_key_label(cfg, "chapter") == "Ctrl+Shift+Alt+F12",
          keymap.global_key_label(cfg, "chapter"))


def test_disabled_globals() -> None:
    cfg = Config(global_hotkeys_enabled=False)
    check("無効なら割り当て無し", keymap.global_bindings(cfg) == [])
    check("表示も空", keymap.global_key_label(cfg, "state") == "")
    text = keymap.help_text(cfg)
    # ★無効なことを黙らない。書いていないと「効かないキーを探す」ことになる
    check("無効だと一覧で伝える", "無効になっています" in text, text)


def test_config_key_can_be_cleared() -> None:
    """設定でキー名を空にしたら割り当てないこと（約束どおり）。"""
    cfg = Config()
    cfg.record["chapter_hotkey"] = ""
    ids = [aid for aid, *_ in keymap.global_bindings(cfg)]
    check("空にすると割り当てない", "chapter" not in ids, str(ids))
    check("表示も空", keymap.global_key_label(cfg, "chapter") == "")
    # 他の割り当ては残る
    check("他は残る", "camera" in ids, str(ids))


def test_config_key_can_be_changed() -> None:
    cfg = Config()
    cfg.camera["hotkey"] = "F9"
    check("キー名を変えられる",
          keymap.global_key_label(cfg, "camera") == "Ctrl+Alt+Shift+F9",
          keymap.global_key_label(cfg, "camera"))


def test_sr_sources_are_included() -> None:
    """スクリーンリーダー音声は設定の数だけ増える（データ駆動）。"""
    cfg = Config()
    ids = [aid for aid, *_ in keymap.global_bindings(cfg)]
    check("NVDAが入る", "sr:NVDA音声" in ids, str(ids))
    check("PC-Talkerが入る", "sr:PC-Talker音声" in ids, str(ids))
    check("素押しキーも引ける",
          keymap.sr_key_label(cfg, "NVDA音声") == "F8")
    check("無い名前は空", keymap.sr_key_label(cfg, "無い") == "")


def test_no_duplicate_bindings_by_default() -> None:
    """★既定の設定でキーが重なっていないこと。

    重なると、あとから登録した方が黙って効かなくなる。
    """
    check("既定では重複なし",
          keymap.duplicate_bindings(Config()) == [],
          str(keymap.duplicate_bindings(Config())))


def test_duplicate_detected() -> None:
    """設定でキーをぶつけたら気づけること。"""
    cfg = Config()
    # 粗い音量の F1 とチャプターをぶつける
    cfg.record["chapter_hotkey"] = "F1"
    dupes = keymap.duplicate_bindings(cfg)
    check("重複を見つける", len(dupes) == 1, str(dupes))
    check("どのキーか言う", "Ctrl+Alt+Shift+F1" in dupes[0], str(dupes))
    check("何と何かを言う",
          "チャプター" in dupes[0] and "音量" in dupes[0], str(dupes))


def test_window_and_menu_labels() -> None:
    cfg = Config()
    check("ウィンドウ内のキー", keymap.window_key_label(cfg, "bgm") == "Ctrl+B")
    check("無い項目は空", keymap.window_key_label(cfg, "無い") == "")
    # ★メニューにはウィンドウ内のキーを優先して出す（そちらが短く、
    #   メニューを開いている＝画面にいる状況で実際に使えるため）
    check("ウィンドウ内を優先",
          keymap.menu_accel(cfg, "record_pause", "record_pause") == "Ctrl+P",
          keymap.menu_accel(cfg, "record_pause", "record_pause"))
    # ウィンドウ内に無ければグローバルを出す
    check("無ければグローバル",
          keymap.menu_accel(cfg, "", "chapter") == "Ctrl+Alt+Shift+F12")
    check("どちらも無ければ空", keymap.menu_accel(cfg, "", "") == "")


def test_help_text_structure() -> None:
    cfg = Config()
    text = keymap.help_text(cfg)
    # ★段ごとの見出しが要る。素押しのF5と Ctrl+Alt+F5 は別物なので、
    #   どこで効くのかが分からないと使えない
    check("画面内の見出し", "【OBSナビの画面にいるとき】" in text, text[:80])
    check("グローバルの見出し", "【どこにいても効くキー】" in text, text[:80])
    check("素押しのF5が出る", "\nF5  状態読み上げ" in text, text[:200])
    check("グローバルのF5も出る", "Ctrl+Alt+F5  状態読み上げ" in text)
    # リスト上でしか意味を持たない操作も載せる（メニューに出せないため）
    check("Enterの説明", "Enter" in text)
    check("アプリケーションキーの説明", "アプリケーションキー" in text)
    check("メニューの開き方", "メニューバーを開く" in text)
    check("SR音声が出る", "NVDA音声の配信オン・オフ" in text)


def test_help_rows_scopes() -> None:
    rows = keymap.help_rows(Config())
    scopes = {r.scope for r in rows}
    check("両方の段がある",
          keymap.SCOPE_WINDOW in scopes and keymap.SCOPE_GLOBAL in scopes,
          str(scopes))
    check("すべてに説明がある", all(r.action for r in rows))
    check("すべてにキー名がある", all(r.keys for r in rows))


# ------------------------------------------------------------
# 0.14.1: キー名の検証と正規化
# ------------------------------------------------------------
def test_normalize_key_name() -> None:
    """★手編集の揺れを救い、使えない値をそろって落とすこと。

    "f12" が黙って効かなくなるのは酷なので救う。英字や Delete は
    どの面（登録・メニュー・一覧）にも出してはいけない値。
    """
    check("小文字を救う", keymap.normalize_key_name("f12") == "F12")
    check("空白を落とす", keymap.normalize_key_name(" F5 ") == "F5")
    check("正規の値はそのまま", keymap.normalize_key_name("F1") == "F1")
    check("英字は捨てる", keymap.normalize_key_name("A") == "")
    check("Deleteは捨てる", keymap.normalize_key_name("Delete") == "")
    check("F13は捨てる", keymap.normalize_key_name("F13") == "")
    check("空は空", keymap.normalize_key_name("") == "")
    check("Noneでも落ちない", keymap.normalize_key_name(None) == "")


def test_config_key_normalizes() -> None:
    """設定から引いたキーも正規化されること（登録と表示が同じ値を見る）。"""
    cfg = Config()
    cfg.record["chapter_hotkey"] = "f12"
    check("小文字の設定でも登録される",
          keymap.global_key_label(cfg, "chapter") == "Ctrl+Alt+Shift+F12",
          keymap.global_key_label(cfg, "chapter"))
    cfg.record["chapter_hotkey"] = "Delete"
    ids = [aid for aid, *_ in keymap.global_bindings(cfg)]
    check("使えない値はどこにも出ない", "chapter" not in ids, str(ids))
    check("表示も空", keymap.global_key_label(cfg, "chapter") == "")


def test_invalid_key_warnings() -> None:
    """★使えないキー名は黙って捨てず、場所つきで報告すること。

    黙って消すと「設定したのに効かない」で終わる。何がなぜ捨てられた
    かを起動時の読み上げに乗せるための関数。
    """
    check("既定の設定では何も無い",
          keymap.invalid_key_warnings(Config()) == [],
          str(keymap.invalid_key_warnings(Config())))
    cfg = Config()
    cfg.record["chapter_hotkey"] = "Delete"
    got = keymap.invalid_key_warnings(cfg)
    check("録画キーの誤りを報告", len(got) == 1, str(got))
    check("どの機能か言う", "チャプター" in got[0], str(got))
    check("何が駄目か言う", "Delete" in got[0], str(got))
    check("直し方を言う", "F1からF12" in got[0], str(got))
    cfg2 = Config()
    cfg2.sr_sources[0]["key"] = "A"
    got2 = keymap.invalid_key_warnings(cfg2)
    check("SRキーの誤りも報告", len(got2) == 1, str(got2))
    check("どのソースか言う", "NVDA音声" in got2[0], str(got2))
    # 正規化で救える値は誤りではない
    cfg3 = Config()
    cfg3.record["pause_hotkey"] = "f5"
    check("救える値は報告しない",
          keymap.invalid_key_warnings(cfg3) == [])


def test_sr_entries_validate() -> None:
    """★sr_sources の走査は sr_entries に一本化され、検証がかかること。

    英字キーの設定が menu のアクセラレータに生のまま載ると、リストの
    頭文字ジャンプが奪われる（0.14.0 のレビューで実測確認された穴）。
    """
    cfg = Config()
    entries = keymap.sr_entries(cfg)
    check("既定は2件", len(entries) == 2, str(entries))
    check("キーが正規化されている",
          [k for _s, _n, k in entries] == ["F8", "F9"], str(entries))
    cfg.sr_sources[0]["key"] = "A"
    entries2 = keymap.sr_entries(cfg)
    check("使えないキーは空文字になる（項目は残る）",
          entries2[0][2] == "" and entries2[0][1] == "NVDA音声",
          str(entries2))
    check("sr_key_label も空を返す",
          keymap.sr_key_label(cfg, "NVDA音声") == "")
    ids = [aid for aid, *_ in keymap.global_bindings(cfg)]
    check("登録からも消える", "sr:NVDA音声" not in ids, str(ids))
    rows = [r.keys for r in keymap.help_rows(cfg)
            if "NVDA音声" in r.action]
    check("一覧からも消える", rows == [], str(rows))
    check("文言は sr_toggle_label が持つ",
          keymap.sr_toggle_label("NVDA音声") == "NVDA音声の配信オン・オフ")


# ------------------------------------------------------------
# 0.14.1: 登録順（衝突時の勝者）
# ------------------------------------------------------------
def test_sr_binding_order_wins_collisions() -> None:
    """★SRトグルは音量・便利キーより先に登録されること。

    RegisterHotKey は先勝ちなので、並び順が衝突時の勝者を決める。
    0.13.0 は SR が先（勝ち）だったのに 0.14.0 で末尾へ回って
    負ける側に変わっていた。0.13.0 の優先順位に戻す。
    """
    ids = [aid for aid, *_ in keymap.global_bindings(Config())]
    sr = ids.index("sr:NVDA音声")
    check("SRは音量より先", sr < ids.index("volume_down"),
          str(ids))
    check("SRはBGMより先", sr < ids.index("bgm"), str(ids))
    check("SRはリプレイより先", sr < ids.index("replay"), str(ids))
    check("状態・レベルはSRより先",
          ids.index("state") < sr and ids.index("levels") < sr, str(ids))


# ------------------------------------------------------------
# 0.14.1: 全段の重複チェック
# ------------------------------------------------------------
def test_duplicate_detects_window_tier() -> None:
    """★素押し段の衝突も見つけること。

    SRキーは設定で変えられる唯一の素押しキーなので、固定キー
    （F5=状態読み上げ 等）や SR 同士とぶつけたときに黙って片方が
    効かなくなる。0.14.0 はグローバル段しか見ていなかった。
    """
    cfg = Config()
    cfg.sr_sources[0]["key"] = "F5"
    dupes = keymap.duplicate_bindings(cfg)
    window = [d for d in dupes if d.startswith("F5")]
    check("固定キーとの衝突を見つける", len(window) == 1, str(dupes))
    check("両方の名前を言う",
          "状態読み上げ" in window[0] and "NVDA音声" in window[0],
          str(window))
    # SR同士の同キー
    cfg2 = Config()
    cfg2.sr_sources[1]["key"] = "F8"
    dupes2 = keymap.duplicate_bindings(cfg2)
    both = [d for d in dupes2 if "NVDA音声" in d and "PC-Talker音声" in d]
    check("SR同士の衝突を見つける", len(both) >= 1, str(dupes2))


def test_duplicate_check_works_without_globals() -> None:
    """★グローバルキーを無効にしても窓内の重複は調べること。

    0.14.0 では global_bindings が空になりチェック全体が空振りして、
    完全に無警告のまま片方が効かなくなっていた。
    """
    cfg = Config(global_hotkeys_enabled=False)
    cfg.sr_sources[0]["key"] = "F5"
    dupes = keymap.duplicate_bindings(cfg)
    check("無効でも窓内は見つける",
          any(d.startswith("F5") for d in dupes), str(dupes))


def test_duplicate_global_labels() -> None:
    """登録失敗の原因切り分け用（自分の重複を他アプリのせいにしない）。"""
    check("既定は空", keymap.duplicate_global_labels(Config()) == set())
    cfg = Config()
    cfg.record["chapter_hotkey"] = "F1"
    labels = keymap.duplicate_global_labels(cfg)
    check("重複キーの表示名を返す",
          labels == {"Ctrl+Alt+Shift+F1"}, str(labels))


# ------------------------------------------------------------
# 0.14.1: 窓内キーの振り分けも keymap から
# ------------------------------------------------------------
def test_parse_window_key() -> None:
    check("Fキー", keymap.parse_window_key("F5") == (False, False, "F5"))
    check("小文字も救う",
          keymap.parse_window_key("f5") == (False, False, "F5"))
    check("Ctrl+英字",
          keymap.parse_window_key("Ctrl+B") == (True, False, "B"))
    check("小文字の英字も救う",
          keymap.parse_window_key("ctrl+p") == (True, False, "P"))
    check("Ctrl+Shift+英字",
          keymap.parse_window_key("Ctrl+Shift+S") == (True, True, "S"))
    check("Ctrl+Shift+英字も小文字を救う",
          keymap.parse_window_key("ctrl+shift+r") == (True, True, "R"))
    check("素の英字は不正", keymap.parse_window_key("B") is None)
    check("Shift+英字だけは不正（文字入力を奪う）",
          keymap.parse_window_key("Shift+S") is None)
    check("Shift+Ctrl の順は不正（表記を1つにする）",
          keymap.parse_window_key("Shift+Ctrl+S") is None)
    check("Ctrl+Shift+Fキーは不正（グローバル段の担当）",
          keymap.parse_window_key("Ctrl+Shift+F5") is None)
    check("全角英字は不正",
          keymap.parse_window_key("Ctrl+Ｓ") is None)
    check("知らない形は不正", keymap.parse_window_key("Alt+F4") is None)
    check("空は不正", keymap.parse_window_key("") is None)


def test_window_bindings_cover_plan() -> None:
    """★WINDOW_PLAN の全行が振り分けに変換できること。

    ここで変換できない行があると、表示（メニュー・一覧）には出るのに
    動作しないキーになる。定義の誤りは例外で気づかせる。
    """
    got = keymap.window_bindings(Config())
    check("行数が一致", len(got) == len(keymap.WINDOW_PLAN), str(got))
    ids = [aid for aid, _c, _s, _k, _d in got]
    check("action_id が揃う",
          ids == [aid for aid, _k, _d in keymap.WINDOW_PLAN], str(ids))
    by_id = {aid: (ctrl, shift, key) for aid, ctrl, shift, key, _d in got}
    check("F5は素押し", by_id["state"] == (False, False, "F5"))
    check("BGMはCtrl+B", by_id["bgm"] == (True, False, "B"))
    check("録画一時停止はCtrl+P",
          by_id["record_pause"] == (True, False, "P"))
    check("ヘルプはF1", by_id["help"] == (False, False, "F1"))


def test_stream_record_keys() -> None:
    """0.18.0: 配信・録画の開始と停止。Shift を足すと停止、で対にする。"""
    got = {aid: (ctrl, shift, key)
           for aid, ctrl, shift, key, _d in keymap.window_bindings(Config())}
    check("配信を開始はCtrl+S", got["stream_start"] == (True, False, "S"))
    check("配信を停止はCtrl+Shift+S",
          got["stream_stop"] == (True, True, "S"))
    check("録画を開始はCtrl+R", got["record_start"] == (True, False, "R"))
    check("録画を停止はCtrl+Shift+R",
          got["record_stop"] == (True, True, "R"))
    # 振り分け表のキー（修飾の組み合わせ＋キー）が窓内で重ならないこと。
    # 重なると後の行が前の行を黙って上書きする
    combos = [(c, s, k) for c, s, k in got.values()]
    check("窓内の固定キーに重なりが無い",
          len(combos) == len(set(combos)), str(combos))
    cfg = Config()
    check("メニューに出すキー（開始）",
          keymap.menu_accel(cfg, "stream_start") == "Ctrl+S")
    check("メニューに出すキー（停止）",
          keymap.menu_accel(cfg, "record_stop") == "Ctrl+Shift+R")
    check("メニューの文言とキー一覧の説明が同じ",
          keymap.action_label("stream_stop") == "配信を停止")
    text = keymap.help_text(cfg)
    for line in ("Ctrl+S  配信を開始", "Ctrl+Shift+S  配信を停止",
                 "Ctrl+R  録画を開始", "Ctrl+Shift+R  録画を停止"):
        check(f"キー一覧に「{line}」", line in text)
    check("既定の設定で重複の警告が出ない",
          keymap.duplicate_bindings(cfg) == [],
          str(keymap.duplicate_bindings(cfg)))


def test_stream_record_global_keys() -> None:
    """0.18.2: ゲーム中でも効く配信・録画のキー（Ctrl+Alt+Shift+F6〜F9）。"""
    cfg = Config()
    want = {"stream_start": "Ctrl+Alt+Shift+F6",
            "stream_stop": "Ctrl+Alt+Shift+F7",
            "record_start": "Ctrl+Alt+Shift+F8",
            "record_stop": "Ctrl+Alt+Shift+F9"}
    for aid, label in want.items():
        got = keymap.global_key_label(cfg, aid)
        check(f"{aid} は {label}", got == label, got)
    check("メニューは窓内キーの方を出す（短い方）",
          keymap.menu_accel(cfg, "stream_start") == "Ctrl+S")
    text = keymap.help_text(cfg)
    glob = text.split("【" + keymap.SCOPE_LABEL[keymap.SCOPE_GLOBAL] + "】")[1]
    check("キー一覧の「どこにいても効くキー」に載る",
          "Ctrl+Alt+Shift+F6  配信を開始" in glob
          and "Ctrl+Alt+Shift+F9  録画を停止" in glob, glob)
    # 0.18.3: 配信のグローバルキーは2回押しが要る。一覧で分かるように
    check("キー一覧で配信は2回続けて押すと分かる",
          "Ctrl+Alt+Shift+F6  配信を開始（2回続けて押す）" in glob
          and "Ctrl+Alt+Shift+F7  配信を停止（2回続けて押す）" in glob, glob)
    check("録画は1回で効くので書かない",
          "Ctrl+Alt+Shift+F8  録画を開始\n" in glob + "\n", glob)
    check("メニューの文言は窓内キーの説明のまま",
          keymap.action_label("stream_start") == "配信を開始")
    labels = [keymap.hotkeys.hotkey_label(t, k)
              for _a, t, k, _d in keymap.global_bindings(cfg)]
    check("グローバルの段で重なりが無い",
          len(labels) == len(set(labels)), str(labels))
    # 0.18.3: 利用者が録画一時停止を F6 にしていたら、そちらが今までどおり
    # 効く（あとから来た配信キーが既存の設定を奪わない）
    cfg.record["pause_hotkey"] = "F6"
    dupes = keymap.duplicate_bindings(cfg)
    check("設定のキーとぶつけたら設定のキーが効く",
          any("録画の一時停止・再開 が効きます" in d
              and "配信を開始（2回続けて押す） は効きません" in d
              for d in dupes), str(dupes))
    order = [aid for aid, _t, _k, _d in keymap.global_bindings(cfg)]
    check("設定のキーを先に登録する（先勝ち）",
          order.index("record_pause") < order.index("stream_start"),
          str(order))
    cfg.global_hotkeys_enabled = False
    check("グローバル無効なら出さない",
          keymap.global_key_label(cfg, "stream_start") == "")


def test_duplicate_names_the_winner() -> None:
    """★重複の警告は「実際に効く方」を言う。

    段ごとに勝つ側が違う（グローバルは先勝ち、窓内の固定キーは固定側が
    勝ち、ただしF1はSRへ譲り、SR同士は先勝ち）。一般則で書くと半分の
    場面で実際と逆を読み上げてしまう。
    """
    cfg = Config()
    cfg.sr_sources = [
        {"name": "A", "key": "F8"},
        {"name": "B", "key": "F8"},
        {"name": "C", "key": "F1"},
        {"name": "D", "key": "F5"},
    ]
    dupes = keymap.duplicate_bindings(cfg)
    window = [d for d in dupes if not d.startswith("Ctrl")]
    joined = "／".join(window)
    check("SR同士は先に書いた方が効く",
          "F8（Aの配信オン・オフ が効きます。Bの配信オン・オフ は効きません）"
          in window, joined)
    check("F1はSRへ譲る",
          "F1（Cの配信オン・オフ が効きます。キー操作の一覧 は効きません）"
          in window, joined)
    check("F1以外の固定キーは固定側が勝つ",
          "F5（状態読み上げ が効きます。Dの配信オン・オフ は効きません）"
          in window, joined)
    check("一般則で言わない",
          all("後の方は効きません" not in d for d in dupes), joined)


def test_action_label_is_single_source() -> None:
    """メニューの文言はキー一覧の説明と同じものを引く。"""
    check("窓内キーの説明",
          keymap.action_label("record_pause") == "録画の一時停止・再開",
          keymap.action_label("record_pause"))
    check("設定で変えられるキーの説明",
          keymap.action_label("camera") == "カメラの有効・無効",
          keymap.action_label("camera"))
    check("知らない名前は空", keymap.action_label("nope") == "",
          keymap.action_label("nope"))


def test_context_keys_list_shift_f10() -> None:
    """アプリケーションキーが無いキーボード用の代替を一覧に出す。"""
    keys = [k for k, _d in keymap.CONTEXT_KEYS]
    check("アプリケーションキー", "アプリケーションキー" in keys, str(keys))
    check("Shift＋F10 も載せる", "Shift＋F10" in keys, str(keys))
    enter = dict(keymap.CONTEXT_KEYS)["Enter"]
    check("Enter の説明に配信・録画の一覧がある（0.18.3）",
          "配信・録画" in enter, enter)


TESTS = [
    test_global_bindings_use_config_modifier,
    test_modifier_change_follows_config,
    test_disabled_globals,
    test_config_key_can_be_cleared,
    test_config_key_can_be_changed,
    test_sr_sources_are_included,
    test_no_duplicate_bindings_by_default,
    test_duplicate_detected,
    test_window_and_menu_labels,
    test_help_text_structure,
    test_help_rows_scopes,
    test_normalize_key_name,
    test_config_key_normalizes,
    test_invalid_key_warnings,
    test_sr_entries_validate,
    test_sr_binding_order_wins_collisions,
    test_duplicate_detects_window_tier,
    test_duplicate_check_works_without_globals,
    test_duplicate_global_labels,
    test_parse_window_key,
    test_window_bindings_cover_plan,
    test_stream_record_keys,
    test_stream_record_global_keys,
    test_duplicate_names_the_winner,
    test_action_label_is_single_source,
    test_context_keys_list_shift_f10,
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
        mark = "OK" if ok else "NG"
        line = f"[{mark}] {name}"
        if not ok and detail:
            line += f" -> {detail}"
        print(line)
    print(f"{p} passed, {f} failed")
