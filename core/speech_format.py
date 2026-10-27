# -*- coding: utf-8 -*-
"""読み上げ文の整形（純関数・OS非依存）。

数値やタイムコードは、PC-Talker で誤読しにくい日本語表現に変換する。
（例: "-18dB" のような記号混じりを避け、「マイナス18デシベル」と読む）
"""
from __future__ import annotations

from . import ordering
from .i18n import tr
from .state import Snapshot
from .volume import VOLUME_MIN_DB

SILENCE_SPEECH_DB = -90.0  # これ以下は「無音」と読む


def _db_number(value: float) -> str:
    """dB値の符号と数値の部分を言葉にする（単位まで含む）。"""
    if value < 0:
        return tr(f"マイナス{abs(value)}デシベル",
                  f"minus {abs(value)} {_decibels(abs(value))}")
    if value == 0:
        return tr("0デシベル", "0 decibels")
    return tr(f"プラス{value}デシベル", f"plus {value} {_decibels(value)}")


def _decibels(value) -> str:
    """英語の単位（1 のときだけ単数）。"""
    return "decibel" if value == 1 else "decibels"


def _count(n: int, ja_unit: str, en_unit: str) -> str:
    """「3分」「3 minutes」のような数と単位（英語は 1 のときだけ単数）。"""
    if n == 1:
        return tr(f"{n}{ja_unit}", f"{n} {en_unit}")
    return tr(f"{n}{ja_unit}", f"{n} {en_unit}s")


def _hms(h: int, m: int, s: int) -> str:
    """時間・分・秒を「1時間2分3秒」「1 hour 2 minutes 3 seconds」にする。"""
    parts: list[str] = []
    if h:
        parts.append(_count(h, "時間", "hour"))
    if m or h:
        parts.append(_count(m, "分", "minute"))
    parts.append(_count(s, "秒", "second"))
    return tr("", " ").join(parts)


def fmt_db(db: float) -> str:
    """レベル(メーター読み)のdB値を読み上げ用の日本語にする。"""
    if db <= SILENCE_SPEECH_DB:
        return tr("無音", "silent")
    return _db_number(round(db))


def fmt_volume_db(db: float) -> str:
    """音量(フェーダー値)のdB値を読み上げ用の日本語にする。

    レベル(fmt_db)と違い、音量は「今いくつに設定されているか」を知るための
    値なので「無音」で潰さず数値を読む。ただし下限まで下げたときだけは
    数値より「最小」のほうが分かりやすいのでそう読む。

    刻みが既定(1dB)なら値は整数に乗るので整数で読む。設定で刻みを細かく
    したときだけ小数第1位まで読む（整数に丸めると、押しても読み上げが
    変わらず効いていないように聞こえるため）。
    """
    if db <= VOLUME_MIN_DB:
        return tr("最小", "minimum")
    value = round(db, 1)
    if value == int(value):
        return _db_number(int(value))
    return _db_number(value)


def timecode_to_speech(tc: str) -> str:
    """"HH:MM:SS.mmm" または "HH:MM:SS" を「H時間M分S秒」にする。"""
    try:
        main = tc.split(".")[0]
        h, m, s = (int(x) for x in main.split(":"))
    except (ValueError, AttributeError):
        return tc
    return _hms(h, m, s)


def state_summary(snap: Snapshot) -> str:
    """状態の要約文。"""
    if not snap.connected:
        return tr("OBSに接続していません", "Not connected to OBS")
    parts: list[str] = []
    if snap.streaming:
        parts.append(tr(f"配信中 {timecode_to_speech(snap.stream_timecode)}", f"Streaming {timecode_to_speech(snap.stream_timecode)}"))
    else:
        parts.append(tr("配信停止中", "Not streaming"))
    if snap.recording:
        # ★一時停止は「録画中のまま止まっている」状態。画面を見れば分かるが
        #   読み上げには出ないため、忘れるとその間が録れていない事故になる。
        #   ここで必ず言い分ける（F5で確かめられる唯一の場所）。
        label = tr("録画一時停止中", "Recording paused") if snap.record_paused else tr("録画中", "Recording")
        parts.append(f"{label} {timecode_to_speech(snap.record_timecode)}")
    else:
        parts.append(tr("録画停止中", "Not recording"))
    if snap.current_scene:
        parts.append(tr(f"現在のシーン {snap.current_scene}", f"Current scene {snap.current_scene}"))
    return tr("、", ", ").join(parts)


def level_summary(
    peaks: dict[str, float],
    muted: dict[str, bool] | None = None,
    order=None,
    skip_muted: bool = False,
) -> str:
    """各入力のレベル要約文。

    order で読み上げる順番を、skip_muted でミュート中を飛ばすかを決める
    （どちらも設定 level_read から来る）。
    """
    if not peaks:
        return tr("レベル情報がまだありません", "No level information yet")
    muted = muted or {}
    parts: list[str] = []
    skipped = 0
    # 設定に載っていない入力は名前順で後ろへ続く（落とさない）。
    # 並び順の考え方は core/ordering.py にまとめてある
    for name in ordering.apply_order(peaks.keys(), order, sort_rest=True):
        if muted.get(name):
            if skip_muted:
                skipped += 1
                continue
            parts.append(tr(f"{name} ミュート中", f"{name} muted"))
        else:
            parts.append(f"{name} {fmt_db(peaks[name])}")
    if not parts:
        # 全部飛ばした。無言で終わると「キーが効いていない」のと区別が
        # 付かないので、飛ばしたことを必ず言う
        return tr(f"読み上げるレベルがありません。{skipped}件すべてミュート中です", f"No levels to read. All {skipped} are muted")
    return tr("、", ", ").join(parts)


def order_saved_speech(what: str, order, sort_rest: bool, live) -> str:
    """並び順を保存したときの読み上げ。

    並びを全部読み返すと長いので、件数と先頭だけ言う（順番は
    並べ替えの画面で1件ずつ確かめられる）。
    what は「レベル読み上げの順番」のような対象名、sort_rest は
    設定を空にしたときに戻る並び（True＝名前順、False＝OBSと同じ順）。

    ★live には「今あるものだけ」を渡す（省略できない）。設定には、
    今は無い名前も位置を保つために残る（シーンコレクションを切り替えて
    戻ったときのため）が、それを件数や先頭として読むと、実際に最初に
    読まれるものと食い違って聞こえる。保存するのは order、読み上げる
    のは live。★既定にしてはいけない。渡し忘れが「今は無い名前を
    先頭として読む」という気づきにくい壊れ方に戻るので、必ず書かせる。
    """
    if not order:
        return tr(f"{what}を{ordering.default_label(sort_rest)}に戻しました", f"Reset {what} to {ordering.default_label(sort_rest)}")
    shown = list(live)
    if not shown:
        # 保存はしたが、今あるものが1つも無い（全部が古い名前）
        return tr(f"{what}を保存しました。今あるものはありません", f"Saved {what}. None of them exist now")
    return tr(f"{what}を保存しました。{len(shown)}件、最初は {shown[0]}", f"Saved {what}. {_count(len(shown), '件', 'item')}, first is {shown[0]}")


def order_unchanged_speech(what: str) -> str:
    """並べ替えの画面を開いたが、順番を変えずに閉じたときの読み上げ。

    ★変えていないのに「戻しました」と言わない。確かめるために開いた
    だけなのに、設定を書き換えたように聞こえる（レビューで判明）。
    """
    return tr(f"{what}は変えませんでした", f"{what} was not changed")


def config_save_failed_speech(what: str) -> str:
    """設定を保存できなかったときの読み上げ。

    ★「保存しました」と嘘をつかない。設定ファイルが読めなかったときは
    上書きを避けて何もしないので、そのまま成功を読み上げると、
    再起動して初めて消えていることに気づく（耳では確かめようが無い）。
    """
    return (tr(f"{what}を保存できませんでした。"
               "設定ファイルが読み込めていないため、上書きしていません",
       f"Could not save {what}. The settings file could not be read, so it was not overwritten"))


def order_reset_speech(sort_rest: bool, dropped: int = 0) -> str:
    """並べ替え画面で「戻す」を押したときの読み上げ。

    ★ボタンの文言（終止形）に「ました」を足してはいけない。
    「OBSと同じ順に戻すました」という壊れた日本語になる（レビューで
    見つかった。読み上げが唯一の出力なので、そのまま耳に入る）。
    """
    label = ordering.default_label(sort_rest)
    head = tr(f"{label}に並べ直しました", f"Re-sorted into {label}") if sort_rest else tr(f"{label}に戻しました", f"Reset to {label}")
    if dropped:
        return tr(f"{head}。今は無いもの{dropped}件は一覧から外しました", f"{head}. Removed {dropped} items that no longer exist from the list")
    return head


def item_moved_speech(name: str, pos: int, total: int, forward: bool) -> str:
    """重なり順を変えたときの読み上げ。

    ★一覧の並びを自分で決めている場合、重なり順を変えても一覧の行は
      動かない。だから「今どこにいるか」を必ず言葉で言う。
    pos は1始まりの「前から数えた位置」。
    """
    where = tr("前に出しました", "Moved forward") if forward else tr("後ろに送りました", "Moved backward")
    return tr(f"{name} を{where}。{total}件中、前から{pos}番目", f"{name}: {where}. Position {pos} from the front, of {total}")


def item_move_edge_speech(name: str, forward: bool) -> str:
    """これ以上動かせないときの読み上げ。

    ★同じ意味の文を2つ持たない。映像切り替えの
    video_already_front_speech もここへ寄せてある（別々に書いていた
    ので「既に」と「すでに」で表記が割れていた）。
    """
    edge = tr("前", "front") if forward else tr("後ろ", "back")
    return tr(f"{name} はすでにいちばん{edge}です", f"{name} is already at the very {edge}")


def skip_muted_speech(skip: bool) -> str:
    """ミュート中を読み飛ばす設定を切り替えたときの読み上げ。"""
    if skip:
        return tr("ミュート中のソースはレベル読み上げに出しません", "Muted sources are left out of the level readout")
    return tr("ミュート中のソースもレベル読み上げに出します", "Muted sources are included in the level readout")


# フィルター種別の内部名 → 読み上げ用の日本語。無いものは内部名のまま読む。
_FILTER_KIND_JP = {
    "noise_suppress_filter": tr("ノイズ抑制", "Noise Suppression"),
    "noise_suppress_filter_v2": tr("ノイズ抑制", "Noise Suppression"),
    "noise_gate_filter": tr("ノイズゲート", "Noise Gate"),
    "compressor_filter": tr("コンプレッサー", "Compressor"),
    "upward_compressor_filter": tr("アップワードコンプレッサー", "Upward Compressor"),
    "limiter_filter": tr("リミッター", "Limiter"),
    "expander_filter": tr("エキスパンダー", "Expander"),
    "gain_filter": tr("ゲイン", "Gain"),
    "basic_eq_filter": tr("イコライザー", "Equalizer"),
    "invert_polarity_filter": tr("位相反転", "Invert Polarity"),
    "vst_filter": tr("ブイエスティープラグイン", "VST Plugin"),
    "async_delay_filter": tr("音声遅延", "Audio Delay"),
    "chroma_key_filter": tr("クロマキー", "Chroma Key"),
    "chroma_key_filter_v2": tr("クロマキー", "Chroma Key"),
    "color_key_filter": tr("カラーキー", "Color Key"),
    "color_key_filter_v2": tr("カラーキー", "Color Key"),
    "luma_key_filter": tr("ルマキー", "Luma Key"),
    "luma_key_filter_v2": tr("ルマキー", "Luma Key"),
    "color_filter": tr("色補正", "Color Correction"),
    "color_filter_v2": tr("色補正", "Color Correction"),
    "crop_filter": tr("クロップ", "Crop"),
    "scale_filter": tr("スケール", "Scale"),
    "sharpness_filter": tr("シャープ", "Sharpen"),
    "sharpness_filter_v2": tr("シャープ", "Sharpen"),
    "mask_filter": tr("画像マスク", "Image Mask"),
    "mask_filter_v2": tr("画像マスク", "Image Mask"),
    "scroll_filter": tr("スクロール", "Scroll"),
    "gpu_delay": tr("映像遅延", "Video Delay"),
    "hdr_tonemap_filter": tr("HDRトーンマップ", "HDR Tone Mapping"),
    "clut_filter": tr("ルックアップテーブル", "Lookup Table"),
}


def filter_kind_jp(kind: str) -> str:
    """フィルター種別の内部名を読み上げ用の日本語にする。無ければそのまま。"""
    return _FILTER_KIND_JP.get(kind, kind)


def filter_list_label(name: str, enabled: bool) -> str:
    """フィルター一覧の1行表示。

    フィルター名はユーザーが付けた名前（既定では種別の日本語名）なので、
    名前をそのまま出す。状態はオン/オフを明示する。
    """
    return tr(f"{name} オン", f"{name} on") if enabled else tr(f"{name} オフ", f"{name} off")


def filter_toggle_speech(name: str, enabled: bool) -> str:
    """フィルターを切り替えたときの読み上げ文。"""
    return tr(f"{name} を有効にしました", f"Enabled {name}") if enabled else tr(f"{name} を無効にしました", f"Disabled {name}")


def scene_item_list_label(name: str, enabled: bool) -> str:
    """シーン内ソース一覧の1行表示。

    可視性なので「表示中／非表示」と読む（ミュートの「オン／ミュート中」と
    混同しないよう別の語にする）。
    """
    return tr(f"{name} 表示中", f"{name} shown") if enabled else tr(f"{name} 非表示", f"{name} hidden")


def scene_item_toggle_speech(name: str, enabled: bool) -> str:
    """シーン内ソースの表示を切り替えたときの読み上げ文。"""
    return tr(f"{name} を表示しました", f"Showed {name}") if enabled else tr(f"{name} を非表示にしました", f"Hid {name}")


def _fmt_disk(mb: float) -> str:
    """空きディスク容量(MB)を読みやすい単位にする。"""
    if mb >= 1024 * 1024:
        return tr(f"{mb / (1024 * 1024):.1f}テラバイト", f"{mb / (1024 * 1024):.1f} terabytes")
    if mb >= 1024:
        return tr(f"{mb / 1024:.1f}ギガバイト", f"{mb / 1024:.1f} gigabytes")
    return tr(f"{int(round(mb))}メガバイト", f"{int(round(mb))} megabytes")


def stats_summary(stats: dict) -> str:
    """OBSの統計を読み上げ用の文にする。

    stats は get_stats の主要値を入れた辞書:
      cpu（%）, disk_free_mb, fps, render_total, render_skipped,
      output_total, output_skipped
    スキップ（コマ落ち）は「あるときだけ」件数と割合を読む。健全なら
    「コマ落ちなし」で済ませ、うるさくしない。
    """
    parts: list[str] = []
    cpu = stats.get("cpu")
    if isinstance(cpu, (int, float)):
        parts.append(tr(f"CPU {cpu:.0f}パーセント", f"CPU {cpu:.0f} percent"))
    fps = stats.get("fps")
    if isinstance(fps, (int, float)):
        parts.append(tr(f"エフピーエス {fps:.0f}", f"FPS {fps:.0f}"))

    def _skip_part(label, total, skipped):
        if not isinstance(total, int) or not isinstance(skipped, int):
            return None
        if total <= 0:
            return None
        if skipped <= 0:
            return tr(f"{label}のコマ落ちなし", f"No dropped frames in {label}")
        pct = skipped / total * 100.0
        return tr(f"{label}のコマ落ち {skipped}フレーム、{pct:.1f}パーセント", f"Dropped frames in {label}: {skipped} frames, {pct:.1f} percent")

    r = _skip_part(tr("描画", "rendering"), stats.get("render_total"),
                   stats.get("render_skipped"))
    if r:
        parts.append(r)
    o = _skip_part(tr("配信録画", "output"), stats.get("output_total"),
                   stats.get("output_skipped"))
    if o:
        parts.append(o)

    disk = stats.get("disk_free_mb")
    if isinstance(disk, (int, float)):
        parts.append(tr(f"空き容量 {_fmt_disk(disk)}", f"Free space {_fmt_disk(disk)}"))
    return tr("、", ", ").join(parts) if parts else tr("統計を取得できませんでした", "Could not get statistics")


def onoff_speech(label: str, active: bool) -> str:
    """オン・オフ状態の変化の読み上げ（仮想カメラなど）。"""
    return tr(f"{label}を開始しました", f"Started {label}") if active else tr(f"{label}を停止しました", f"Stopped {label}")


def input_list_label(
    name: str, muted: bool, volume_db: float | None = None
) -> str:
    """音声入力一覧の1行表示。

    一覧を上下で辿るとスクリーンリーダーがこの行を読む。ミュート状態だけ
    でなく音量も入れておくと、辿るだけで各入力の状態が分かる。
    volume_db=None のときは音量を出さない（まだ取得できていないとき）。
    """
    state = tr("ミュート中", "muted") if muted else tr("オン", "on")
    if volume_db is None:
        return f"{name} {state}"
    return f"{name} {state} {fmt_volume_db(volume_db)}"


def volume_speech(name: str, volume_db: float) -> str:
    """音量を変えた/選んだときの読み上げ文（例「マイク プラス6デシベル」）。"""
    return f"{name} {fmt_volume_db(volume_db)}"


# ------------------------------------------------------------
# ソース設定（プロパティ）まわり
# ------------------------------------------------------------
# 読み上げに向かない記号。ウィンドウタイトルには絵文字・全角括弧・
# パス区切りなどが普通に入っており、そのまま読ませると記号名を延々と
# 読み上げてしまう。
_NOISY_CHARS = "\\/|<>*?\"[]{}【】《》＜＞«»"
MAX_TITLE_CHARS = 24


def speech_safe(text: str) -> str:
    """読み上げバックエンドで化ける文字を空白に置き換える。

    PC-Talker 側は cp932 に変換して渡すため、絵文字や ™ ® などは
    「？」と読まれる。落とすと単語がつながるので空白に置換する。
    """
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        try:
            ch.encode("cp932")
        except (UnicodeEncodeError, LookupError):
            out.append(" ")
        else:
            out.append(ch)
    # 置換で増えた空白をまとめる
    return " ".join("".join(out).split())


def _tame_title(title: str) -> str:
    """ウィンドウタイトルを読み上げやすく短くする。"""
    # OBSはタイトル内の ':' を "#3A" にエスケープして持つ。そのまま読むと
    # 「シャープ3エー」と読まれるので落とす。
    title = title.replace("#3A", " ").replace("#22", " ")
    cleaned = "".join(" " if ch in _NOISY_CHARS else ch for ch in title)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > MAX_TITLE_CHARS:
        cleaned = cleaned[:MAX_TITLE_CHARS] + tr(" ほか", " and more")
    return cleaned


def parse_window_item(item_name: str) -> tuple[str, str]:
    """選択肢の表示名を (タイトル, 実行ファイル名) に分ける。

    OBSは "[Diablo IV.exe]: ディアブロ IV" の形で返す。
    実行ファイル名は拡張子を落とす（「ドットイーエックスイー」と
    読ませないため）。形式が違えば全体をタイトル扱いにする。
    """
    if not item_name:
        return ("", "")
    text = item_name.strip()
    if text.startswith("[") and "]" in text:
        close = text.index("]")
        exe = text[1:close].strip()
        title = text[close + 1:].lstrip(": ").strip()
        if exe.lower().endswith(".exe"):
            exe = exe[:-4]
        return (title, exe)
    return (text, "")


def window_item_label(item_name: str, enabled: bool = True) -> str:
    """ウィンドウ選択肢1件の読み上げ行。

    itemEnabled=false は「今その対象が一覧に無い」＝起動していないこと
    を意味する（OBSが設定済みの値だけをプレースホルダとして足すため）。
    """
    title, exe = parse_window_item(item_name)
    title = _tame_title(title)
    if title and exe:
        text = tr(f"{title}、{exe}", f"{title}, {exe}")
    else:
        text = title or exe or tr("名前なし", "no name")
    if not enabled:
        text += tr("、今は起動していません", ", not running now")
    return text


def window_value_label(window_value: str) -> str:
    """window の「設定値」を読み上げ用にする。

    選択肢一覧を取りに行かなくても現在値を読めるようにするためのもの。
    値の形は "タイトル:クラス:実行ファイル"。クラス名は利用者にとって
    意味が無いので読まない。
    """
    if not window_value:
        return tr("未設定", "not set")
    parts = window_value.rsplit(":", 2)
    if len(parts) < 3:
        return _tame_title(window_value) or tr("未設定", "not set")
    title, _cls, exe = parts
    if exe.lower().endswith(".exe"):
        exe = exe[:-4]
    title = _tame_title(title)
    exe = _tame_title(exe)
    if title and exe:
        return tr(f"{title}、{exe}", f"{title}, {exe}")
    return title or exe or tr("未設定", "not set")


def device_item_label(item_name: str, enabled: bool = True) -> str:
    """音声デバイス選択肢1件の読み上げ行。

    "Line (Steinberg UR44C)" のような括弧を読点に開く。
    """
    sep = tr("、", ",")
    text = (item_name or "").replace("(", sep).replace(")", "")
    text = " ".join(text.split())
    # 「Line (Steinberg…」→「Line 、Steinberg…」のように読点の前後へ
    # 空白が残るので詰める（読点の直前で息継ぎが二重になるのを防ぐ）
    # 英語は「Line, Steinberg…」の形にそろえる
    text = text.replace(" " + sep, sep).replace(sep + " ", sep).strip(sep + " ")
    if sep == ",":
        text = text.replace(",", ", ")
    if not text:
        text = tr("名前なし", "no name")
    if not enabled:
        text += tr("、今は使えません", ", not available now")
    return text


def prop_row_label(label: str, value_text: str) -> str:
    """設定項目一覧の1行（「対象ウィンドウ、ディアブロ IV」）。"""
    return tr(f"{label}、{value_text}", f"{label}, {value_text}")


def prop_changed_speech(source: str, label: str, value_text: str) -> str:
    """設定を1つ変えたときの読み上げ文。"""
    return tr(f"{source} の {label} を {value_text} にしました", f"Set {label} of {source} to {value_text}")


def prop_multi_changed_speech(source: str, pairs) -> str:
    """設定を複数変えたときの読み上げ文。

    pairs は (ラベル, 値の文字列) の並び。
    """
    items = list(pairs or [])
    if not items:
        return tr("変更はありません", "No changes")
    if len(items) == 1:
        return prop_changed_speech(source, items[0][0], items[0][1])
    body = tr("、", ", ").join(f"{label} {value}" for label, value in items)
    return tr(f"{source} を変えました。{body}", f"Changed {source}. {body}")


def prop_unchanged_speech(source: str, label: str) -> str:
    """投げたのに値が変わらなかったときの警告文。"""
    return tr(f"{source} の {label} は変わりませんでした。OBSが受け付けていません", f"{label} of {source} did not change. OBS did not accept it")


def game_switch_speech(
    title: str,
    video_source: str,
    audio_ok: list | None = None,
    audio_ng: list | None = None,
    running: bool = True,
    key_name: str = "F3",
) -> str:
    """ゲーム切り替えの結果を1文で読む。"""
    ok = list(audio_ok or [])
    ng = list(audio_ng or [])
    parts = [tr(f"{title} に切り替えました", f"Switched to {title}")]
    done = [video_source] + ok
    parts.append(tr("、".join(done) + " を設定しました",
                    "Set " + ", ".join(done)))
    if ng:
        parts.append(tr(
            "、".join(ng) + " は対象が見つかりません。"
            f"ゲームを起動してから、もう一度 {key_name} で切り替えてください",
            "No target found for " + ", ".join(ng) + ". "
            f"Start the game, then press {key_name} again to switch"))
    elif not running:
        parts.append(tr("今は起動していないので、ゲームを起動すると映ります", "It is not running now, so it will appear once you start the game"))
    return tr("。", ". ").join(parts)


def fmt_media_time(ms) -> str:
    """再生位置・長さ(ミリ秒)を日本語にする。"""
    if not isinstance(ms, (int, float)) or ms < 0:
        return tr("不明", "unknown")
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return _hms(h, m, s)


_MEDIA_STATE_JP = {
    "OBS_MEDIA_STATE_PLAYING": tr("再生中", "playing"),
    "OBS_MEDIA_STATE_PAUSED": tr("一時停止", "paused"),
    "OBS_MEDIA_STATE_STOPPED": tr("停止", "stopped"),
    "OBS_MEDIA_STATE_ENDED": tr("再生が終わりました", "finished playing"),
    "OBS_MEDIA_STATE_OPENING": tr("読み込み中", "loading"),
    "OBS_MEDIA_STATE_BUFFERING": tr("読み込み中", "loading"),
    "OBS_MEDIA_STATE_ERROR": tr("エラー", "error"),
    "OBS_MEDIA_STATE_NONE": tr("未再生", "not played"),
}


def media_state_jp(state: str) -> str:
    """メディアの再生状態を日本語にする。"""
    return _MEDIA_STATE_JP.get(state, tr("状態不明", "unknown state"))


def media_status_speech(name: str, state: str, cursor_ms, duration_ms) -> str:
    """メディアの現在状態の読み上げ文。

    再生位置・長さは再生中/一時停止のときしか返らないので、
    取れないときは状態だけを読む。
    """
    label = media_state_jp(state)
    if isinstance(cursor_ms, (int, float)) and isinstance(
        duration_ms, (int, float)
    ):
        return (tr(f"{name} {label} {fmt_media_time(cursor_ms)}、"
                   f"全体 {fmt_media_time(duration_ms)}",
           f"{name} {label} {fmt_media_time(cursor_ms)}, of {fmt_media_time(duration_ms)}"))
    return f"{name} {label}"


def media_action_speech(name: str, action: str) -> str:
    """メディア操作イベントの読み上げ文。

    再生(PLAY)だけは PlaybackStarted 側で読むので、ここでは空文字を返す
    （呼び出し側は空なら読み上げない）。二重読みを避けるため。
    """
    if action.endswith("_PAUSE"):
        return tr(f"{name} を一時停止しました", f"Paused {name}")
    if action.endswith("_STOP"):
        return tr(f"{name} を止めました", f"Stopped {name}")
    if action.endswith("_RESTART"):
        return tr(f"{name} を最初から再生します", f"Playing {name} from the beginning")
    return ""


def media_started_speech(name: str) -> str:
    """再生が始まったときの読み上げ文。"""
    return tr(f"{name} を再生します", f"Playing {name}")


def media_ended_speech(name: str) -> str:
    """再生が終わったときの読み上げ文。"""
    return tr(f"{name} の再生が終わりました", f"{name} finished playing")


def bgm_file_speech(name: str, path: str) -> str:
    """BGMのファイルを設定したときの読み上げ文。

    フルパスは記号だらけで読み上げに向かないのでファイル名の本体だけ読む
    （リプレイ保存パスを読まないのと同じ方針）。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path) or tr("名前不明", "unknown name")
    return tr(f"{name} の音楽ファイルを {stem} にしました", f"Set the music file of {name} to {stem}")


def video_item_label(name: str, index: int, top_index: int, blank: bool) -> str:
    """映像切り替えの候補1件の読み上げ行。

    ★「いま映っています」とは言わない。いちばん手前でも、ゲームが起動して
    いなければ絵は出ておらず、後ろのソースが見えている。断定すると嘘に
    なるので、位置（前面／後ろ）と「今は絵が出ていない」だけを伝える。
    """
    where = tr("前面", "front") if index >= top_index else tr("後ろ", "behind")
    text = tr(f"{name}、{where}", f"{name}, {where}")
    if blank:
        text += tr("、今は映っていません", ", not showing anything now")
    return text


def video_front_speech(plan) -> str:
    """映像ソースを前に出したときの読み上げ文。"""
    parts = [tr(f"{plan.name} を前に出しました", f"Brought {plan.name} to the front")]
    if plan.behind:
        parts.append(tr("、".join(plan.behind) + " が後ろになりました",
                        ", ".join(plan.behind) + " moved behind it"))
    if plan.blank:
        parts.append(
            tr(f"ただし {plan.name} は今は映っていません。"
               "ゲームや機器が動いていないと、後ろのソースが見えます",
               f"However, {plan.name} is not showing anything now. If the game or device is not running, the sources behind it are visible"))
    return tr("。", ". ").join(parts)


def video_already_front_speech(name: str) -> str:
    """すでに最前面だったときの読み上げ文（重なり順の文言に合わせる）。"""
    return item_move_edge_speech(name, True)


def video_unchanged_speech(name: str) -> str:
    """投げたのに順番が変わらなかったときの警告文。"""
    return tr(f"{name} を前に出せませんでした。OBSが受け付けていません", f"Could not bring {name} to the front. OBS did not accept it")


def video_none_speech() -> str:
    """切り替えられる映像ソースが無いときの案内文。"""
    return (tr("切り替えられる映像ソースがありません。"
               "ゲームキャプチャや映像キャプチャデバイスを作ってから実行してください",
       "There are no video sources to switch. Create a game capture or video capture device source first"))


def mute_monitor_caveat(
    muted: bool, mon_type: str, media_state: str = ""
) -> str:
    """ミュートとモニタリングが食い違うときの補足。食い違わなければ空文字。

    ★OBSのミュートは「配信・録画に乗せない」だけで、自分の耳へ返す
    モニタリングは止めない。そのため「BGMをミュートしたのに鳴り続ける」
    ことが実際に起きる（実機で発生）。目でミキサーを確認できない以上、
    読み上げがこの食い違いを伝えないと原因に辿り着けない。

    逆に「自分だけ聞く」設定だと、ミュートを解除しても配信には乗らない。
    こちらは「自分に聞こえている＝配信にも乗っている」と誤解したまま
    配信してしまうので、より危ない。どちらも読み上げと実際がずれる
    ときだけ一言添え、ずれていなければ黙る（普段をうるさくしない）。

    media_state はメディアソースのときだけ渡す（空文字＝マイクなどの
    生の音声で、鳴っているかを外から判定できないもの）。
    ★止まっているメディアに「自分には聞こえ続けます」と言うと嘘になる。
    一時停止・停止中のBGMをミュートしたときに再生中と同じ案内が出ると
    混乱するため、メディアは再生中のときだけ添える。
    """
    from .props import (  # 循環参照回避
        MONITOR_AND_OUTPUT, MONITOR_ONLY, is_media_playing)

    if muted and mon_type in (MONITOR_ONLY, MONITOR_AND_OUTPUT):
        if media_state:
            if not is_media_playing(media_state):
                return ""  # 鳴っていないので「聞こえ続ける」ことはない
            return (tr("ただしモニタリングがオンなので、自分にはこのまま聞こえます"
                       "。止めるには一時停止してください",
               "However, monitoring is on, so you will keep hearing it. Pause it to stop the sound"))
        return tr("ただしモニタリングがオンなので、自分にはこのまま聞こえます", "However, monitoring is on, so you will keep hearing it")
    if not muted and mon_type == MONITOR_ONLY:
        # こちらは「今鳴っているか」ではなく音の行き先の話なので、
        # 止まっていても伝える（次に鳴らしたとき配信に乗らないため）
        return tr("ただしモニタリングが自分だけ聞く設定なので、配信には乗りません", "However, monitoring is set to monitor only, so it is not sent to the stream")
    return ""


def monitor_changed_speech(name: str, mon_type: str) -> str:
    """音声モニタリングを変えたときの読み上げ文。"""
    from .props import monitor_label  # 循環参照を避けるため関数内 import

    return tr(f"{name} の音声モニタリングを {monitor_label(mon_type)} にしました", f"Set audio monitoring of {name} to {monitor_label(mon_type)}")


def bgm_wrong_kind_speech(name: str) -> str:
    """既存ソースがメディアソースでないときの案内文。"""
    return (tr(f"{name} はアプリの音を取り込む設定です。"
               "音楽ファイルを再生するには、新しくメディアソースを作る必要があります",
       f"{name} is set to capture application audio. To play a music file, you need to create a new media source"))


# ------------------------------------------------------------
# 録画まわり
# ------------------------------------------------------------
def fmt_seconds(sec) -> str:
    """秒数を日本語にする（一時停止からの経過など）。"""
    if not isinstance(sec, (int, float)) or sec < 0:
        return tr("不明", "unknown")
    return fmt_media_time(float(sec) * 1000.0)


def path_speech(path: str) -> str:
    """フォルダ・ファイルのパスを読み上げ用にする。

    区切り記号をそのまま渡すと「バックスラッシュ」を延々と読むので、
    要素ごとに読点で区切る（リプレイ保存パスを読まない方針と同じ趣旨で、
    記号を読ませないための整形）。
    """
    if not path:
        return tr("未設定", "not set")
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    return tr("、", ", ").join(parts) if parts else str(path)


def record_stopped_speech(path: str = "") -> str:
    """録画停止の読み上げ文。保存先が分かればファイル名を添える。

    フルパスは読まない（記号だらけで読み上げに向かない）。探すときの
    手がかりになるファイル名の本体だけにする。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path)
    if stem:
        return tr(f"録画を停止しました。ファイル {stem}", f"Stopped recording. File {stem}")
    return tr("録画を停止しました", "Stopped recording")


def replay_saved_speech(path: str = "") -> str:
    """リプレイ保存の読み上げ文。

    ★「保存を要求できた」ではなく「保存された」ときに読む。OBSの保存は
    非同期なので、要求が通った時点で言うと嘘になり得る。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path)
    if stem:
        return tr(f"リプレイを保存しました。ファイル {stem}", f"Saved replay. File {stem}")
    return tr("リプレイを保存しました", "Saved replay")


def pause_reminder_speech(elapsed_sec: float) -> str:
    """一時停止を放置していることを知らせる文。

    「まだ止まっている」ことと、経過時間を伝える。再開の手段も添える
    （そのために押すキーを思い出せないと意味がないため）。
    """
    return (tr(f"録画は一時停止のままです。{fmt_seconds(elapsed_sec)}経過しました。"
               "再開するには Ctrl+P を押してください",
       f"Recording is still paused. {fmt_seconds(elapsed_sec)} have passed. Press Ctrl+P to resume"))


def disk_warning_speech(level: int, free_mb: float) -> str:
    """空き容量の警告文。level は recording の DISK_WARN / DISK_CRITICAL。

    危険域では「どうすればよいか」まで言う。容量切れで録画が止まると、
    目で気づけない利用者は録れていないことに最後まで気づけないため。
    """
    from .recording import DISK_CRITICAL  # 循環参照を避けるため関数内 import

    free = _fmt_disk(free_mb) if isinstance(free_mb, (int, float)) else tr("不明", "unknown")
    if level == DISK_CRITICAL:
        return (tr(f"録画の保存先の空き容量がわずかです。残り {free}。"
                   "録画を止めるか、ファイルを移してください",
           f"The recording drive is almost full. {free} left. Stop recording or move some files"))
    return tr(f"録画の保存先の空き容量が少なくなっています。残り {free}", f"The recording drive is running low on space. {free} left")


def chapter_added_speech(index: int, timecode: str) -> str:
    """チャプターを打ったときの読み上げ文。"""
    return tr(f"チャプター{int(index)} を付けました、{timecode_to_speech(timecode)}", f"Added chapter {int(index)}, {timecode_to_speech(timecode)}")


# 録画フォーマットの識別子 → 読み上げ用の名前。無いものは識別子のまま読む。
_REC_FORMAT_JP = {
    "mp4": "MP4",
    "hybrid_mp4": tr("ハイブリッドMP4", "Hybrid MP4"),
    "fragmented_mp4": tr("フラグメントMP4", "Fragmented MP4"),
    "mov": "MOV",
    "hybrid_mov": tr("ハイブリッドMOV", "Hybrid MOV"),
    "fragmented_mov": tr("フラグメントMOV", "Fragmented MOV"),
    "mkv": "MKV",
    "mpegts": "MPEG-TS",
    "flv": "FLV",
    "m3u8": "HLS",
}

# エンコーダの識別子 → 読み上げ用の名前。
# ★値に読点を入れない。読み上げ文は「ラベル 値」を読点で連ねる形なので、
#   値の中の読点が項目の区切りに聞こえてしまう（props.py の PRIORITY_JP と
#   同じ理由）。補足は空白で区切る。
_REC_ENCODER_JP = {
    "x264": tr("x264 CPUで処理", "x264 on CPU"),
    "obs_x264": tr("x264 CPUで処理", "x264 on CPU"),
    "nvenc": tr("NVENC GPUで処理", "NVENC on GPU"),
    "jim_nvenc": tr("NVENC GPUで処理", "NVENC on GPU"),
    "obs_nvenc_h264_tex": tr("NVENC GPUで処理", "NVENC on GPU"),
    "jim_hevc_nvenc": tr("NVENC HEVC GPUで処理", "NVENC HEVC on GPU"),
    "amd": tr("AMD GPUで処理", "AMD on GPU"),
    "qsv": tr("クイックシンク GPUで処理", "Quick Sync on GPU"),
    "obs_qsv11": tr("クイックシンク GPUで処理", "Quick Sync on GPU"),
    "none": tr("配信と同じ設定", "same as stream"),
}

# 簡易出力の録画品質。
_REC_QUALITY_JP = {
    "Stream": tr("配信と同じ品質", "same quality as stream"),
    "Small": tr("高品質 ファイル小", "high quality medium file size"),
    "HQ": tr("高品質 ファイル中", "high quality large file size"),
    "Lossless": tr("無劣化 ファイル特大", "lossless huge file size"),
}


def rec_format_jp(value: str) -> str:
    """録画フォーマットの識別子を読み上げ用の名前にする。"""
    key = str(value or "").strip().lower()
    return _REC_FORMAT_JP.get(key, value or tr("不明", "unknown"))


def record_settings_summary(settings: dict) -> str:
    """録画設定の読み上げ文。

    OBS本体の[設定→出力]にはスクリーンリーダーで読めない領域があるため、
    ここが録画設定を確かめる唯一の手段になる。取れなかった項目は黙って
    落とす（「不明」を並べても判断材料にならないため）。
    """
    if not settings:
        return tr("録画設定を取得できませんでした", "Could not get the recording settings")
    parts: list[str] = []
    directory = settings.get("directory")
    if directory:
        parts.append(tr(f"保存先 {path_speech(directory)}", f"Folder {path_speech(directory)}"))
    fmt = settings.get("format")
    if fmt:
        parts.append(tr(f"フォーマット {rec_format_jp(fmt)}", f"Format {rec_format_jp(fmt)}"))
    quality = settings.get("quality")
    if quality:
        parts.append(tr(f"品質 {_REC_QUALITY_JP.get(str(quality), quality)}", f"Quality {_REC_QUALITY_JP.get(str(quality), quality)}"))
    encoder = settings.get("encoder")
    if encoder:
        parts.append(
            tr(f"エンコーダー {_REC_ENCODER_JP.get(str(encoder), encoder)}", f"Encoder {_REC_ENCODER_JP.get(str(encoder), encoder)}"))
    tracks = settings.get("tracks")
    if tracks:
        # ★RecTracks はビットの合計（トラック1〜4なら 15）。そのまま読むと
        #   「音声トラック 15」と聞こえるので、トラックの番号へ直す
        from .tracks import mask_to_tracks, track_list_text
        states = mask_to_tracks(tracks)
        text = track_list_text(states) if states is not None else ""
        parts.append(tr(f"録画する音声 {text}", f"Recorded audio {text}") if text
                     else tr(f"音声トラック {tracks}", f"Audio tracks {tracks}"))
    disk = settings.get("disk_free_mb")
    if isinstance(disk, (int, float)):
        parts.append(tr(f"空き容量 {_fmt_disk(disk)}", f"Free space {_fmt_disk(disk)}"))
    if not parts:
        return tr("録画設定を取得できませんでした", "Could not get the recording settings")
    # チャプターの可否は、この設定から分かる中でいちばん見落としやすい
    if fmt:
        parts.append(chapter_status_speech(fmt, settings.get("output_kind", "")))
    return tr("録画設定。", "Recording settings. ") + tr("、", ", ").join(parts)


def chapter_status_speech(rec_format: str, output_kind: str = "") -> str:
    """チャプターが使える状態かを一言で言う。

    ★設定と実態はずれ得る。録画フォーマットを変えても起動中のOBSは
    出力を作り直さないため、「設定はハイブリッドMP4だが実際は従来の出力」
    という状態が起きる（実測で確認）。設定だけを見て「使えます」と読むと
    嘘になるので、実態（出力の種別）が分かるときはそちらを優先する。
    """
    from .recording import (  # 循環参照を避けるため関数内 import
        output_supports_chapters, supports_chapters)

    if not supports_chapters(rec_format):
        return tr("このフォーマットではチャプターは使えません", "Chapters cannot be used with this format")
    if output_kind and not output_supports_chapters(output_kind):
        return tr("チャプターはOBSを再起動すると使えます", "Chapters can be used after restarting OBS")
    return tr("チャプターが使えます", "Chapters can be used")


def chapter_unsupported_speech(
    rec_format: str = "", output_kind: str = ""
) -> str:
    """チャプターが打てなかったときの案内文。

    原因はほぼ録画フォーマット。何をすれば使えるようになるかまで言う。

    ★ただし「設定は変えたのに反映されていない」場合がある。フォーマットを
    変えても起動中のOBSは出力を作り直さないため（実測）、設定だけ見て
    「フォーマットを変えてください」と言うと、既に変えた利用者は打つ手が
    分からなくなる。そのときは再起動が要ることを伝える。
    """
    from .recording import (  # 循環参照を避けるため関数内 import
        output_supports_chapters, supports_chapters)

    if rec_format and supports_chapters(rec_format):
        if output_kind and not output_supports_chapters(output_kind):
            return (tr(f"録画フォーマットは {rec_format_jp(rec_format)} に"
                       "なっていますが、OBSにまだ反映されていません。"
                       "OBSを再起動すると使えるようになります",
               f"The recording format is set to {rec_format_jp(rec_format)}, but OBS has not applied it yet. Restart OBS to use chapters"))
        # 設定も実態も対応しているのに拒否された。原因が分からないので
        # 決めつけず、確かめられることだけ言う
        return (tr("チャプターを付けられませんでした。"
                   "録画が始まっているか確かめてください",
           "Could not add a chapter. Check that recording has started"))
    now = tr(f"今は {rec_format_jp(rec_format)} です。", f"It is {rec_format_jp(rec_format)} now. ") if rec_format else ""
    return (tr("チャプターは録画フォーマットがハイブリッドMP4か"
               "ハイブリッドMOVのときだけ使えます。"
               f"{now}OBSの設定、出力、録画フォーマットで変えてください",
       f"Chapters can be used only when the recording format is Hybrid MP4 or Hybrid MOV. {now}Change it in OBS Settings, Output, Recording Format"))


def chapter_not_recording_speech() -> str:
    """録画していないときにチャプターを打とうとしたときの案内文。"""
    return tr("録画していないので、チャプターは付けられません", "Not recording, so a chapter cannot be added")


# ------------------------------------------------------------
# 音声フィルターの設定
# ------------------------------------------------------------
def fmt_filter_value(spec, raw) -> str:
    """フィルターの設定値1つを読み上げ用にする。

    数値は単位まで読む。小数は整数に乗るときだけ整数で読む
    （「マイナス18.0デシベル」より「マイナス18デシベル」の方が短い）。
    """
    from .filters import SIDECHAIN_NONE, choice_label  # 循環参照回避

    if spec.type == "choice":
        return choice_label(spec, raw)
    if spec.type == "source":
        text = str(raw or "")
        return tr("なし", "none") if not text or text == SIDECHAIN_NONE else text
    if spec.type == "bool":
        return tr("オン", "on") if bool(raw) else tr("オフ", "off")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if spec.unit == tr("デシベル", " decibels"):
        # 音量と同じ読み方に揃える（記号を読ませない）
        return _db_number(int(value) if value == int(value)
                          else round(value, 1))
    number = int(value) if value == int(value) else round(value, 2)
    return f"{number}{spec.unit}"


def filter_prop_row(spec, raw) -> str:
    """フィルター設定の一覧の1行（「比率、10対1」）。"""
    return prop_row_label(spec.label, fmt_filter_value(spec, raw))


def filter_prop_changed_speech(filter_name: str, spec, raw) -> str:
    """フィルターの設定を1つ変えたときの読み上げ文。"""
    return (tr(f"{filter_name} の {spec.label} を "
               f"{fmt_filter_value(spec, raw)} にしました",
       f"Set {spec.label} of {filter_name} to {fmt_filter_value(spec, raw)}"))


def filter_prop_unchanged_speech(filter_name: str, spec) -> str:
    """投げたのに値が変わらなかったときの警告文。

    フィルターには設定変更のイベントが無く、読み直しでしか確かめられない。
    ずれていたら黙らずに言う（変わったつもりで変わっていないのが一番困る）。
    """
    return (tr(f"{filter_name} の {spec.label} は変わりませんでした。"
               "OBSが受け付けていません",
       f"{spec.label} of {filter_name} did not change. OBS did not accept it"))


def filter_no_props_speech(filter_name: str, known: bool) -> str:
    """設定項目が無いフィルターを開いたときの案内文。

    「このアプリでは変えられない」のか「そもそも設定が無い」のかを
    言い分ける。前者なら OBS 本体で触る手が残っているため。
    """
    if known:
        return tr(f"{filter_name} に変えられる設定はありません。オン・オフだけです", f"{filter_name} has no settings to change. It can only be turned on or off")
    return (tr(f"{filter_name} の設定は、このアプリでは変えられません。"
               "OBSの画面で変更してください",
       f"The settings of {filter_name} cannot be changed in this app. Change them in OBS"))


def filter_added_speech(filter_name: str, source: str) -> str:
    """フィルターを追加したときの読み上げ文。"""
    return tr(f"{source} に {filter_name} を追加しました", f"Added {filter_name} to {source}")


def filter_removed_speech(filter_name: str, source: str) -> str:
    """フィルターを削除したときの読み上げ文。"""
    return tr(f"{source} から {filter_name} を削除しました", f"Removed {filter_name} from {source}")


def filter_kind_row(info) -> str:
    """追加できるフィルター1件の読み上げ行（名前と、何のためのものか）。

    種別の名前だけでは何をするものか分からないので、一言添える。
    フィルターを初めて入れる人が選べることを優先する。
    """
    return tr(f"{info.label}、{info.hint}", f"{info.label}, {info.hint}") if info.hint else info.label


def filter_none_speech(source: str) -> str:
    """フィルターが1つも無いときの案内文。"""
    return (tr(f"{source} にフィルターはありません。"
               "フィルターを追加のボタンで足せます",
       f"{source} has no filters. You can add one with Add Filter"))


# ------------------------------------------------------------
# カメラ（映像キャプチャデバイス）
# ------------------------------------------------------------
def camera_state_speech(state) -> str:
    """カメラ1台の状態を読み上げ用にする。

    ★「動いているか」と「映像が来ているか」を必ず言い分ける。
    見えない利用者にとって、カメラが動いているかは読み上げでしか
    分からない（本体のランプが判断材料にならない）。
    有効なのに映像が来ていない状態は実在する（起動直後、信号なし）ので、
    そこを「動いています」で丸めると嘘になる。
    """
    from .camera import (  # 循環参照を避けるため関数内 import
        STATE_OFF, STATE_ON, STATE_ON_NO_SIGNAL)

    head = f"{state.name}"
    if state.device and state.device != tr("未設定", "not set"):
        head += tr(f"、{state.device}", f", {state.device}")
    if state.state == STATE_OFF:
        body = tr("止まっています。カメラは使われていません", "stopped. The camera is not in use")
    elif state.state == STATE_ON:
        body = tr("動いています。映像が来ています", "running. Video is coming in")
    elif state.state == STATE_ON_NO_SIGNAL:
        body = tr("動いていますが、映像は来ていません", "running, but no video is coming in")
    else:
        body = tr("状態が分かりません", "state unknown")
    text = tr(f"{head}、{body}", f"{head}, {body}")
    # 表示・非表示は別の話。動いていても非表示なら配信には出ない
    if state.visible is False:
        text += tr("。シーンでは非表示です", ". Hidden in the scene")
    return text


def camera_list_speech(states, unused=None) -> str:
    """カメラ全体の状態をまとめて読む（確認用）。

    つないであるのにOBSで使っていない機材も知らせる。
    「ウェブカメラをつないだのに出てこない」に自力で気づけるようにする。
    """
    items = list(states or [])
    parts: list[str] = []
    if not items:
        parts.append(tr("OBSに映像キャプチャデバイスのソースがありません", "There are no video capture device sources in OBS"))
    else:
        parts.append(tr(f"カメラ {len(items)} 件", f"{len(items)} cameras"))
        parts.extend(camera_state_speech(s) for s in items)
    spare = list(unused or [])
    if spare:
        parts.append(
            tr("使っていない機材: ", "Unused devices: ") + tr("、", ", ").join(spare)
            + tr("。OBSでソースを作ると使えます", ". Create a source in OBS to use them"))
    return tr("。", ". ").join(parts)


def camera_toggle_intent_speech(name: str, turning_on: bool) -> str:
    """カメラの切り替えを始めたときの読み上げ文。

    切り替えは1〜2秒かかる（実測）。その間に何も言わないと、キーが
    効いたのかどうか分からないので、先に何をするかだけ伝える。
    結果は必ず camera_toggle_result_speech で確かめてから言う。
    """
    return tr(f"{name} を動かします", f"Starting {name}") if turning_on else tr(f"{name} を止めます", f"Stopping {name}")


def camera_toggle_result_speech(state, expected_active: bool) -> str:
    """切り替えたあと、実際の状態を確かめて読む文。

    ★期待どおりにならなかったら、はっきり言う。カメラが止まったと
    思い込ませるのが一番危ない。
    """
    if state is None:
        return tr("カメラの状態を確認できませんでした", "Could not check the camera state")
    if state.active != expected_active:
        if expected_active:
            return tr(f"{state.name} を動かせませんでした", f"Could not start {state.name}")
        return (tr(f"{state.name} を止められませんでした。"
                   "カメラはまだ動いています",
           f"Could not stop {state.name}. The camera is still running"))
    return camera_state_speech(state)


# ------------------------------------------------------------
# ソースの作成・削除
# ------------------------------------------------------------
def source_kind_row(info) -> str:
    """作れるソース1件の読み上げ行（名前と、何のためのものか）。

    種別の名前だけでは何をするものか分からないので一言添える。
    フィルターの追加一覧と同じ考え方。
    """
    return tr(f"{info.label}、{info.hint}", f"{info.label}, {info.hint}") if info.hint else info.label


def source_created_speech(name: str, info, scene: str) -> str:
    """ソースを作ったときの読み上げ文。

    ★作っただけでは使えない種類が多い（カメラは機材を、ウィンドウ
    キャプチャは対象を選ばないと何も映らない）。作れたことだけ伝えて
    放すと「足したのに使えない」で止まるので、次に何をするかまで言う。
    """
    head = tr(f"{scene} に {name} を作りました", f"Created {name} in {scene}")
    if getattr(info, "needs", ""):
        return tr(f"{head}。続けて設定を開きます", f"{head}. Opening its settings next")
    return head


def source_remove_warning(name: str, roles=None) -> str:
    """ソースを削除する前の確認文。

    ★入力の削除は「このシーンから外す」ではなく**すべてのシーンから
    消える**。設定も失われて元に戻せない。目で確かめられない以上、
    何が起きるかを言葉で全部書く。
    設定で使っているソース（BGM、ゲーム切り替えなど）ならそれも言う。
    """
    parts = [tr(f"ソース「{name}」を削除しますか？", f"Delete the source \"{name}\"?"),
             tr("すべてのシーンから消えて、設定も元に戻せません。", "It disappears from all scenes, and its settings cannot be restored.")]
    used = list(roles or [])
    if used:
        parts.append(
            tr("このソースは ", "This source is used for ") + tr("、", ", ").join(used) + tr(" に使っています。"
               "削除するとその機能が動かなくなります。",
               ". Deleting it will stop those features from working."))
    return "\n".join(parts)


def source_removed_speech(name: str) -> str:
    """ソースを削除したときの読み上げ文。"""
    return tr(f"{name} を削除しました", f"Deleted {name}")


# ------------------------------------------------------------
# シーン
# ------------------------------------------------------------
def scene_created_speech(name: str) -> str:
    """シーンを作ったときの読み上げ文。

    ★作っても現在のシーンは変わらない（実測）。切り替わったと誤解すると
    「配信の画面が変わった」と思わせるので、変わらないことを明言する。
    作った直後は空なので、次にやることも言う。
    """
    return (tr(f"シーン {name} を作りました。今の画面は変わっていません。"
               "続けて設定を開きます。ソースを追加できます",
       f"Created scene {name}. The current screen has not changed. Opening its settings next, where you can add sources"))


def scene_renamed_speech(old: str, new: str) -> str:
    """シーンの名前を変えたときの読み上げ文。"""
    return tr(f"シーン {old} を {new} に変えました", f"Renamed scene {old} to {new}")


def scene_remove_warning(name: str, is_current: bool = False) -> str:
    """シーンを削除する前の確認文。

    ★何が失われるかを言葉で全部書く。目で確かめられない以上、
    「消したらどうなるか」を read しか判断材料が無い。
    そのシーンにしか無いソースは一緒に消えるが、他のシーンにも置いて
    あるソースは残る（実測で確認）。
    """
    parts = [tr(f"シーン「{name}」を削除しますか？", f"Delete the scene \"{name}\"?"),
             tr("このシーンにしか無いソースも一緒に消えます。", "Sources that exist only in this scene are deleted with it."),
             tr("他のシーンにも置いてあるソースは残ります。", "Sources that are also placed in other scenes remain."),
             tr("元に戻せません。", "This cannot be undone.")]
    if is_current:
        parts.insert(1, tr("★これは今映しているシーンです。"
                           "削除すると別のシーンに切り替わります。",
           "Note: this is the scene on air now. Deleting it switches to another scene."))
    return "\n".join(parts)


def scene_removed_speech(name: str) -> str:
    """シーンを削除したときの読み上げ文。"""
    return tr(f"シーン {name} を削除しました", f"Deleted scene {name}")


def scene_transition_row(current, transitions=None) -> str:
    """シーン設定の「トランジション」行。

    設定していなければ、全体の設定に従うことが分かるように読む
    （「未設定」だと、切り替え効果が無いのか設定が無いのか分からない）。
    """
    if not current.overridden:
        return prop_row_label(tr("切り替え効果", "Transition"), tr("全体の設定に従う", "follow the global setting"))
    return prop_row_label(tr("切り替え効果", "Transition"), current.name)


def scene_duration_row(current) -> str:
    """シーン設定の「切り替えの長さ」行。"""
    ms = current.duration_ms
    if not isinstance(ms, (int, float)):
        return prop_row_label(tr("切り替えの長さ", "Transition duration"), tr("既定", "default"))
    return prop_row_label(tr("切り替えの長さ", "Transition duration"), tr(f"{int(ms)}ミリ秒", f"{int(ms)} milliseconds"))


def scene_transition_changed_speech(scene: str, current) -> str:
    """シーンのトランジションを変えたときの読み上げ文。"""
    if not current.overridden:
        return tr(f"{scene} の切り替え効果を全体の設定に戻しました", f"Reset the transition of {scene} to the global setting")
    return tr(f"{scene} の切り替え効果を {current.name} にしました", f"Set the transition of {scene} to {current.name}")


def scene_source_added_speech(scene: str, source: str) -> str:
    """既存ソースをシーンに追加したときの読み上げ文。

    ★コピーではなく共有であることを伝える。片方で設定を変えると
    両方に効くので、知らないと戸惑う。
    """
    return (tr(f"{scene} に {source} を追加しました。"
               "同じソースを共有するので、設定を変えると両方に効きます",
       f"Added {source} to {scene}. The same source is shared, so changing its settings affects both"))


def scene_no_addable_speech(scene: str) -> str:
    """追加できるソースが無いときの案内文。"""
    return (tr(f"{scene} に追加できるソースがありません。"
               "すべてこのシーンに置いてあります",
       f"No sources can be added to {scene}. All of them are already in this scene"))


def camera_none_speech() -> str:
    """カメラのソースが無いときの案内文。"""
    return (tr("映像キャプチャデバイスのソースがありません。"
               "OBSでウェブカメラやキャプチャーボードのソースを作ってください",
       "There are no video capture device sources. Create a webcam or capture card source in OBS"))


def license_notice_speech() -> str:
    """「OBSナビについて」で読むライセンスの告知。

    ★OBSナビは GPL-3.0 で配っている（使っている obsws-python が
    GPL-3.0 のため）。GPL-3.0 は、操作画面のある作品に「著作権の表示・
    無保証であること・同じライセンスで配れること・ライセンスの見方」を
    画面から確かめられるようにすることを求める（第5条 d の「適切な
    法的告知」）。メニューの目立つ項目で示せばよいとされているので、
    ヘルプメニューの「OBSナビについて」で読む。
    ★末尾に句点を付けない。呼ぶ側（on_about）が「。」で文を連ねる。
    """
    return (tr("著作権 Takahashi。"
               "このソフトは GNU GPL 第3版のもとで配布しています。"
               "同じライセンスのもとで、改変や再配布ができます。"
               "無保証です。"
               "ライセンスの全文は、同梱の LICENSE.txt にあります",
       "Copyright Takahashi. This software is distributed under the GNU GPL version 3. You may modify and redistribute it under the same license. It comes with no warranty. The full license text is in the included LICENSE.txt"))


def ai_notice_speech() -> str:
    """「OBSナビについて」で読む、AI を使って作ったことの告知。

    ★README・マニュアルの「AI を使って作ったこと」と同じ趣旨を短く言う。
    ★末尾に句点を付けない。呼ぶ側（on_about）が「。」で文を連ねる。
    """
    return (tr("このソフトは、AI（Anthropic の Claude）を使って作りました。"
               "何を作るかと読み上げでの使いやすさは作者が決め、"
               "スクリーンリーダーで使って確かめています",
       "This software was made with AI (Anthropic's Claude). The author decided what to build and how it should work with speech, and checks it with a screen reader"))


# ------------------------------------------------------------
# 録画の音声トラック割り当て（core/tracks.py）
# ------------------------------------------------------------
def input_track_row(number: int, on: bool) -> str:
    """ソースの設定画面の行（「録画のトラック2、オン」）。

    ★1行1トラックにして、Enter で入り切りする（オン・オフの設定と同じ
    操作）。チェックボックスの並んだ表は VoiceOver で扱いにくいため。
    """
    return tr(f"録画のトラック{number}、{'オン' if on else 'オフ'}", f"Recording track {number}, {'on' if on else 'off'}")


def input_tracks_changed_speech(name: str, number: int, on: bool,
                                states) -> str:
    """ソースのトラックを切り替えたときの読み上げ文（今の全体も言う）。"""
    from .tracks import track_list_text
    head = (tr(f"{name} をトラック{number}に出しました", f"Sent {name} to track {number}") if on
            else tr(f"{name} をトラック{number}から外しました", f"Removed {name} from track {number}"))
    now = track_list_text(states)
    tail = tr(f"今は{now}", f"Now {now}") if now else tr("今はどのトラックにも出していません", "Now it is not sent to any track")
    return tr(f"{head}。{tail}", f"{head}. {tail}")


def input_tracks_unchanged_speech(name: str) -> str:
    """切り替えを投げたのに読み直すと変わっていなかったとき。"""
    return tr(f"{name} のトラックは変わりませんでした。OBSが受け付けていません", f"The tracks of {name} did not change. OBS did not accept it")


def record_track_row(number: int, on: bool) -> str:
    """録画のトラック設定の画面の行（「トラック1を録画する、オン」）。"""
    return tr(f"トラック{number}を録画する、{'オン' if on else 'オフ'}", f"Record track {number}, {'on' if on else 'off'}")


def record_tracks_changed_speech(states) -> str:
    """録画するトラックを変えたときの読み上げ文。"""
    from .tracks import track_list_text
    now = track_list_text(states)
    if not now:
        return (tr("録画するトラックがありません。"
                   "このままだと音の無い録画になります",
           "No tracks are recorded. The recording will have no sound"))
    return tr(f"録画する音声を{now}にしました。次の録画から効きます", f"Set recorded audio to {now}. Takes effect from the next recording")


def tracks_overview_speech(input_tracks: dict, recorded, note: str = "") -> str:
    """録画のトラック割り当てをまとめて読む文。

    input_tracks は {入力名: オン・オフの並び}（音声入力一覧の順）、
    recorded は録画するトラックの並び（読めなければ None）。
    ★録画されないトラックにしか出していない入力を最後に言い当てる
    （画面を見ないと気づけない食い違いなので）。
    """
    from .tracks import track_list_text, unrecorded_inputs
    parts: list[str] = []
    if recorded is None:
        parts.append(tr("録画するトラックを読めませんでした", "Could not read the recorded tracks"))
    else:
        text = track_list_text(recorded)
        parts.append(tr(f"録画する音声は{text}", f"Recorded audio is {text}") if text
                     else tr("録画するトラックがありません", "No tracks are recorded"))
    for name, states in (input_tracks or {}).items():
        text = track_list_text(states)
        parts.append(tr(f"{name} は{text}", f"{name} is on {text}") if text
                     else tr(f"{name} はどのトラックにも出していません", f"{name} is not sent to any track"))
    if not input_tracks:
        parts.append(tr("音声を持つソースがありません", "There are no sources with audio"))
    if recorded is not None and input_tracks:
        missing = unrecorded_inputs(input_tracks, recorded)
        if missing:
            parts.append(tr("次のソースは録画に入りません。", "The following sources are not recorded: ")
                         + tr("、", ", ").join(missing))
    if note:
        parts.append(note)
    return tr("。", ". ").join(parts)


def tracks_recommendation_speech() -> str:
    """作曲の配信・録画で勧める割り当ての案内。"""
    from .tracks import RECOMMENDED
    rows = [tr(f"{label} はトラック", f"{label} on track ") + tr("と", " and ").join(str(n) for n in nums)
            for label, nums in RECOMMENDED]
    return (tr("おすすめの割り当て。", "Recommended assignment. ") + tr("、", ", ").join(rows)
            + tr("。トラック1は全部入りで、配信と同じ音になります", ". Track 1 has everything and sounds the same as the stream"))
