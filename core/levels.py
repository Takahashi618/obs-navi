# -*- coding: utf-8 -*-
"""音量レベル監視の純ロジック（表示・音声・OSに依存しない）。

obs-websocket の InputVolumeMeters イベントから抽出したピーク値(dB)を
update() に流し込むと、通知すべき警告のリストを返す。

- 無音警告: 監視が有効（配信中または録画中）で、しきい値未満の状態が
  一定秒数続いたとき。一度警告したら、音が戻るまで再警告しない
  （クールダウンも併用）。
- クリップ警告: ピークがしきい値以上になったとき。入力ごとに
  クールダウンあり。
- ミュート中の入力は「意図した無音」なので警告しない。

レベル読み上げ(F6)用の current_peaks は「直近 hold_seconds 秒の最大」を返す。
声のように途切れる音では、キーを押した瞬間がたまたま息継ぎだと瞬間値では
「無音」になってしまい、知りたいこと（今ちゃんと乗っているか）に答えられない
ため。警告の判定は update に渡された瞬間値をそのまま使うので、ここは
読み上げにしか影響しない。
"""
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field

SILENCE_FLOOR_DB = -120.0


def mul_to_db(mul: float) -> float:
    """OBSのレベル（倍率 0..1）を dB に変換する。"""
    if mul <= 0.0:
        return SILENCE_FLOOR_DB
    db = 20.0 * math.log10(mul)
    return max(db, SILENCE_FLOOR_DB)


def peak_db_from_levels(levels_mul: list) -> float:
    """inputLevelsMul から代表ピーク(dB)を求める。

    levels_mul はチャンネルごとの [magnitude, peak, input_peak]（倍率）。
    全チャンネルの peak（無ければ magnitude）の最大値を使う。
    """
    peak = 0.0
    for ch in levels_mul or []:
        try:
            value = ch[1] if len(ch) > 1 else ch[0]
        except (TypeError, IndexError):
            continue
        if isinstance(value, (int, float)) and value > peak:
            peak = float(value)
    return mul_to_db(peak)


@dataclass
class LevelWarning:
    """読み上げるべき警告。"""

    kind: str          # "silence" または "clip"
    input_name: str
    message: str


@dataclass
class _InputState:
    last_peak_db: float = SILENCE_FLOOR_DB
    silence_since: float | None = None
    silence_warned: bool = False
    last_clip_warn_at: float | None = None
    last_silence_warn_at: float | None = None
    # 読み上げ用のピーク保持窓。(時刻, ピークdB) を hold_seconds ぶんだけ持つ
    peak_history: deque = field(default_factory=deque)


class LevelMonitor:
    """入力ごとのピークを追跡し、無音・クリップ警告を判定する。

    時刻は必ず呼び出し側から now（time.monotonic 相当）で渡す。
    これによりテストで時間を自由に進められる。

    スレッド安全性: update() は obsws-python の wsスレッドから高頻度
    （~50ms）で呼ばれ、current_peaks() / set_active() / forget_missing() は
    UIスレッドから呼ばれる。両者は同じ _inputs とその中の保持窓に触るので、
    公開メソッドはロックで包む。包まないと、F6（current_peaks）の最中に
    wsスレッドが入力を足したり保持窓を削ったりして
    「dictionary changed size during iteration」
    「deque mutated during iteration」で落ちる。
    ロックは競合しなければほぼ無コストで、呼び出しの中で外部を呼ばないので
    デッドロックの心配もない。
    """

    def __init__(
        self,
        silence_threshold_db: float = -50.0,
        silence_seconds: float = 60.0,
        clip_threshold_db: float = -0.5,
        cooldown_seconds: float = 30.0,
        hold_seconds: float = 3.0,
    ) -> None:
        self.silence_threshold_db = silence_threshold_db
        self.silence_seconds = silence_seconds
        self.clip_threshold_db = clip_threshold_db
        self.cooldown_seconds = cooldown_seconds
        # current_peaks が遡る秒数。0以下なら瞬間値をそのまま返す
        self.hold_seconds = hold_seconds
        self.active = False  # 配信中または録画中のときだけ警告を出す
        self._inputs: dict[str, _InputState] = {}
        self._lock = threading.Lock()

    def set_active(self, active: bool, now: float) -> None:
        """監視の有効・無効を切り替える（配信/録画状態に連動させる）。"""
        with self._lock:
            if active == self.active:
                return
            self.active = active
            # 状態が変わったら無音タイマーを仕切り直す
            for st in self._inputs.values():
                st.silence_since = now
                st.silence_warned = False

    def current_peaks(self, now: float | None = None) -> dict[str, float]:
        """レベル読み上げ用のピーク(dB)を入力名ごとに返す。

        hold_seconds > 0 なら「直近 hold_seconds 秒の最大」を返す。声のように
        途切れる音でも、F6を押した瞬間がたまたま無音でも直前のレベルを読める。
        hold_seconds <= 0 なら瞬間値（直近のメーター1件）を返す。

        now を渡すと、その時刻から hold_seconds 以内のものだけを見る。
        メーターが止まっているのに古い値を読んでしまうのを防ぐため、
        呼び出し側は now を渡すのが望ましい。
        """
        result: dict[str, float] = {}
        with self._lock:
            for name, st in self._inputs.items():
                if self.hold_seconds <= 0 or not st.peak_history:
                    result[name] = st.last_peak_db
                    continue
                if now is None:
                    samples = [p for _, p in st.peak_history]
                else:
                    cutoff = now - self.hold_seconds
                    samples = [p for ts, p in st.peak_history if ts >= cutoff]
                # 窓の中に1件も無い = しばらくメーターが来ていない → 無音扱い
                result[name] = max(samples) if samples else SILENCE_FLOOR_DB
        return result

    def forget_missing(self, present: set[str]) -> None:
        """存在しなくなった入力の追跡をやめる。"""
        with self._lock:
            for name in list(self._inputs):
                if name not in present:
                    del self._inputs[name]

    def update(
        self,
        input_name: str,
        peak_db: float,
        now: float,
        muted: bool = False,
        suppress_warnings: bool = False,
    ) -> list[LevelWarning]:
        """ピーク値を1件反映し、必要な警告を返す。

        suppress_warnings=True のときはピーク値は記録するが警告は出さない。
        スクリーンリーダー音声のように、無音が正常で無音警告が邪魔になる
        入力に使う（レベル読み上げ用にピークは追跡し続ける）。
        """
        with self._lock:
            return self._update_locked(
                input_name, peak_db, now, muted, suppress_warnings)

    def _update_locked(
        self,
        input_name: str,
        peak_db: float,
        now: float,
        muted: bool,
        suppress_warnings: bool,
    ) -> list[LevelWarning]:
        """update の本体。ロックを持った状態で呼ぶこと。"""
        st = self._inputs.get(input_name)
        if st is None:
            st = _InputState(silence_since=now)
            self._inputs[input_name] = st
        st.last_peak_db = peak_db
        # 読み上げ用のピーク保持窓を更新する（警告の判定には使わない）。
        # 抑止中(suppress_warnings)やミュート中でも記録は続ける。F6で
        # 「乗っているか」を確かめられるようにするのがこの窓の目的なので。
        if self.hold_seconds > 0:
            st.peak_history.append((now, peak_db))
            cutoff = now - self.hold_seconds
            while st.peak_history and st.peak_history[0][0] < cutoff:
                st.peak_history.popleft()

        if muted or suppress_warnings:
            # 意図した無音、または警告対象外。タイマーを進めず警告も出さない。
            st.silence_since = now
            st.silence_warned = False
            return []

        warnings: list[LevelWarning] = []

        # クリップ判定（監視有効時のみ・クールダウンあり）
        if self.active and peak_db >= self.clip_threshold_db:
            last = st.last_clip_warn_at
            if last is None or (now - last) >= self.cooldown_seconds:
                st.last_clip_warn_at = now
                warnings.append(LevelWarning(
                    kind="clip",
                    input_name=input_name,
                    message=f"{input_name} が音割れしています",
                ))

        # 無音判定
        if peak_db > self.silence_threshold_db:
            st.silence_since = now
            st.silence_warned = False
        else:
            if st.silence_since is None:
                st.silence_since = now
            duration = now - st.silence_since
            if (
                self.active
                and not st.silence_warned
                and duration >= self.silence_seconds
            ):
                last = st.last_silence_warn_at
                if last is None or (now - last) >= self.cooldown_seconds:
                    st.silence_warned = True
                    st.last_silence_warn_at = now
                    secs = int(self.silence_seconds)
                    warnings.append(LevelWarning(
                        kind="silence",
                        input_name=input_name,
                        message=f"{input_name} が{secs}秒以上無音です",
                    ))
        return warnings
