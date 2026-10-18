# -*- coding: utf-8 -*-
"""録画まわりの純ロジック（wx・obsws非依存）。

扱うのは4つ。いずれも「目でOBSの画面を確認できない」ことから来る
見落としを、読み上げで拾えるようにするためのもの。

1. PauseReminder — 一時停止したまま忘れるのを防ぐ
   OBSの一時停止は画面を見れば分かるが、読み上げには出ない。忘れると
   その間のプレイが丸ごと録れていない事故になる。放置を定期的に知らせる。
2. DiskWatch — 録画中の空き容量を見張る
   obs-websocket に残量のイベントは無いので、呼び出し側が定期的に
   check() へ流す。段階が上がったときだけ知らせ、同じ段階では黙る。
3. チャプター名の生成
4. 録画設定の在りか（プロファイル設定のセクションとキー）の解決

読み上げ文は作らない。ここは「何が起きたか」を返すだけで、日本語への
変換は speech_format 側で行う（video.py と同じ流儀）。
"""
from __future__ import annotations

# 出力モードごとの、録画設定が入っているプロファイルのセクション名。
# OBSの[設定→出力]の「出力モード」が簡易(Simple)か詳細(Advanced)かで
# 同じ意味の設定が別のセクション・別のキー名になる。
SECTION_SIMPLE = "SimpleOutput"
SECTION_ADVANCED = "AdvOut"

# 録画フォーマットの識別子。チャプターに対応するのはハイブリッド形式だけ。
# ★実測（2026-08-27、OBS 32.2.2）: プレーンMP4で CreateRecordChapter を
#   投げると 702「Verify that the output being used supports chapter markers」
#   で拒否される。対応するのは OBS本体のメニューにあるとおり
#   "Add Chapter Marker (Hybrid MP4/MOV only)" の2つ。
#   識別子は obs64.exe から実測して確認した（hybrid_mp4 / hybrid_mov）。
FORMAT_HYBRID_MP4 = "hybrid_mp4"
FORMAT_HYBRID_MOV = "hybrid_mov"
CHAPTER_FORMATS = frozenset({FORMAT_HYBRID_MP4, FORMAT_HYBRID_MOV})

# ★★設定を変えても、起動中のOBSは録画の出力オブジェクトを作り直さない
#   （2026-08-27 に実測。SetProfileParameter で RecFormat2 を hybrid_mp4 に
#    してもログは 'ffmpeg muxer' のままで、チャプターは 702 で拒否された）。
#   つまり「設定のフォーマット」と「今まさに使われている出力」はずれ得る。
#   設定だけ見て「チャプターが使えます」と読み上げると嘘になるので、
#   実態は出力の種別（GetOutputList の outputKind）で判定する。
#   識別子は OBS のバイナリから実測: ハイブリッド形式は obs-outputs.dll の
#   mp4_output / mov_output、従来形式は obs-ffmpeg.dll の ffmpeg_muxer。
OUTPUT_FFMPEG_MUXER = "ffmpeg_muxer"
CHAPTER_OUTPUT_KINDS = frozenset({"mp4_output", "mov_output"})
RECORD_OUTPUT_KINDS = frozenset(
    {OUTPUT_FFMPEG_MUXER}) | CHAPTER_OUTPUT_KINDS
# OBSが録画出力に付ける名前（簡易出力・詳細出力）。
RECORD_OUTPUT_NAMES = ("simple_file_output", "adv_file_output")


def output_supports_chapters(output_kind: str) -> bool:
    """今使われている出力でチャプターを打てるか。

    設定のフォーマット（supports_chapters）ではなく、実際に動いている
    出力の種別で見る。両者がずれるのは「設定を変えたがOBSを再起動して
    いない」ときで、そのときこそ正しく伝える必要がある。
    """
    return str(output_kind or "").strip().lower() in CHAPTER_OUTPUT_KINDS


def pick_record_output(outputs) -> dict | None:
    """出力一覧から録画に使われているものを選ぶ。無ければ None。

    名前での照合を先にする（OBSが付ける名前は決まっているため）。
    名前が変わっていた場合の保険として、録画に使われる種別からも探す。
    配信・仮想カメラ・リプレイバッファを掴まないことが肝。
    """
    real = [o for o in outputs or [] if isinstance(o, dict)]
    for name in RECORD_OUTPUT_NAMES:
        for item in real:
            if item.get("outputName") == name:
                return item
    for item in real:
        kind = str(item.get("outputKind", "") or "").strip().lower()
        if kind in RECORD_OUTPUT_KINDS:
            return item
    return None

# 空き容量の段階
DISK_OK = 0
DISK_WARN = 1
DISK_CRITICAL = 2

# 一度警告した段階を解除する余裕。しきい値ちょうどで行き来したときに
# 警告が何度も鳴るのを防ぐ（ファイルを消して容量が戻ったときは鳴らせる）。
DISK_REARM_RATIO = 1.15


def output_section(mode: str) -> str:
    """出力モードから、録画設定が入っているセクション名を返す。

    OBSの [Output] Mode は "Simple" か "Advanced"。未知の値は簡易扱いに
    する（この環境の既定が簡易で、外すなら安全側に倒したいため）。
    """
    return (SECTION_ADVANCED
            if str(mode or "").strip().lower().startswith("adv")
            else SECTION_SIMPLE)


def record_path_key(section: str) -> str:
    """録画の保存先が入っているキー名（セクションで違う）。

    実測: 簡易出力は FilePath、詳細出力は RecFilePath。
    ※通常の保存先の取得には GetRecordDirectory を使えばよく、これは
      設定を一覧で読むときの補助。
    """
    return "RecFilePath" if section == SECTION_ADVANCED else "FilePath"


def supports_chapters(rec_format: str) -> bool:
    """この録画フォーマットでチャプターを打てるか。"""
    return str(rec_format or "").strip().lower() in CHAPTER_FORMATS


def chapter_name(index: int, timecode: str) -> str:
    """自動で付けるチャプター名。

    プレイヤーや編集ソフトが並べて表示するので、番号を先頭に置いて
    ゼロ詰めする（文字列で並べ替えても順番が崩れない）。日本語を入れると
    読めないソフトがあるため、数字と時刻だけにしてある。
    """
    tc = str(timecode or "").split(".")[0].strip()
    return f"{int(index):02d} {tc}" if tc else f"{int(index):02d}"


class PauseReminder:
    """録画を一時停止したまま忘れていないか見張る。

    時刻は必ず呼び出し側から now（time.monotonic 相当）で渡す。
    LevelMonitor と同じ流儀で、テストから時間を自由に進められるようにする。

    一時停止した瞬間そのものは、OBSのイベントを受けた側が読み上げるので
    ここでは知らせない（二重に読まない）。その時刻を起点に、interval_seconds
    ごとに「まだ止まっている」ことを知らせる。
    """

    def __init__(self, interval_seconds: float = 300.0) -> None:
        # 0以下なら知らせない（設定で切れるようにするため）
        self.interval_seconds = interval_seconds
        self._since: float | None = None
        self._last_notified_at: float | None = None

    @property
    def paused(self) -> bool:
        """今、一時停止を追跡中か。"""
        return self._since is not None

    def set_paused(self, paused: bool, now: float) -> None:
        """一時停止状態が変わったことを伝える。

        同じ状態で繰り返し呼んでも起点は動かない（イベントとスナップショットの
        両方から呼ばれるため、冪等にしておく必要がある）。
        """
        if paused:
            if self._since is None:
                self._since = now
                # 一時停止した瞬間はイベント側が読んでいるので、
                # そこを「直近で知らせた時刻」として数え始める
                self._last_notified_at = now
        else:
            self.reset()

    def reset(self) -> None:
        """追跡をやめる（録画停止・再開時）。"""
        self._since = None
        self._last_notified_at = None

    def tick(self, now: float) -> float | None:
        """定期呼び出し。知らせるべきなら一時停止からの経過秒を返す。

        知らせなくてよければ None。返した時点で「知らせた」ことにするので、
        呼び出し側は返り値を必ず読み上げること。
        """
        if self._since is None or self.interval_seconds <= 0:
            return None
        last = self._last_notified_at
        if last is None:
            last = self._since
        if (now - last) < self.interval_seconds:
            return None
        self._last_notified_at = now
        return now - self._since


class DiskWatch:
    """録画中の空き容量を見張る。

    段階は「警告」と「危険」の2つ。段階が上がったときだけ知らせ、
    同じ段階に留まっている間は黙る（うるさくしない原則）。
    容量が戻ったら（録画を止めた、ファイルを消した）また知らせられる
    ようにするが、しきい値ちょうどで行き来して鳴り続けないよう
    戻りには余裕（DISK_REARM_RATIO）を見る。
    """

    def __init__(
        self, warn_mb: float = 10240.0, critical_mb: float = 2048.0
    ) -> None:
        self.warn_mb = warn_mb
        self.critical_mb = critical_mb
        self._announced = DISK_OK

    def reset(self) -> None:
        """録画が終わったときなどに、警告済みの記録を消す。"""
        self._announced = DISK_OK

    def _level_for(self, free_mb: float) -> int:
        """今の残量が属する段階。"""
        if self.critical_mb > 0 and free_mb <= self.critical_mb:
            return DISK_CRITICAL
        if self.warn_mb > 0 and free_mb <= self.warn_mb:
            return DISK_WARN
        return DISK_OK

    def _threshold_for(self, level: int) -> float:
        return self.critical_mb if level == DISK_CRITICAL else self.warn_mb

    def check(self, free_mb: float) -> int:
        """残量を1件反映し、知らせるべき段階を返す。黙ってよければ DISK_OK。

        free_mb はメガバイト（OBSの GetStats の availableDiskSpace と同じ単位）。
        """
        try:
            free = float(free_mb)
        except (TypeError, ValueError):
            return DISK_OK
        level = self._level_for(free)
        if level > self._announced:
            self._announced = level
            return level
        if level < self._announced:
            # 段階が下がった＝容量が戻った。境界付近で往復して鳴り続けない
            # よう、しきい値を十分に上回ってから警告を張り直す
            if free >= self._threshold_for(self._announced) * DISK_REARM_RATIO:
                self._announced = level
        return DISK_OK
