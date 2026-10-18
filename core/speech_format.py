# -*- coding: utf-8 -*-
"""読み上げ文の整形（純関数・OS非依存）。

数値やタイムコードは、PC-Talker で誤読しにくい日本語表現に変換する。
（例: "-18dB" のような記号混じりを避け、「マイナス18デシベル」と読む）
"""
from __future__ import annotations

from . import ordering
from .state import Snapshot
from .volume import VOLUME_MIN_DB

SILENCE_SPEECH_DB = -90.0  # これ以下は「無音」と読む


def _db_number(value: float) -> str:
    """dB値の符号と数値の部分を日本語にする（単位まで含む）。"""
    if value < 0:
        return f"マイナス{abs(value)}デシベル"
    if value == 0:
        return "0デシベル"
    return f"プラス{value}デシベル"


def fmt_db(db: float) -> str:
    """レベル(メーター読み)のdB値を読み上げ用の日本語にする。"""
    if db <= SILENCE_SPEECH_DB:
        return "無音"
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
        return "最小"
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
    parts: list[str] = []
    if h:
        parts.append(f"{h}時間")
    if m or h:
        parts.append(f"{m}分")
    parts.append(f"{s}秒")
    return "".join(parts)


def state_summary(snap: Snapshot) -> str:
    """状態の要約文。"""
    if not snap.connected:
        return "OBSに接続していません"
    parts: list[str] = []
    if snap.streaming:
        parts.append(f"配信中 {timecode_to_speech(snap.stream_timecode)}")
    else:
        parts.append("配信停止中")
    if snap.recording:
        # ★一時停止は「録画中のまま止まっている」状態。画面を見れば分かるが
        #   読み上げには出ないため、忘れるとその間が録れていない事故になる。
        #   ここで必ず言い分ける（F5で確かめられる唯一の場所）。
        label = "録画一時停止中" if snap.record_paused else "録画中"
        parts.append(f"{label} {timecode_to_speech(snap.record_timecode)}")
    else:
        parts.append("録画停止中")
    if snap.current_scene:
        parts.append(f"現在のシーン {snap.current_scene}")
    return "、".join(parts)


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
        return "レベル情報がまだありません"
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
            parts.append(f"{name} ミュート中")
        else:
            parts.append(f"{name} {fmt_db(peaks[name])}")
    if not parts:
        # 全部飛ばした。無言で終わると「キーが効いていない」のと区別が
        # 付かないので、飛ばしたことを必ず言う
        return f"読み上げるレベルがありません。{skipped}件すべてミュート中です"
    return "、".join(parts)


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
        return f"{what}を{ordering.default_label(sort_rest)}に戻しました"
    shown = list(live)
    if not shown:
        # 保存はしたが、今あるものが1つも無い（全部が古い名前）
        return f"{what}を保存しました。今あるものはありません"
    return f"{what}を保存しました。{len(shown)}件、最初は {shown[0]}"


def order_unchanged_speech(what: str) -> str:
    """並べ替えの画面を開いたが、順番を変えずに閉じたときの読み上げ。

    ★変えていないのに「戻しました」と言わない。確かめるために開いた
    だけなのに、設定を書き換えたように聞こえる（レビューで判明）。
    """
    return f"{what}は変えませんでした"


def config_save_failed_speech(what: str) -> str:
    """設定を保存できなかったときの読み上げ。

    ★「保存しました」と嘘をつかない。設定ファイルが読めなかったときは
    上書きを避けて何もしないので、そのまま成功を読み上げると、
    再起動して初めて消えていることに気づく（耳では確かめようが無い）。
    """
    return (f"{what}を保存できませんでした。"
            "設定ファイルが読み込めていないため、上書きしていません")


def order_reset_speech(sort_rest: bool, dropped: int = 0) -> str:
    """並べ替え画面で「戻す」を押したときの読み上げ。

    ★ボタンの文言（終止形）に「ました」を足してはいけない。
    「OBSと同じ順に戻すました」という壊れた日本語になる（レビューで
    見つかった。読み上げが唯一の出力なので、そのまま耳に入る）。
    """
    label = ordering.default_label(sort_rest)
    head = f"{label}に並べ直しました" if sort_rest else f"{label}に戻しました"
    if dropped:
        return f"{head}。今は無いもの{dropped}件は一覧から外しました"
    return head


def item_moved_speech(name: str, pos: int, total: int, forward: bool) -> str:
    """重なり順を変えたときの読み上げ。

    ★一覧の並びを自分で決めている場合、重なり順を変えても一覧の行は
      動かない。だから「今どこにいるか」を必ず言葉で言う。
    pos は1始まりの「前から数えた位置」。
    """
    where = "前に出しました" if forward else "後ろに送りました"
    return f"{name} を{where}。{total}件中、前から{pos}番目"


def item_move_edge_speech(name: str, forward: bool) -> str:
    """これ以上動かせないときの読み上げ。

    ★同じ意味の文を2つ持たない。映像切り替えの
    video_already_front_speech もここへ寄せてある（別々に書いていた
    ので「既に」と「すでに」で表記が割れていた）。
    """
    edge = "前" if forward else "後ろ"
    return f"{name} はすでにいちばん{edge}です"


def skip_muted_speech(skip: bool) -> str:
    """ミュート中を読み飛ばす設定を切り替えたときの読み上げ。"""
    if skip:
        return "ミュート中のソースはレベル読み上げに出しません"
    return "ミュート中のソースもレベル読み上げに出します"


# フィルター種別の内部名 → 読み上げ用の日本語。無いものは内部名のまま読む。
_FILTER_KIND_JP = {
    "noise_suppress_filter": "ノイズ抑制",
    "noise_suppress_filter_v2": "ノイズ抑制",
    "noise_gate_filter": "ノイズゲート",
    "compressor_filter": "コンプレッサー",
    "upward_compressor_filter": "アップワードコンプレッサー",
    "limiter_filter": "リミッター",
    "expander_filter": "エキスパンダー",
    "gain_filter": "ゲイン",
    "basic_eq_filter": "イコライザー",
    "invert_polarity_filter": "位相反転",
    "vst_filter": "ブイエスティープラグイン",
    "async_delay_filter": "音声遅延",
    "chroma_key_filter": "クロマキー",
    "chroma_key_filter_v2": "クロマキー",
    "color_key_filter": "カラーキー",
    "color_key_filter_v2": "カラーキー",
    "luma_key_filter": "ルマキー",
    "luma_key_filter_v2": "ルマキー",
    "color_filter": "色補正",
    "color_filter_v2": "色補正",
    "crop_filter": "クロップ",
    "scale_filter": "スケール",
    "sharpness_filter": "シャープ",
    "sharpness_filter_v2": "シャープ",
    "mask_filter": "画像マスク",
    "mask_filter_v2": "画像マスク",
    "scroll_filter": "スクロール",
    "gpu_delay": "映像遅延",
    "hdr_tonemap_filter": "HDRトーンマップ",
    "clut_filter": "ルックアップテーブル",
}


def filter_kind_jp(kind: str) -> str:
    """フィルター種別の内部名を読み上げ用の日本語にする。無ければそのまま。"""
    return _FILTER_KIND_JP.get(kind, kind)


def filter_list_label(name: str, enabled: bool) -> str:
    """フィルター一覧の1行表示。

    フィルター名はユーザーが付けた名前（既定では種別の日本語名）なので、
    名前をそのまま出す。状態はオン/オフを明示する。
    """
    return f"{name} オン" if enabled else f"{name} オフ"


def filter_toggle_speech(name: str, enabled: bool) -> str:
    """フィルターを切り替えたときの読み上げ文。"""
    return f"{name} を有効にしました" if enabled else f"{name} を無効にしました"


def scene_item_list_label(name: str, enabled: bool) -> str:
    """シーン内ソース一覧の1行表示。

    可視性なので「表示中／非表示」と読む（ミュートの「オン／ミュート中」と
    混同しないよう別の語にする）。
    """
    return f"{name} 表示中" if enabled else f"{name} 非表示"


def scene_item_toggle_speech(name: str, enabled: bool) -> str:
    """シーン内ソースの表示を切り替えたときの読み上げ文。"""
    return f"{name} を表示しました" if enabled else f"{name} を非表示にしました"


def _fmt_disk(mb: float) -> str:
    """空きディスク容量(MB)を読みやすい単位にする。"""
    if mb >= 1024 * 1024:
        return f"{mb / (1024 * 1024):.1f}テラバイト"
    if mb >= 1024:
        return f"{mb / 1024:.1f}ギガバイト"
    return f"{int(round(mb))}メガバイト"


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
        parts.append(f"CPU {cpu:.0f}パーセント")
    fps = stats.get("fps")
    if isinstance(fps, (int, float)):
        parts.append(f"エフピーエス {fps:.0f}")

    def _skip_part(label, total, skipped):
        if not isinstance(total, int) or not isinstance(skipped, int):
            return None
        if total <= 0:
            return None
        if skipped <= 0:
            return f"{label}のコマ落ちなし"
        pct = skipped / total * 100.0
        return f"{label}のコマ落ち {skipped}フレーム、{pct:.1f}パーセント"

    r = _skip_part("描画", stats.get("render_total"),
                   stats.get("render_skipped"))
    if r:
        parts.append(r)
    o = _skip_part("配信録画", stats.get("output_total"),
                   stats.get("output_skipped"))
    if o:
        parts.append(o)

    disk = stats.get("disk_free_mb")
    if isinstance(disk, (int, float)):
        parts.append(f"空き容量 {_fmt_disk(disk)}")
    return "、".join(parts) if parts else "統計を取得できませんでした"


def onoff_speech(label: str, active: bool) -> str:
    """オン・オフ状態の変化の読み上げ（仮想カメラなど）。"""
    return f"{label}を開始しました" if active else f"{label}を停止しました"


def input_list_label(
    name: str, muted: bool, volume_db: float | None = None
) -> str:
    """音声入力一覧の1行表示。

    一覧を上下で辿るとスクリーンリーダーがこの行を読む。ミュート状態だけ
    でなく音量も入れておくと、辿るだけで各入力の状態が分かる。
    volume_db=None のときは音量を出さない（まだ取得できていないとき）。
    """
    state = "ミュート中" if muted else "オン"
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
        cleaned = cleaned[:MAX_TITLE_CHARS] + " ほか"
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
        text = f"{title}、{exe}"
    else:
        text = title or exe or "名前なし"
    if not enabled:
        text += "、今は起動していません"
    return text


def window_value_label(window_value: str) -> str:
    """window の「設定値」を読み上げ用にする。

    選択肢一覧を取りに行かなくても現在値を読めるようにするためのもの。
    値の形は "タイトル:クラス:実行ファイル"。クラス名は利用者にとって
    意味が無いので読まない。
    """
    if not window_value:
        return "未設定"
    parts = window_value.rsplit(":", 2)
    if len(parts) < 3:
        return _tame_title(window_value) or "未設定"
    title, _cls, exe = parts
    if exe.lower().endswith(".exe"):
        exe = exe[:-4]
    title = _tame_title(title)
    exe = _tame_title(exe)
    if title and exe:
        return f"{title}、{exe}"
    return title or exe or "未設定"


def device_item_label(item_name: str, enabled: bool = True) -> str:
    """音声デバイス選択肢1件の読み上げ行。

    "Line (Steinberg UR44C)" のような括弧を読点に開く。
    """
    text = (item_name or "").replace("(", "、").replace(")", "")
    text = " ".join(text.split())
    # 「Line (Steinberg…」→「Line 、Steinberg…」のように読点の前後へ
    # 空白が残るので詰める（読点の直前で息継ぎが二重になるのを防ぐ）
    text = text.replace(" 、", "、").replace("、 ", "、").strip("、 ")
    if not text:
        text = "名前なし"
    if not enabled:
        text += "、今は使えません"
    return text


def prop_row_label(label: str, value_text: str) -> str:
    """設定項目一覧の1行（「対象ウィンドウ、ディアブロ IV」）。"""
    return f"{label}、{value_text}"


def prop_changed_speech(source: str, label: str, value_text: str) -> str:
    """設定を1つ変えたときの読み上げ文。"""
    return f"{source} の {label} を {value_text} にしました"


def prop_multi_changed_speech(source: str, pairs) -> str:
    """設定を複数変えたときの読み上げ文。

    pairs は (ラベル, 値の文字列) の並び。
    """
    items = list(pairs or [])
    if not items:
        return "変更はありません"
    if len(items) == 1:
        return prop_changed_speech(source, items[0][0], items[0][1])
    body = "、".join(f"{label} {value}" for label, value in items)
    return f"{source} を変えました。{body}"


def prop_unchanged_speech(source: str, label: str) -> str:
    """投げたのに値が変わらなかったときの警告文。"""
    return f"{source} の {label} は変わりませんでした。OBSが受け付けていません"


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
    parts = [f"{title} に切り替えました"]
    done = [video_source] + ok
    parts.append("、".join(done) + " を設定しました")
    if ng:
        parts.append(
            "、".join(ng) + " は対象が見つかりません。"
            f"ゲームを起動してから、もう一度 {key_name} で切り替えてください")
    elif not running:
        parts.append("今は起動していないので、ゲームを起動すると映ります")
    return "。".join(parts)


def fmt_media_time(ms) -> str:
    """再生位置・長さ(ミリ秒)を日本語にする。"""
    if not isinstance(ms, (int, float)) or ms < 0:
        return "不明"
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}時間")
    if m or h:
        parts.append(f"{m}分")
    parts.append(f"{s}秒")
    return "".join(parts)


_MEDIA_STATE_JP = {
    "OBS_MEDIA_STATE_PLAYING": "再生中",
    "OBS_MEDIA_STATE_PAUSED": "一時停止",
    "OBS_MEDIA_STATE_STOPPED": "停止",
    "OBS_MEDIA_STATE_ENDED": "再生が終わりました",
    "OBS_MEDIA_STATE_OPENING": "読み込み中",
    "OBS_MEDIA_STATE_BUFFERING": "読み込み中",
    "OBS_MEDIA_STATE_ERROR": "エラー",
    "OBS_MEDIA_STATE_NONE": "未再生",
}


def media_state_jp(state: str) -> str:
    """メディアの再生状態を日本語にする。"""
    return _MEDIA_STATE_JP.get(state, "状態不明")


def media_status_speech(name: str, state: str, cursor_ms, duration_ms) -> str:
    """メディアの現在状態の読み上げ文。

    再生位置・長さは再生中/一時停止のときしか返らないので、
    取れないときは状態だけを読む。
    """
    label = media_state_jp(state)
    if isinstance(cursor_ms, (int, float)) and isinstance(
        duration_ms, (int, float)
    ):
        return (f"{name} {label} {fmt_media_time(cursor_ms)}、"
                f"全体 {fmt_media_time(duration_ms)}")
    return f"{name} {label}"


def media_action_speech(name: str, action: str) -> str:
    """メディア操作イベントの読み上げ文。

    再生(PLAY)だけは PlaybackStarted 側で読むので、ここでは空文字を返す
    （呼び出し側は空なら読み上げない）。二重読みを避けるため。
    """
    if action.endswith("_PAUSE"):
        return f"{name} を一時停止しました"
    if action.endswith("_STOP"):
        return f"{name} を止めました"
    if action.endswith("_RESTART"):
        return f"{name} を最初から再生します"
    return ""


def media_started_speech(name: str) -> str:
    """再生が始まったときの読み上げ文。"""
    return f"{name} を再生します"


def media_ended_speech(name: str) -> str:
    """再生が終わったときの読み上げ文。"""
    return f"{name} の再生が終わりました"


def bgm_file_speech(name: str, path: str) -> str:
    """BGMのファイルを設定したときの読み上げ文。

    フルパスは記号だらけで読み上げに向かないのでファイル名の本体だけ読む
    （リプレイ保存パスを読まないのと同じ方針）。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path) or "名前不明"
    return f"{name} の音楽ファイルを {stem} にしました"


def video_item_label(name: str, index: int, top_index: int, blank: bool) -> str:
    """映像切り替えの候補1件の読み上げ行。

    ★「いま映っています」とは言わない。いちばん手前でも、ゲームが起動して
    いなければ絵は出ておらず、後ろのソースが見えている。断定すると嘘に
    なるので、位置（前面／後ろ）と「今は絵が出ていない」だけを伝える。
    """
    where = "前面" if index >= top_index else "後ろ"
    text = f"{name}、{where}"
    if blank:
        text += "、今は映っていません"
    return text


def video_front_speech(plan) -> str:
    """映像ソースを前に出したときの読み上げ文。"""
    parts = [f"{plan.name} を前に出しました"]
    if plan.behind:
        parts.append("、".join(plan.behind) + " が後ろになりました")
    if plan.blank:
        parts.append(
            f"ただし {plan.name} は今は映っていません。"
            "ゲームや機器が動いていないと、後ろのソースが見えます")
    return "。".join(parts)


def video_already_front_speech(name: str) -> str:
    """すでに最前面だったときの読み上げ文（重なり順の文言に合わせる）。"""
    return item_move_edge_speech(name, True)


def video_unchanged_speech(name: str) -> str:
    """投げたのに順番が変わらなかったときの警告文。"""
    return f"{name} を前に出せませんでした。OBSが受け付けていません"


def video_none_speech() -> str:
    """切り替えられる映像ソースが無いときの案内文。"""
    return ("切り替えられる映像ソースがありません。"
            "ゲームキャプチャや映像キャプチャデバイスを作ってから実行してください")


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
            return ("ただしモニタリングがオンなので、自分にはこのまま聞こえます"
                    "。止めるには一時停止してください")
        return "ただしモニタリングがオンなので、自分にはこのまま聞こえます"
    if not muted and mon_type == MONITOR_ONLY:
        # こちらは「今鳴っているか」ではなく音の行き先の話なので、
        # 止まっていても伝える（次に鳴らしたとき配信に乗らないため）
        return "ただしモニタリングが自分だけ聞く設定なので、配信には乗りません"
    return ""


def monitor_changed_speech(name: str, mon_type: str) -> str:
    """音声モニタリングを変えたときの読み上げ文。"""
    from .props import monitor_label  # 循環参照を避けるため関数内 import

    return f"{name} の音声モニタリングを {monitor_label(mon_type)} にしました"


def bgm_wrong_kind_speech(name: str) -> str:
    """既存ソースがメディアソースでないときの案内文。"""
    return (f"{name} はアプリの音を取り込む設定です。"
            "音楽ファイルを再生するには、新しくメディアソースを作る必要があります")


# ------------------------------------------------------------
# 録画まわり
# ------------------------------------------------------------
def fmt_seconds(sec) -> str:
    """秒数を日本語にする（一時停止からの経過など）。"""
    if not isinstance(sec, (int, float)) or sec < 0:
        return "不明"
    return fmt_media_time(float(sec) * 1000.0)


def path_speech(path: str) -> str:
    """フォルダ・ファイルのパスを読み上げ用にする。

    区切り記号をそのまま渡すと「バックスラッシュ」を延々と読むので、
    要素ごとに読点で区切る（リプレイ保存パスを読まない方針と同じ趣旨で、
    記号を読ませないための整形）。
    """
    if not path:
        return "未設定"
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    return "、".join(parts) if parts else str(path)


def record_stopped_speech(path: str = "") -> str:
    """録画停止の読み上げ文。保存先が分かればファイル名を添える。

    フルパスは読まない（記号だらけで読み上げに向かない）。探すときの
    手がかりになるファイル名の本体だけにする。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path)
    if stem:
        return f"録画を停止しました。ファイル {stem}"
    return "録画を停止しました"


def replay_saved_speech(path: str = "") -> str:
    """リプレイ保存の読み上げ文。

    ★「保存を要求できた」ではなく「保存された」ときに読む。OBSの保存は
    非同期なので、要求が通った時点で言うと嘘になり得る。
    """
    from .props import file_stem  # 循環参照を避けるため関数内 import

    stem = file_stem(path)
    if stem:
        return f"リプレイを保存しました。ファイル {stem}"
    return "リプレイを保存しました"


def pause_reminder_speech(elapsed_sec: float) -> str:
    """一時停止を放置していることを知らせる文。

    「まだ止まっている」ことと、経過時間を伝える。再開の手段も添える
    （そのために押すキーを思い出せないと意味がないため）。
    """
    return (f"録画は一時停止のままです。{fmt_seconds(elapsed_sec)}経過しました。"
            "再開するには Ctrl+P を押してください")


def disk_warning_speech(level: int, free_mb: float) -> str:
    """空き容量の警告文。level は recording の DISK_WARN / DISK_CRITICAL。

    危険域では「どうすればよいか」まで言う。容量切れで録画が止まると、
    目で気づけない利用者は録れていないことに最後まで気づけないため。
    """
    from .recording import DISK_CRITICAL  # 循環参照を避けるため関数内 import

    free = _fmt_disk(free_mb) if isinstance(free_mb, (int, float)) else "不明"
    if level == DISK_CRITICAL:
        return (f"録画の保存先の空き容量がわずかです。残り {free}。"
                "録画を止めるか、ファイルを移してください")
    return f"録画の保存先の空き容量が少なくなっています。残り {free}"


def chapter_added_speech(index: int, timecode: str) -> str:
    """チャプターを打ったときの読み上げ文。"""
    return f"チャプター{int(index)} を付けました、{timecode_to_speech(timecode)}"


# 録画フォーマットの識別子 → 読み上げ用の名前。無いものは識別子のまま読む。
_REC_FORMAT_JP = {
    "mp4": "MP4",
    "hybrid_mp4": "ハイブリッドMP4",
    "fragmented_mp4": "フラグメントMP4",
    "mov": "MOV",
    "hybrid_mov": "ハイブリッドMOV",
    "fragmented_mov": "フラグメントMOV",
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
    "x264": "x264 CPUで処理",
    "obs_x264": "x264 CPUで処理",
    "nvenc": "NVENC GPUで処理",
    "jim_nvenc": "NVENC GPUで処理",
    "obs_nvenc_h264_tex": "NVENC GPUで処理",
    "jim_hevc_nvenc": "NVENC HEVC GPUで処理",
    "amd": "AMD GPUで処理",
    "qsv": "クイックシンク GPUで処理",
    "obs_qsv11": "クイックシンク GPUで処理",
    "none": "配信と同じ設定",
}

# 簡易出力の録画品質。
_REC_QUALITY_JP = {
    "Stream": "配信と同じ品質",
    "Small": "高品質 ファイル小",
    "HQ": "高品質 ファイル中",
    "Lossless": "無劣化 ファイル特大",
}


def rec_format_jp(value: str) -> str:
    """録画フォーマットの識別子を読み上げ用の名前にする。"""
    key = str(value or "").strip().lower()
    return _REC_FORMAT_JP.get(key, value or "不明")


def record_settings_summary(settings: dict) -> str:
    """録画設定の読み上げ文。

    OBS本体の[設定→出力]にはスクリーンリーダーで読めない領域があるため、
    ここが録画設定を確かめる唯一の手段になる。取れなかった項目は黙って
    落とす（「不明」を並べても判断材料にならないため）。
    """
    if not settings:
        return "録画設定を取得できませんでした"
    parts: list[str] = []
    directory = settings.get("directory")
    if directory:
        parts.append(f"保存先 {path_speech(directory)}")
    fmt = settings.get("format")
    if fmt:
        parts.append(f"フォーマット {rec_format_jp(fmt)}")
    quality = settings.get("quality")
    if quality:
        parts.append(f"品質 {_REC_QUALITY_JP.get(str(quality), quality)}")
    encoder = settings.get("encoder")
    if encoder:
        parts.append(
            f"エンコーダー {_REC_ENCODER_JP.get(str(encoder), encoder)}")
    tracks = settings.get("tracks")
    if tracks:
        # ★RecTracks はビットの合計（トラック1〜4なら 15）。そのまま読むと
        #   「音声トラック 15」と聞こえるので、トラックの番号へ直す
        from .tracks import mask_to_tracks, track_list_text
        states = mask_to_tracks(tracks)
        text = track_list_text(states) if states is not None else ""
        parts.append(f"録画する音声 {text}" if text
                     else f"音声トラック {tracks}")
    disk = settings.get("disk_free_mb")
    if isinstance(disk, (int, float)):
        parts.append(f"空き容量 {_fmt_disk(disk)}")
    if not parts:
        return "録画設定を取得できませんでした"
    # チャプターの可否は、この設定から分かる中でいちばん見落としやすい
    if fmt:
        parts.append(chapter_status_speech(fmt, settings.get("output_kind", "")))
    return "録画設定。" + "、".join(parts)


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
        return "このフォーマットではチャプターは使えません"
    if output_kind and not output_supports_chapters(output_kind):
        return "チャプターはOBSを再起動すると使えます"
    return "チャプターが使えます"


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
            return (f"録画フォーマットは {rec_format_jp(rec_format)} に"
                    "なっていますが、OBSにまだ反映されていません。"
                    "OBSを再起動すると使えるようになります")
        # 設定も実態も対応しているのに拒否された。原因が分からないので
        # 決めつけず、確かめられることだけ言う
        return ("チャプターを付けられませんでした。"
                "録画が始まっているか確かめてください")
    now = f"今は {rec_format_jp(rec_format)} です。" if rec_format else ""
    return ("チャプターは録画フォーマットがハイブリッドMP4か"
            "ハイブリッドMOVのときだけ使えます。"
            f"{now}OBSの設定、出力、録画フォーマットで変えてください")


def chapter_not_recording_speech() -> str:
    """録画していないときにチャプターを打とうとしたときの案内文。"""
    return "録画していないので、チャプターは付けられません"


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
        return "なし" if not text or text == SIDECHAIN_NONE else text
    if spec.type == "bool":
        return "オン" if bool(raw) else "オフ"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if spec.unit == "デシベル":
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
    return (f"{filter_name} の {spec.label} を "
            f"{fmt_filter_value(spec, raw)} にしました")


def filter_prop_unchanged_speech(filter_name: str, spec) -> str:
    """投げたのに値が変わらなかったときの警告文。

    フィルターには設定変更のイベントが無く、読み直しでしか確かめられない。
    ずれていたら黙らずに言う（変わったつもりで変わっていないのが一番困る）。
    """
    return (f"{filter_name} の {spec.label} は変わりませんでした。"
            "OBSが受け付けていません")


def filter_no_props_speech(filter_name: str, known: bool) -> str:
    """設定項目が無いフィルターを開いたときの案内文。

    「このアプリでは変えられない」のか「そもそも設定が無い」のかを
    言い分ける。前者なら OBS 本体で触る手が残っているため。
    """
    if known:
        return f"{filter_name} に変えられる設定はありません。オン・オフだけです"
    return (f"{filter_name} の設定は、このアプリでは変えられません。"
            "OBSの画面で変更してください")


def filter_added_speech(filter_name: str, source: str) -> str:
    """フィルターを追加したときの読み上げ文。"""
    return f"{source} に {filter_name} を追加しました"


def filter_removed_speech(filter_name: str, source: str) -> str:
    """フィルターを削除したときの読み上げ文。"""
    return f"{source} から {filter_name} を削除しました"


def filter_kind_row(info) -> str:
    """追加できるフィルター1件の読み上げ行（名前と、何のためのものか）。

    種別の名前だけでは何をするものか分からないので、一言添える。
    フィルターを初めて入れる人が選べることを優先する。
    """
    return f"{info.label}、{info.hint}" if info.hint else info.label


def filter_none_speech(source: str) -> str:
    """フィルターが1つも無いときの案内文。"""
    return (f"{source} にフィルターはありません。"
            "フィルターを追加のボタンで足せます")


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
    if state.device and state.device != "未設定":
        head += f"、{state.device}"
    if state.state == STATE_OFF:
        body = "止まっています。カメラは使われていません"
    elif state.state == STATE_ON:
        body = "動いています。映像が来ています"
    elif state.state == STATE_ON_NO_SIGNAL:
        body = "動いていますが、映像は来ていません"
    else:
        body = "状態が分かりません"
    text = f"{head}、{body}"
    # 表示・非表示は別の話。動いていても非表示なら配信には出ない
    if state.visible is False:
        text += "。シーンでは非表示です"
    return text


def camera_list_speech(states, unused=None) -> str:
    """カメラ全体の状態をまとめて読む（確認用）。

    つないであるのにOBSで使っていない機材も知らせる。
    「ウェブカメラをつないだのに出てこない」に自力で気づけるようにする。
    """
    items = list(states or [])
    parts: list[str] = []
    if not items:
        parts.append("OBSに映像キャプチャデバイスのソースがありません")
    else:
        parts.append(f"カメラ {len(items)} 件")
        parts.extend(camera_state_speech(s) for s in items)
    spare = list(unused or [])
    if spare:
        parts.append(
            "使っていない機材: " + "、".join(spare)
            + "。OBSでソースを作ると使えます")
    return "。".join(parts)


def camera_toggle_intent_speech(name: str, turning_on: bool) -> str:
    """カメラの切り替えを始めたときの読み上げ文。

    切り替えは1〜2秒かかる（実測）。その間に何も言わないと、キーが
    効いたのかどうか分からないので、先に何をするかだけ伝える。
    結果は必ず camera_toggle_result_speech で確かめてから言う。
    """
    return f"{name} を動かします" if turning_on else f"{name} を止めます"


def camera_toggle_result_speech(state, expected_active: bool) -> str:
    """切り替えたあと、実際の状態を確かめて読む文。

    ★期待どおりにならなかったら、はっきり言う。カメラが止まったと
    思い込ませるのが一番危ない。
    """
    if state is None:
        return "カメラの状態を確認できませんでした"
    if state.active != expected_active:
        if expected_active:
            return f"{state.name} を動かせませんでした"
        return (f"{state.name} を止められませんでした。"
                "カメラはまだ動いています")
    return camera_state_speech(state)


# ------------------------------------------------------------
# ソースの作成・削除
# ------------------------------------------------------------
def source_kind_row(info) -> str:
    """作れるソース1件の読み上げ行（名前と、何のためのものか）。

    種別の名前だけでは何をするものか分からないので一言添える。
    フィルターの追加一覧と同じ考え方。
    """
    return f"{info.label}、{info.hint}" if info.hint else info.label


def source_created_speech(name: str, info, scene: str) -> str:
    """ソースを作ったときの読み上げ文。

    ★作っただけでは使えない種類が多い（カメラは機材を、ウィンドウ
    キャプチャは対象を選ばないと何も映らない）。作れたことだけ伝えて
    放すと「足したのに使えない」で止まるので、次に何をするかまで言う。
    """
    head = f"{scene} に {name} を作りました"
    if getattr(info, "needs", ""):
        return f"{head}。続けて設定を開きます"
    return head


def source_remove_warning(name: str, roles=None) -> str:
    """ソースを削除する前の確認文。

    ★入力の削除は「このシーンから外す」ではなく**すべてのシーンから
    消える**。設定も失われて元に戻せない。目で確かめられない以上、
    何が起きるかを言葉で全部書く。
    設定で使っているソース（BGM、ゲーム切り替えなど）ならそれも言う。
    """
    parts = [f"ソース「{name}」を削除しますか？",
             "すべてのシーンから消えて、設定も元に戻せません。"]
    used = list(roles or [])
    if used:
        parts.append(
            "このソースは " + "、".join(used) + " に使っています。"
            "削除するとその機能が動かなくなります。")
    return "\n".join(parts)


def source_removed_speech(name: str) -> str:
    """ソースを削除したときの読み上げ文。"""
    return f"{name} を削除しました"


# ------------------------------------------------------------
# シーン
# ------------------------------------------------------------
def scene_created_speech(name: str) -> str:
    """シーンを作ったときの読み上げ文。

    ★作っても現在のシーンは変わらない（実測）。切り替わったと誤解すると
    「配信の画面が変わった」と思わせるので、変わらないことを明言する。
    作った直後は空なので、次にやることも言う。
    """
    return (f"シーン {name} を作りました。今の画面は変わっていません。"
            "続けて設定を開きます。ソースを追加できます")


def scene_renamed_speech(old: str, new: str) -> str:
    """シーンの名前を変えたときの読み上げ文。"""
    return f"シーン {old} を {new} に変えました"


def scene_remove_warning(name: str, is_current: bool = False) -> str:
    """シーンを削除する前の確認文。

    ★何が失われるかを言葉で全部書く。目で確かめられない以上、
    「消したらどうなるか」を read しか判断材料が無い。
    そのシーンにしか無いソースは一緒に消えるが、他のシーンにも置いて
    あるソースは残る（実測で確認）。
    """
    parts = [f"シーン「{name}」を削除しますか？",
             "このシーンにしか無いソースも一緒に消えます。",
             "他のシーンにも置いてあるソースは残ります。",
             "元に戻せません。"]
    if is_current:
        parts.insert(1, "★これは今映しているシーンです。"
                        "削除すると別のシーンに切り替わります。")
    return "\n".join(parts)


def scene_removed_speech(name: str) -> str:
    """シーンを削除したときの読み上げ文。"""
    return f"シーン {name} を削除しました"


def scene_transition_row(current, transitions=None) -> str:
    """シーン設定の「トランジション」行。

    設定していなければ、全体の設定に従うことが分かるように読む
    （「未設定」だと、切り替え効果が無いのか設定が無いのか分からない）。
    """
    if not current.overridden:
        return prop_row_label("切り替え効果", "全体の設定に従う")
    return prop_row_label("切り替え効果", current.name)


def scene_duration_row(current) -> str:
    """シーン設定の「切り替えの長さ」行。"""
    ms = current.duration_ms
    if not isinstance(ms, (int, float)):
        return prop_row_label("切り替えの長さ", "既定")
    return prop_row_label("切り替えの長さ", f"{int(ms)}ミリ秒")


def scene_transition_changed_speech(scene: str, current) -> str:
    """シーンのトランジションを変えたときの読み上げ文。"""
    if not current.overridden:
        return f"{scene} の切り替え効果を全体の設定に戻しました"
    return f"{scene} の切り替え効果を {current.name} にしました"


def scene_source_added_speech(scene: str, source: str) -> str:
    """既存ソースをシーンに追加したときの読み上げ文。

    ★コピーではなく共有であることを伝える。片方で設定を変えると
    両方に効くので、知らないと戸惑う。
    """
    return (f"{scene} に {source} を追加しました。"
            "同じソースを共有するので、設定を変えると両方に効きます")


def scene_no_addable_speech(scene: str) -> str:
    """追加できるソースが無いときの案内文。"""
    return (f"{scene} に追加できるソースがありません。"
            "すべてこのシーンに置いてあります")


def camera_none_speech() -> str:
    """カメラのソースが無いときの案内文。"""
    return ("映像キャプチャデバイスのソースがありません。"
            "OBSでウェブカメラやキャプチャーボードのソースを作ってください")


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
    return ("著作権 Takahashi。"
            "このソフトは GNU GPL 第3版のもとで配布しています。"
            "同じライセンスのもとで、改変や再配布ができます。"
            "無保証です。"
            "ライセンスの全文は、同梱の LICENSE.txt にあります")


def ai_notice_speech() -> str:
    """「OBSナビについて」で読む、AI を使って作ったことの告知。

    ★README・マニュアルの「AI を使って作ったこと」と同じ趣旨を短く言う。
    ★末尾に句点を付けない。呼ぶ側（on_about）が「。」で文を連ねる。
    """
    return ("このソフトは、AI（Anthropic の Claude）を使って作りました。"
            "何を作るかと読み上げでの使いやすさは作者が決め、"
            "スクリーンリーダーで使って確かめています")


# ------------------------------------------------------------
# 録画の音声トラック割り当て（core/tracks.py）
# ------------------------------------------------------------
def input_track_row(number: int, on: bool) -> str:
    """ソースの設定画面の行（「録画のトラック2、オン」）。

    ★1行1トラックにして、Enter で入り切りする（オン・オフの設定と同じ
    操作）。チェックボックスの並んだ表は VoiceOver で扱いにくいため。
    """
    return f"録画のトラック{number}、{'オン' if on else 'オフ'}"


def input_tracks_changed_speech(name: str, number: int, on: bool,
                                states) -> str:
    """ソースのトラックを切り替えたときの読み上げ文（今の全体も言う）。"""
    from .tracks import track_list_text
    head = (f"{name} をトラック{number}に出しました" if on
            else f"{name} をトラック{number}から外しました")
    now = track_list_text(states)
    tail = f"今は{now}" if now else "今はどのトラックにも出していません"
    return f"{head}。{tail}"


def input_tracks_unchanged_speech(name: str) -> str:
    """切り替えを投げたのに読み直すと変わっていなかったとき。"""
    return f"{name} のトラックは変わりませんでした。OBSが受け付けていません"


def record_track_row(number: int, on: bool) -> str:
    """録画のトラック設定の画面の行（「トラック1を録画する、オン」）。"""
    return f"トラック{number}を録画する、{'オン' if on else 'オフ'}"


def record_tracks_changed_speech(states) -> str:
    """録画するトラックを変えたときの読み上げ文。"""
    from .tracks import track_list_text
    now = track_list_text(states)
    if not now:
        return ("録画するトラックがありません。"
                "このままだと音の無い録画になります")
    return f"録画する音声を{now}にしました。次の録画から効きます"


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
        parts.append("録画するトラックを読めませんでした")
    else:
        text = track_list_text(recorded)
        parts.append(f"録画する音声は{text}" if text
                     else "録画するトラックがありません")
    for name, states in (input_tracks or {}).items():
        text = track_list_text(states)
        parts.append(f"{name} は{text}" if text
                     else f"{name} はどのトラックにも出していません")
    if not input_tracks:
        parts.append("音声を持つソースがありません")
    if recorded is not None and input_tracks:
        missing = unrecorded_inputs(input_tracks, recorded)
        if missing:
            parts.append("次のソースは録画に入りません。"
                         + "、".join(missing))
    if note:
        parts.append(note)
    return "。".join(parts)


def tracks_recommendation_speech() -> str:
    """作曲の配信・録画で勧める割り当ての案内。"""
    from .tracks import RECOMMENDED
    rows = [f"{label} はトラック" + "と".join(str(n) for n in nums)
            for label, nums in RECOMMENDED]
    return ("おすすめの割り当て。" + "、".join(rows)
            + "。トラック1は全部入りで、配信と同じ音になります")
