# -*- coding: utf-8 -*-
"""speech_format モジュールのテスト。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.speech_format import (  # noqa: E402
    chapter_added_speech,
    chapter_unsupported_speech,
    disk_warning_speech,
    filter_kind_jp,
    filter_list_label,
    filter_toggle_speech,
    fmt_db,
    fmt_seconds,
    fmt_volume_db,
    input_list_label,
    item_move_edge_speech,
    license_notice_speech,
    ai_notice_speech,
    item_moved_speech,
    level_summary,
    config_save_failed_speech,
    order_reset_speech,
    order_saved_speech,
    order_unchanged_speech,
    mute_monitor_caveat,
    onoff_speech,
    path_speech,
    pause_reminder_speech,
    rec_format_jp,
    record_settings_summary,
    record_stopped_speech,
    replay_saved_speech,
    scene_item_list_label,
    scene_item_toggle_speech,
    skip_muted_speech,
    state_summary,
    stats_summary,
    video_already_front_speech,
    timecode_to_speech,
    volume_speech,
)
from core.state import AudioInput, Snapshot  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def test_fmt_db() -> None:
    check("負値はマイナス表現", fmt_db(-18.0) == "マイナス18デシベル", fmt_db(-18.0))
    check("0はゼロ表現", fmt_db(0.0) == "0デシベル", fmt_db(0.0))
    check("正値はプラス表現", fmt_db(3.0) == "プラス3デシベル", fmt_db(3.0))
    check("下限以下は無音", fmt_db(-120.0) == "無音", fmt_db(-120.0))
    check("四捨五入する", fmt_db(-17.6) == "マイナス18デシベル", fmt_db(-17.6))


def test_fmt_volume_db() -> None:
    check("正値はプラス表現", fmt_volume_db(6.0) == "プラス6デシベル",
          fmt_volume_db(6.0))
    check("負値はマイナス表現", fmt_volume_db(-10.0) == "マイナス10デシベル",
          fmt_volume_db(-10.0))
    check("0はゼロ表現", fmt_volume_db(0.0) == "0デシベル", fmt_volume_db(0.0))
    check("下限は最小と読む", fmt_volume_db(-100.0) == "最小",
          fmt_volume_db(-100.0))


def test_fmt_volume_db_differs_from_level() -> None:
    """音量はレベルと違い「無音」で潰さず数値を読むこと。

    -95dB のフェーダー値は「無音」ではなく数値で知りたい（設定値なので）。
    レベル(fmt_db)は -90 以下を「無音」と読むが、音量はそうしない。
    """
    check("レベルなら無音", fmt_db(-95.0) == "無音", fmt_db(-95.0))
    check("音量なら数値を読む", fmt_volume_db(-95.0) == "マイナス95デシベル",
          fmt_volume_db(-95.0))


def test_fmt_volume_db_fraction() -> None:
    """刻みを細かくしたときに、整数に丸めて無反応に聞こえないこと。"""
    check("小数は小数第1位まで読む", fmt_volume_db(5.5) == "プラス5.5デシベル",
          fmt_volume_db(5.5))
    check("負の小数", fmt_volume_db(-2.5) == "マイナス2.5デシベル",
          fmt_volume_db(-2.5))
    check("float32の誤差は整数に寄せる",
          fmt_volume_db(5.999999523162842) == "プラス6デシベル",
          fmt_volume_db(5.999999523162842))


def test_volume_speech() -> None:
    check("名前と音量", volume_speech("マイク", 6.0) == "マイク プラス6デシベル",
          volume_speech("マイク", 6.0))


def test_filter_kind_jp() -> None:
    check("既知の種別は日本語",
          filter_kind_jp("noise_suppress_filter") == "ノイズ抑制",
          filter_kind_jp("noise_suppress_filter"))
    check("コンプレッサー",
          filter_kind_jp("compressor_filter") == "コンプレッサー")
    check("未知の種別はそのまま",
          filter_kind_jp("something_unknown") == "something_unknown")


def test_filter_list_label() -> None:
    check("オン表示", filter_list_label("ノイズ抑制", True) == "ノイズ抑制 オン")
    check("オフ表示", filter_list_label("ノイズ抑制", False) == "ノイズ抑制 オフ")


def test_filter_toggle_speech() -> None:
    check("有効化", filter_toggle_speech("コンプ", True) == "コンプ を有効にしました")
    check("無効化", filter_toggle_speech("コンプ", False) == "コンプ を無効にしました")


def test_scene_item_labels() -> None:
    check("表示中", scene_item_list_label("カメラ", True) == "カメラ 表示中")
    check("非表示", scene_item_list_label("カメラ", False) == "カメラ 非表示")
    # ミュートの語（オン/ミュート中）と混同しない別の語であること
    check("ミュートと別の語",
          "ミュート" not in scene_item_list_label("カメラ", False))


def test_scene_item_toggle_speech() -> None:
    check("表示", scene_item_toggle_speech("カメラ", True) == "カメラ を表示しました")
    check("非表示",
          scene_item_toggle_speech("カメラ", False) == "カメラ を非表示にしました")


def test_stats_summary_healthy() -> None:
    s = stats_summary({
        "cpu": 0.56, "fps": 60.0, "disk_free_mb": 10267.0,
        "render_total": 92428, "render_skipped": 0,
        "output_total": 0, "output_skipped": 0,
    })
    check("CPUを丸めて読む", "CPU 1パーセント" in s, s)
    check("FPSを読む", "エフピーエス 60" in s, s)
    check("描画コマ落ちなし", "描画のコマ落ちなし" in s, s)
    check("output_total=0 なら配信録画のコマ落ちは読まない",
          "配信録画" not in s, s)
    check("空き容量をギガで読む", "ギガバイト" in s, s)


def test_stats_summary_dropped_frames() -> None:
    s = stats_summary({
        "cpu": 40.0, "fps": 59.0,
        "render_total": 1000, "render_skipped": 25,
        "output_total": 2000, "output_skipped": 10,
    })
    check("描画コマ落ちの件数", "描画のコマ落ち 25フレーム" in s, s)
    check("描画コマ落ちの割合", "2.5パーセント" in s, s)
    check("配信録画コマ落ちの件数", "配信録画のコマ落ち 10フレーム" in s, s)


def test_stats_summary_disk_units() -> None:
    check("メガ", "メガバイト" in stats_summary({"disk_free_mb": 500.0}))
    check("ギガ", "ギガバイト" in stats_summary({"disk_free_mb": 2048.0}))
    check("テラ", "テラバイト" in stats_summary({"disk_free_mb": 3 * 1024 * 1024.0}))


def test_stats_summary_empty() -> None:
    check("空なら取得失敗を伝える",
          stats_summary({}) == "統計を取得できませんでした",
          stats_summary({}))


def test_onoff_speech() -> None:
    check("開始", onoff_speech("仮想カメラ", True) == "仮想カメラを開始しました")
    check("停止", onoff_speech("仮想カメラ", False) == "仮想カメラを停止しました")


def test_timecode() -> None:
    check("時分秒", timecode_to_speech("01:02:03") == "1時間2分3秒",
          timecode_to_speech("01:02:03"))
    check("ミリ秒切り捨て", timecode_to_speech("00:00:05.123") == "5秒",
          timecode_to_speech("00:00:05.123"))
    check("分のみ", timecode_to_speech("00:10:00") == "10分0秒",
          timecode_to_speech("00:10:00"))
    check("不正値はそのまま", timecode_to_speech("bad") == "bad")


def test_state_summary() -> None:
    check("未接続", state_summary(Snapshot(connected=False))
          == "OBSに接続していません")
    snap = Snapshot(
        connected=True, streaming=True, stream_timecode="00:05:00",
        recording=False, current_scene="ゲーム",
    )
    s = state_summary(snap)
    check("配信中を含む", "配信中" in s and "5分0秒" in s, s)
    check("録画停止中を含む", "録画停止中" in s, s)
    check("現在シーンを含む", "ゲーム" in s, s)
    # 録画中の分岐（タイムコード付き）
    rec = state_summary(Snapshot(
        connected=True, streaming=False, recording=True,
        record_timecode="00:10:05", current_scene="ゲーム"))
    check("録画中とタイムコードを含む", "録画中" in rec and "10分5秒" in rec, rec)
    check("録画中でも配信停止中を読む", "配信停止中" in rec, rec)


def test_level_summary() -> None:
    check("情報なし", level_summary({}) == "レベル情報がまだありません")
    peaks = {"マイク": -18.0, "ゲーム": -120.0}
    muted = {"ゲーム": True}
    s = level_summary(peaks, muted)
    check("ミュートを反映", "ゲーム ミュート中" in s, s)
    check("レベルを反映", "マイク マイナス18デシベル" in s, s)


def test_level_summary_order() -> None:
    peaks = {"マイク": -18.0, "ゲーム音": -6.0, "BGM": -30.0}
    s = level_summary(peaks, {}, order=["ゲーム音", "マイク"])
    check("設定の順で読む",
          s.index("ゲーム音") < s.index("マイク") < s.index("BGM"), s)


def test_level_summary_skip_muted() -> None:
    peaks = {"マイク": -18.0, "ゲーム音": -6.0}
    muted = {"ゲーム音": True}
    s = level_summary(peaks, muted, skip_muted=True)
    check("ミュートを飛ばす", "ゲーム音" not in s, s)
    check("飛ばしても他は読む", "マイク マイナス18デシベル" in s, s)
    # 既定（飛ばさない）は今までどおり
    s = level_summary(peaks, muted)
    check("既定はミュートも読む", "ゲーム音 ミュート中" in s, s)
    # 全部ミュートで無言にならないこと（キーが効いていないのと
    # 区別が付かなくなるため）
    s = level_summary({"マイク": -60.0}, {"マイク": True}, skip_muted=True)
    check("全部ミュートでも何か言う", "すべてミュート中" in s, s)
    check("件数を言う", "1件" in s, s)


def test_level_setting_speech() -> None:
    got = order_saved_speech(
        "レベル読み上げの順番", ["マイク", "BGM"], True, ["マイク", "BGM"])
    check("順番の保存",
          got == "レベル読み上げの順番を保存しました。2件、最初は マイク", got)
    got = order_saved_speech("シーン一覧の並び順", [], False, [])
    check("空なら戻す先を言う", got.endswith("OBSと同じ順に戻しました"), got)
    # ★件数と先頭は「今あるもの」で言う。設定には今は無い名前も残るので、
    #   そのまま読むと実際に最初に読まれるものと食い違う
    got = order_saved_speech(
        "レベル読み上げの順番", ["旧マイク", "マイク", "BGM"], True,
        ["マイク", "BGM"])
    check("今あるものだけ数える", "2件" in got, got)
    check("今あるものを先頭として言う", "最初は マイク" in got, got)
    got = order_saved_speech("レベル読み上げの順番", ["旧マイク"], True, [])
    check("今あるものが無いときは正直に言う",
          got.endswith("今あるものはありません"), got)
    got = order_unchanged_speech("シーン一覧の並び順")
    check("変えなかったときは保存と言わない",
          "保存" not in got and got == "シーン一覧の並び順は変えませんでした",
          got)
    got = config_save_failed_speech("シーン一覧の並び順")
    check("保存できないときは成功と言わない",
          "保存できませんでした" in got, got)
    check("飛ばす側", skip_muted_speech(True)
          == "ミュート中のソースはレベル読み上げに出しません",
          skip_muted_speech(True))
    check("読む側", "も" in skip_muted_speech(False), skip_muted_speech(False))


def test_order_reset_speech() -> None:
    """★ボタンの文言（終止形）に「ました」を足さない。"""
    check("OBS順へ戻す",
          order_reset_speech(False) == "OBSと同じ順に戻しました",
          order_reset_speech(False))
    check("名前順へ並べ直す",
          order_reset_speech(True) == "名前順に並べ直しました",
          order_reset_speech(True))
    check("壊れた日本語にしない",
          "戻すました" not in order_reset_speech(False)
          and "並べ直すました" not in order_reset_speech(True))
    got = order_reset_speech(False, 2)
    check("落としたものは件数で言う", "今は無いもの2件" in got, got)


def test_item_layer_speech() -> None:
    """重なり順を変えたときは、動いた先の位置を必ず言う。"""
    got = item_moved_speech("ゲームキャプチャ", 2, 5, True)
    check("前に出したことと位置",
          got == "ゲームキャプチャ を前に出しました。5件中、前から2番目", got)
    got = item_moved_speech("画像", 4, 4, False)
    check("後ろに送った側", "後ろに送りました" in got, got)
    check("端は動かせないと言う",
          item_move_edge_speech("画像", True) == "画像 はすでにいちばん前です",
          item_move_edge_speech("画像", True))
    check("後ろの端",
          "いちばん後ろ" in item_move_edge_speech("画像", False),
          item_move_edge_speech("画像", False))
    # ★同じ意味の文を2つ持たない（表記が割れて別物に聞こえる）
    check("映像切り替えの文言と同じもの",
          video_already_front_speech("画像")
          == item_move_edge_speech("画像", True),
          video_already_front_speech("画像"))


def test_input_list_label() -> None:
    check("オン表示", input_list_label("マイク", False) == "マイク オン")
    check("ミュート表示", input_list_label("マイク", True) == "マイク ミュート中")


def test_input_list_label_with_volume() -> None:
    """一覧を辿るだけで音量も分かること。"""
    check("オンと音量",
          input_list_label("マイク", False, 5.0) == "マイク オン プラス5デシベル",
          input_list_label("マイク", False, 5.0))
    check("ミュート中でも音量は出す",
          input_list_label("BGM", True, -6.0) == "BGM ミュート中 マイナス6デシベル",
          input_list_label("BGM", True, -6.0))
    check("音量不明なら出さない",
          input_list_label("マイク", False, None) == "マイク オン",
          input_list_label("マイク", False, None))
    check("0dBも省略せず出す",
          input_list_label("BGM", False, 0.0) == "BGM オン 0デシベル",
          input_list_label("BGM", False, 0.0))


def test_mute_monitor_caveat() -> None:
    """ミュートとモニタリングが食い違うときだけ補足を添えること。

    実機で「BGMをミュートしたのに鳴り続ける」が起きた。ミュートは配信・
    録画に乗せないだけで、自分の耳へ返すモニタリングは止めないため。
    """
    from core.props import (  # noqa: PLC0415
        MONITOR_AND_OUTPUT, MONITOR_NONE, MONITOR_ONLY)

    c = mute_monitor_caveat(True, MONITOR_AND_OUTPUT)
    check("ミュートでもモニタ有効なら聞こえ続けると伝える",
          "自分にはこのまま聞こえます" in c, c)
    check("ミュート＋自分だけ聞くでも伝える",
          "自分にはこのまま聞こえます" in mute_monitor_caveat(True, MONITOR_ONLY),
          mute_monitor_caveat(True, MONITOR_ONLY))
    check("ミュート＋モニタ無しは黙る",
          mute_monitor_caveat(True, MONITOR_NONE) == "",
          mute_monitor_caveat(True, MONITOR_NONE))
    # 逆の落とし穴: 解除しても配信には乗らない（より危ない側）
    c2 = mute_monitor_caveat(False, MONITOR_ONLY)
    check("解除＋自分だけ聞くなら配信に乗らないと伝える",
          "配信には乗りません" in c2, c2)
    check("解除＋自分も配信にもは黙る",
          mute_monitor_caveat(False, MONITOR_AND_OUTPUT) == "",
          mute_monitor_caveat(False, MONITOR_AND_OUTPUT))
    check("解除＋モニタ無しは黙る",
          mute_monitor_caveat(False, MONITOR_NONE) == "")
    check("モニタ設定が取れないときは黙る",
          mute_monitor_caveat(True, "") == "")
    # メディアソースは「ではどうするか」まで案内する
    m = mute_monitor_caveat(True, MONITOR_AND_OUTPUT,
                            "OBS_MEDIA_STATE_PLAYING")
    check("再生中のメディアなら一時停止を案内", "一時停止" in m, m)
    check("メディアでなければ案内しない",
          "一時停止" not in mute_monitor_caveat(True, MONITOR_AND_OUTPUT))


def test_mute_monitor_caveat_media_not_playing() -> None:
    """止まっているメディアには「聞こえ続けます」と言わないこと。

    一時停止中のBGMをミュートしたときに再生中と同じ案内が出ると、
    鳴っていないのに「聞こえます」と言われて混乱する（利用者の指摘）。
    """
    from core.props import MONITOR_AND_OUTPUT, MONITOR_ONLY  # noqa: PLC0415

    for state in ("OBS_MEDIA_STATE_PAUSED", "OBS_MEDIA_STATE_STOPPED",
                  "OBS_MEDIA_STATE_ENDED", "OBS_MEDIA_STATE_NONE"):
        got = mute_monitor_caveat(True, MONITOR_AND_OUTPUT, state)
        check(f"{state} では黙る", got == "", got)
    # 鳴り出す状態は再生中と同じ扱い（放っておけば鳴るため）
    for state in ("OBS_MEDIA_STATE_PLAYING", "OBS_MEDIA_STATE_OPENING",
                  "OBS_MEDIA_STATE_BUFFERING"):
        got = mute_monitor_caveat(True, MONITOR_AND_OUTPUT, state)
        check(f"{state} では案内する", "聞こえます" in got, got)
    # 行き先の話（配信に乗らない）は、止まっていても伝える
    got = mute_monitor_caveat(False, MONITOR_ONLY, "OBS_MEDIA_STATE_PAUSED")
    check("停止中でも配信に乗らないことは伝える",
          "配信には乗りません" in got, got)


# ------------------------------------------------------------
# 録画まわり
# ------------------------------------------------------------
def test_state_summary_paused() -> None:
    # ★一時停止は「録画中」と言い分けられなければ意味がない。
    #   混同すると、録れていない時間があることに最後まで気づけない
    paused = state_summary(Snapshot(
        connected=True, recording=True, record_paused=True,
        record_timecode="00:10:05", current_scene="ゲーム"))
    check("一時停止を言う", "録画一時停止中" in paused, paused)
    check("一時停止のとき単なる録画中とは言わない",
          "録画中" not in paused, paused)
    check("一時停止でもタイムコードは読む", "10分5秒" in paused, paused)
    normal = state_summary(Snapshot(
        connected=True, recording=True, record_paused=False,
        record_timecode="00:10:05"))
    check("通常の録画中は従来どおり", "録画中" in normal, normal)
    check("通常の録画中に一時停止とは言わない",
          "一時停止" not in normal, normal)


def test_fmt_seconds() -> None:
    check("秒だけ", fmt_seconds(45) == "45秒", fmt_seconds(45))
    check("分と秒", fmt_seconds(300) == "5分0秒", fmt_seconds(300))
    check("時間も", fmt_seconds(3725) == "1時間2分5秒", fmt_seconds(3725))
    check("不正値", fmt_seconds(None) == "不明")
    check("負値", fmt_seconds(-1) == "不明")


def test_path_speech() -> None:
    # 区切り記号をそのまま読ませない（「バックスラッシュ」を延々と読む）
    check("スラッシュを読点に", path_speech("F:/Videos") == "F:、Videos",
          path_speech("F:/Videos"))
    check("バックスラッシュも同じ",
          path_speech("F:\\Videos\\OBS") == "F:、Videos、OBS",
          path_speech("F:\\Videos\\OBS"))
    check("空は未設定", path_speech("") == "未設定")


def test_record_stopped_speech() -> None:
    got = record_stopped_speech("F:/Videos/2026-08-27 14-30-05.mp4")
    check("停止を伝える", "録画を停止しました" in got, got)
    check("ファイル名の本体だけ読む", "2026-08-27 14-30-05" in got, got)
    check("フォルダは読まない", "Videos" not in got, got)
    check("拡張子は読まない", ".mp4" not in got, got)
    bare = record_stopped_speech("")
    check("パスが無ければ停止だけ", bare == "録画を停止しました", bare)


def test_replay_saved_speech() -> None:
    got = replay_saved_speech("F:/Videos/Replay 2026-08-27.mp4")
    check("保存を伝える", "リプレイを保存しました" in got, got)
    check("ファイル名を添える", "Replay 2026-08-27" in got, got)
    check("パスが無ければ保存だけ",
          replay_saved_speech() == "リプレイを保存しました")


def test_pause_reminder_speech() -> None:
    got = pause_reminder_speech(300.0)
    check("止まったままだと伝える", "一時停止のまま" in got, got)
    check("経過を伝える", "5分0秒" in got, got)
    # 再開の手段を言わないと、キーを思い出せないまま止まり続ける
    check("再開の手段を言う", "Ctrl+P" in got, got)


def test_disk_warning_speech() -> None:
    from core.recording import DISK_CRITICAL, DISK_WARN  # noqa: PLC0415

    warn = disk_warning_speech(DISK_WARN, 9000.0)
    check("警告は残量を言う", "ギガバイト" in warn, warn)
    check("警告は少ないと言う", "少なくなっています" in warn, warn)
    crit = disk_warning_speech(DISK_CRITICAL, 1000.0)
    check("危険はわずかと言う", "わずか" in crit, crit)
    # 危険域では、何をすればよいかまで言わないと打つ手が分からない
    check("危険は対処を言う", "録画を止める" in crit, crit)


def test_chapter_speech() -> None:
    got = chapter_added_speech(3, "01:12:33")
    check("番号を言う", "チャプター3" in got, got)
    check("位置を言う", "1時間12分33秒" in got, got)


def test_chapter_unsupported_speech() -> None:
    got = chapter_unsupported_speech("mp4")
    check("必要なフォーマットを言う", "ハイブリッドMP4" in got, got)
    check("MOVも使えることを言う", "ハイブリッドMOV" in got, got)
    check("今の値を言う", "今は MP4 です" in got, got)
    check("変え方を言う", "録画フォーマット" in got, got)
    bare = chapter_unsupported_speech("")
    check("今の値が不明でも案内する", "ハイブリッドMP4" in bare, bare)


def test_chapter_unsupported_needs_restart() -> None:
    """★設定は対応フォーマットなのに拒否される状態を正しく案内すること。

    録画フォーマットを変えても、起動中のOBSは出力を作り直さない（実測）。
    このとき「フォーマットを変えてください」と言うと、既に変えた利用者は
    打つ手が分からなくなる。再起動が要ることまで言わないと解決しない。
    """
    got = chapter_unsupported_speech("hybrid_mp4", "ffmpeg_muxer")
    check("反映されていないと言う", "反映されていません" in got, got)
    check("再起動を促す", "再起動" in got, got)
    # 既に変えてあるのに「変えてください」と言わない
    check("フォーマットを変えろとは言わない",
          "変えてください" not in got, got)
    # 設定も実態も対応しているのに失敗した場合は、決めつけない
    both_ok = chapter_unsupported_speech("hybrid_mp4", "mp4_output")
    check("原因不明なら決めつけない", "再起動" not in both_ok, both_ok)
    check("確かめられることを言う", "録画が始まっている" in both_ok, both_ok)


def test_chapter_status_speech() -> None:
    from core.speech_format import chapter_status_speech  # noqa: PLC0415

    check("非対応フォーマット",
          chapter_status_speech("mp4", "ffmpeg_muxer")
          == "このフォーマットではチャプターは使えません")
    # ★設定は対応でも実態が追いついていなければ「使えます」と言わない
    check("設定だけ対応なら再起動を言う",
          chapter_status_speech("hybrid_mp4", "ffmpeg_muxer")
          == "チャプターはOBSを再起動すると使えます")
    check("実態も対応なら使えると言う",
          chapter_status_speech("hybrid_mp4", "mp4_output")
          == "チャプターが使えます")
    # 実態が分からないときは設定で答える（何も言わないよりよい）
    check("実態不明なら設定で答える",
          chapter_status_speech("hybrid_mp4", "") == "チャプターが使えます")


def test_rec_format_jp() -> None:
    check("ハイブリッドMP4", rec_format_jp("hybrid_mp4") == "ハイブリッドMP4")
    check("プレーンMP4", rec_format_jp("mp4") == "MP4")
    check("未知はそのまま", rec_format_jp("なにか") == "なにか")
    check("空は不明", rec_format_jp("") == "不明")


def test_record_settings_summary() -> None:
    got = record_settings_summary({
        "directory": "F:/Videos", "format": "mp4", "quality": "Small",
        "encoder": "x264", "tracks": "1", "disk_free_mb": 500000.0,
    })
    check("保存先", "F:、Videos" in got, got)
    check("フォーマット", "MP4" in got, got)
    check("品質を日本語に", "ファイル小" in got, got)
    check("エンコーダを日本語に", "CPU" in got, got)
    # ★値の中に読点を入れないこと。読み上げは「ラベル 値」を読点で連ねる
    #   形なので、値の読点が項目の区切りに聞こえて件数を誤解させる
    check("項目数が読点の数と合う",
          got.count("、") == len([p for p in got.split("、")]) - 1, got)
    check("エンコーダの値に読点が無い",
          "x264 CPUで処理" in got, got)
    check("品質の値に読点が無い", "高品質 ファイル小" in got, got)
    check("空き容量", "ギガバイト" in got, got)
    # ★この設定で見落としやすいのはチャプターの可否なので必ず言う
    check("プレーンMP4はチャプター不可と言う",
          "チャプターは使えません" in got, got)
    hybrid = record_settings_summary({"format": "hybrid_mp4"})
    check("ハイブリッドMP4はチャプター可と言う",
          "チャプターが使えます" in hybrid, hybrid)
    check("空なら取得失敗を伝える",
          record_settings_summary({}) == "録画設定を取得できませんでした")
    # 取れなかった項目は黙って落とす（「不明」を並べても判断できない）
    partial = record_settings_summary({"directory": "F:/Videos"})
    check("取れた項目だけ読む", "フォーマット" not in partial, partial)


def test_license_notice_speech() -> None:
    """GPL-3.0 の「適切な法的告知」に要る4つを言うこと。"""
    got = license_notice_speech()
    check("著作権の表示がある", "著作権" in got, got)
    check("GPL第3版と言う", "GPL 第3版" in got, got)
    check("無保証と言う", "無保証" in got, got)
    check("再配布できると言う", "再配布" in got, got)
    check("ライセンスの全文の在りかを言う", "LICENSE.txt" in got, got)
    # on_about は「。」で文を連ねるので、句点が二重にならないように
    check("末尾に句点が無い", not got.endswith("。"), got)


def test_ai_notice_speech() -> None:
    """AI を使って作ったことを言うこと。"""
    got = ai_notice_speech()
    check("AI を使って作ったと言う", "AI" in got and "作りました" in got, got)
    check("作者が確かめていると言う", "作者" in got, got)
    check("AI の告知の末尾に句点が無い", not got.endswith("。"), got)


def run() -> tuple[int, int]:
    for fn in (
        test_fmt_db,
        test_fmt_volume_db,
        test_fmt_volume_db_differs_from_level,
        test_fmt_volume_db_fraction,
        test_volume_speech,
        test_filter_kind_jp,
        test_filter_list_label,
        test_filter_toggle_speech,
        test_scene_item_labels,
        test_scene_item_toggle_speech,
        test_stats_summary_healthy,
        test_stats_summary_dropped_frames,
        test_stats_summary_disk_units,
        test_stats_summary_empty,
        test_onoff_speech,
        test_timecode,
        test_state_summary,
        test_level_summary,
        test_level_summary_order,
        test_level_summary_skip_muted,
        test_level_setting_speech,
        test_order_reset_speech,
        test_item_layer_speech,
        test_input_list_label,
        test_input_list_label_with_volume,
        test_mute_monitor_caveat,
        test_mute_monitor_caveat_media_not_playing,
        test_state_summary_paused,
        test_fmt_seconds,
        test_path_speech,
        test_record_stopped_speech,
        test_replay_saved_speech,
        test_pause_reminder_speech,
        test_disk_warning_speech,
        test_chapter_speech,
        test_chapter_unsupported_speech,
        test_chapter_unsupported_needs_restart,
        test_chapter_status_speech,
        test_rec_format_jp,
        test_record_settings_summary,
        test_license_notice_speech,
        test_ai_notice_speech,
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
    print(f"speech_format: {p} passed, {f} failed")
