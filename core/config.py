# -*- coding: utf-8 -*-
"""設定の読み書きと、OBS側WebSocket設定の自動取得。

パスワードは OBS 本体の obs-websocket 設定ファイルから自動取得できる
（auto_password=True のとき）。手入力の手間とコピー操作を無くすため。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_FILENAME = "obs_navi_config.json"


def app_dir() -> Path:
    """設定ファイルを置く基準フォルダ。

    PyInstaller で固めたときは実行ファイルのあるフォルダを使う。
    固めた中身（_internal など）は書き込めない・更新で消えるうえ、
    onefile では起動ごとに作られる一時フォルダになるため、そこへ
    設定を書くと毎回失われてしまう。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    """obs_navi 自身の設定ファイルの既定パス。"""
    return app_dir() / CONFIG_FILENAME


def obs_websocket_config_path() -> Path:
    """OBS本体の obs-websocket 設定ファイルの場所（OS別）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", ""))
        return (base / "obs-studio" / "plugin_config"
                / "obs-websocket" / "config.json")
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support"
                / "obs-studio" / "plugin_config"
                / "obs-websocket" / "config.json")
    return (Path.home() / ".config" / "obs-studio" / "plugin_config"
            / "obs-websocket" / "config.json")


def _default_sr_sources() -> list:
    """sr_sources の既定値（正規化のフォールバックにも使う）。"""
    return [
        {"name": "NVDA音声", "method": "device",
         "device_match": "CABLE Output", "key": "F8"},
        {"name": "PC-Talker音声", "method": "app",
         "exe": "PCTalker.exe", "key": "F9"},
    ]


# record の数値項目の既定値（正規化のフォールバックに使う）
_RECORD_DEFAULTS = {
    "pause_reminder_seconds": 300.0,
    "disk_warn_mb": 10240.0,
    "disk_critical_mb": 2048.0,
    "disk_check_seconds": 60.0,
}


def _as_float(value, default: float) -> float:
    """設定値を float に寄せる。読めなければ既定値。

    手編集で "300" のような文字列や null が入っていても、タイマーの中で
    比較に失敗して落ちないようにするため。負の値は「無効」の意味に
    まとめて 0 にする（0 を無効として扱う項目しかないため）。
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result:  # NaN
        return default
    return max(result, 0.0)


def _clean_name_list(value) -> list:
    """並び順の設定を「重複の無い文字列のリスト」に寄せる。

    手編集で文字列1つだけ書かれることがあるので配列へ直す。読めない値は
    黙って落とす（並び順は落としても動きが壊れない＝落として続ける方が
    起動できないより良い）。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    seen: set = set()
    out: list = []
    for entry in value:
        if isinstance(entry, str) and entry and entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def _as_bool(value, default: bool = False) -> bool:
    """手編集で入った値を真偽値へ寄せる。

    ★bool() だけで済ませてはいけない。JSON に "false" と書かれると
    bool("false") は True になり、書いた本人の意図と逆に効く。
    数値の設定は _as_float で文字列を解釈しているのに、真偽値だけ
    素通しだった（レビューで判明）。読めない値は default に倒す。
    """
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("false", "0", "no", "off", ""):
            return False
        if text in ("true", "1", "yes", "on"):
            return True
        return default
    return bool(value)


def _rename_in_list(names, old: str, new: str):
    """名前のリストの中の old を new へ置き換える。(新しいリスト, 変えたか)。

    新しい名前が既にあるときは古い方を消すだけにする（重複を作らない）。
    """
    if not isinstance(names, list) or old not in names:
        return names, False
    if new in names:
        return [n for n in names if n != old], True
    return [new if n == old else n for n in names], True


@dataclass
class ObsWsInfo:
    """OBS側WebSocket設定の要約。"""

    enabled: bool
    port: int
    password: str


def read_obs_websocket_config(path: Path | None = None) -> ObsWsInfo | None:
    """OBS本体の設定からポートとパスワードを読む。読めなければ None。"""
    p = path if path is not None else obs_websocket_config_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        # 破損して null や配列になったファイル。raw.get で AttributeError に
        # なる前に止め、「読めなければ None」の契約を守る
        return None
    try:
        return ObsWsInfo(
            enabled=bool(raw.get("server_enabled", False)),
            port=int(raw.get("server_port", 4455)),
            password=str(raw.get("server_password", "")),
        )
    except (TypeError, ValueError):
        return None


@dataclass
class Config:
    """obs_navi の設定。"""

    host: str = "localhost"
    port: int = 4455
    password: str = ""            # 空なら OBS 設定からの自動取得に頼る
    auto_password: bool = True    # OBS設定ファイルからポート・パスワードを取る
    # スクリーンリーダーごとの音声入力。配信オン・オフを個別に管理する。
    # method で捕捉方式を分ける:
    #   "app"    アプリ音声キャプチャ。exe で対象実行ファイルを指定
    #            （可視ウィンドウを持つSR向け。例: PC-Talker）
    #   "device" デバイスキャプチャ。device_match で録音デバイス名を指定
    #            （ウィンドウを持たないSRを仮想ケーブル経由で拾う。例: NVDA）
    # key は F5/F6 が状態/レベル読み上げで予約済みのため F8 以降を使う。
    sr_sources: list = field(default_factory=_default_sr_sources)
    silence_threshold_db: float = -50.0
    silence_seconds: float = 60.0
    clip_threshold_db: float = -0.5
    warn_cooldown_seconds: float = 30.0
    monitor_enabled: bool = True
    # F6のレベル読み上げが遡る秒数。声のように途切れる音でも、押した瞬間が
    # たまたま息継ぎだったときに「無音」と読まれないよう、直近の最大を読む。
    # 0 にすると瞬間値（直近のメーター1件）をそのまま読む従来の挙動になる。
    level_hold_seconds: float = 3.0
    # 音量調整の刻み(dB)。音量は step のほうの格子に乗せて動かすので、
    # coarse は step の整数倍にしておくと値がきれいに揃う。
    volume_step_db: float = 1.0
    volume_coarse_step_db: float = 5.0
    # グローバルホットキー（ウィンドウ非アクティブでも効く）。
    # 素のファンクションキーを登録するとシステム全体で奪ってしまうため、
    # 必ず修飾キーを付ける（ゲームとの衝突を避ける）。空にすると無効扱い。
    #
    # 基準は Ctrl+Alt（0.6.0で Ctrl+Shift から変更）。
    # Ctrl+Shift+F1〜F12 は、同じPCで動かすほかの道具がグローバルキーに
    # 使うことがあり、衝突しやすい。Ctrl+Alt へ寄せておけば当たりにくい。
    # Ctrl+Alt / Ctrl+Alt+Shift とも F1〜F12 が全部空いていることを実測済み。
    global_hotkeys_enabled: bool = True
    global_hotkey_modifier: str = "Ctrl+Alt"
    # ゲーム切り替え（F3 / Ctrl+Alt+F3）。ソース名はハードコードせず設定で持つ。
    #   video_source   ゲーム映像のソース名（game_capture）
    #   audio_sources  一緒に切り替える音声ソース名（アプリ音声キャプチャ）
    #   also_audio     音声も一緒に切り替えるか
    #   raise_window   グローバルキーで呼んだときウィンドウを前面に出すか
    #                  （排他フルスクリーンのゲームだと最小化されることが
    #                    あるので切れるようにしてある）
    game_switch: dict = field(default_factory=lambda: {
        "video_source": "ゲームキャプチャ",
        "audio_sources": ["ゲーム音"],
        "also_audio": True,
        "raise_window": True,
    })
    # ローカル音楽ファイル再生用のメディアソース。
    # 既存の「BGM」（アプリ音声キャプチャ）とは別名にする。入力の種別は
    # 後から変更できないため、ファイル再生には別入力が要るため。
    bgm: dict = field(default_factory=lambda: {
        "source_name": "BGM音楽",
        "last_dir": "",
    })
    # 映像切り替え（重なり順で切り替える）。
    # extra_kinds に種別名を足すと切り替えの候補に含められる
    # （プラグイン製の映像ソースなど。既定は空）。
    video_switch: dict = field(default_factory=lambda: {
        "extra_kinds": [],
    })
    # 録画まわり。既定値は「まず使ってみて調整する」前提で入れてある。
    #   pause_reminder_seconds  一時停止を放置していることを知らせる間隔(秒)。
    #                           0 で知らせない。うるさければ伸ばす
    #   disk_warn_mb            空き容量の警告(MB)。既定10GB。0 で無効
    #   disk_critical_mb        強い警告(MB)。既定2GB。0 で無効
    #   disk_check_seconds      空き容量を見に行く間隔(秒)。0 で無効
    #   announce_file_name      録画停止・リプレイ保存でファイル名を読むか
    #   pause_hotkey            録画一時停止・再開のグローバルキー。
    #   chapter_hotkey          チャプターのグローバルキー。
    #     ※どちらも修飾キーは global_hotkey_modifier に1つ足したもの
    #       （基準 Ctrl+Alt なら Ctrl+Alt+Shift）。粗い音量刻みと同じ考え方で、
    #       hotkeys.coarse_modifier_tokens が決める。空文字にすると割り当てない
    record: dict = field(default_factory=lambda: {
        "pause_reminder_seconds": 300.0,
        "disk_warn_mb": 10240.0,
        "disk_critical_mb": 2048.0,
        "disk_check_seconds": 60.0,
        "announce_file_name": True,
        "pause_hotkey": "F5",
        "chapter_hotkey": "F12",
    })
    # カメラ（映像キャプチャデバイス）。
    #   hotkey  有効・無効を切り替えるグローバルキー。修飾キーは record と
    #           同じ「基準に1つ足した段」（既定 Ctrl+Alt+Shift）。空で無効。
    #           既定の F11 は Ctrl+Alt+F11＝仮想カメラの「強い版」＝
    #           本物のカメラ、という対応で覚えられるようにしてある
    #   confirm_before_toggle
    #           切り替える前に確認を出すか。カメラを止めるのは安全側の操作
    #           なので既定は出さない（とっさに止められることを優先）
    camera: dict = field(default_factory=lambda: {
        "hotkey": "F11",
        "confirm_before_toggle": False,
    })
    # F6のレベル読み上げ（各入力のレベルを順に読む）の出しかた。
    #   order       読み上げる順番（入力名の並び）。ここに無い入力は
    #               この後ろへ名前順で続く。空なら全部が名前順
    #   skip_muted  ミュート中の入力を読み飛ばすか
    #     ★既定は False。飛ばすと「ミュートされている」ことまで
    #       分からなくなる（音が出ていないのか、切ってあるのかの区別が
    #       つかない）。入力が多くて読み上げが長い人だけが選ぶ設定
    #     ★どちらも「音声」メニューから変えられる（手編集も可）
    level_read: dict = field(default_factory=lambda: {
        "order": [],
        "skip_muted": False,
    })
    # 一覧を辿るときの並び順（OBSナビの中だけの話。OBS本体の並びや
    # 映像の重なり順は変わらない）。
    #   scenes  シーン一覧の並び（シーン名）
    #   items   ソース一覧の並び（ソース名。どのシーンでも同じ順を使う）
    # ★載っていないものは後ろへ、OBSから来た順のまま続く。空なら
    #   全部がOBSと同じ順＝これまでの動き。
    # ★ソース一覧のOBSの順は「重なり順」という意味を持つ。並べ替えると
    #   その意味は一覧から読み取れなくなるので、重なり順そのものを
    #   変えたいときは「前に出す・後ろに送る」を使う（別の操作）。
    list_order: dict = field(default_factory=lambda: {
        "scenes": [],
        "items": [],
    })

    def __post_init__(self) -> None:
        """辞書項目に足りないキーを既定値で補う。

        設定ファイルが古くて一部のキーしか無くても、読み出し側が
        キーの有無を気にせず済むようにする。
        """
        for name, defaults in (
            ("game_switch", {"video_source": "ゲームキャプチャ",
                             "audio_sources": ["ゲーム音"],
                             "also_audio": True,
                             "raise_window": True}),
            ("bgm", {"source_name": "BGM音楽", "last_dir": ""}),
            ("video_switch", {"extra_kinds": []}),
            ("record", {"pause_reminder_seconds": 300.0,
                        "disk_warn_mb": 10240.0,
                        "disk_critical_mb": 2048.0,
                        "disk_check_seconds": 60.0,
                        "announce_file_name": True,
                        "pause_hotkey": "F5",
                        "chapter_hotkey": "F12"}),
            ("camera", {"hotkey": "F11",
                        "confirm_before_toggle": False}),
            ("level_read", {"order": [], "skip_muted": False}),
            ("list_order", {"scenes": [], "items": []}),
        ):
            value = getattr(self, name, None)
            if not isinstance(value, dict):
                setattr(self, name, dict(defaults))
                continue
            for key, default in defaults.items():
                value.setdefault(key, default)

        # record の数値は手で編集される前提なので、文字列や null が入って
        # いても起動時・タイマー内で落ちないよう数値へ寄せる。読めない値は
        # 既定へ戻す（0 は「無効」という意味を持つので勝手に既定へ戻さない）。
        for key in ("pause_reminder_seconds", "disk_warn_mb",
                    "disk_critical_mb", "disk_check_seconds"):
            self.record[key] = _as_float(
                self.record.get(key), float(_RECORD_DEFAULTS[key]))

        # sr_sources は手編集されることがある。
        # 形が壊れていても起動時に KeyError / TypeError で死なないよう、
        # ここで正規化する: list でなければ既定へ、要素は「name を持つ辞書」
        # だけ残す。全要素が不正なら（書き損じとみなして）既定へ戻す。
        # 空リストは「SRソースを使わない」という意図として尊重する。
        if not isinstance(self.sr_sources, list):
            self.sr_sources = _default_sr_sources()
        else:
            cleaned = [
                s for s in self.sr_sources
                if isinstance(s, dict)
                and isinstance(s.get("name"), str) and s.get("name")
            ]
            if not cleaned and self.sr_sources:
                cleaned = _default_sr_sources()
            self.sr_sources = cleaned

        # audio_sources / extra_kinds は「文字列1つ」で書かれがちなので
        # 配列へ直す。それ以外の不正型は既定へ（文字列以外の要素は落とす）。
        audio = self.game_switch.get("audio_sources")
        if isinstance(audio, str):
            self.game_switch["audio_sources"] = [audio]
        elif isinstance(audio, list):
            self.game_switch["audio_sources"] = [
                a for a in audio if isinstance(a, str) and a]
        else:
            self.game_switch["audio_sources"] = ["ゲーム音"]
        extra = self.video_switch.get("extra_kinds")
        if isinstance(extra, str):
            self.video_switch["extra_kinds"] = [extra]
        elif isinstance(extra, list):
            self.video_switch["extra_kinds"] = [
                k for k in extra if isinstance(k, str) and k]
        else:
            self.video_switch["extra_kinds"] = []

        # 並び順の設定は、並べ替えダイアログからも手編集からも入る。
        # 文字列1つで書かれていたら配列へ直し、文字列でない要素と空文字は
        # 落とす。同じ名前が2回あると同じものを2回出してしまうので、
        # 最初の1つだけ残す。
        self.level_read["order"] = _clean_name_list(
            self.level_read.get("order"))
        self.level_read["skip_muted"] = _as_bool(
            self.level_read.get("skip_muted"))
        for key in ("scenes", "items"):
            self.list_order[key] = _clean_name_list(self.list_order.get(key))

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """設定を読み込む。無ければ既定値でファイルを作る。"""
        p = path if path is not None else default_config_path()
        if not p.exists():
            cfg = cls()
            try:
                cfg.save(p)
            except OSError:
                pass
            return cfg
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls._unsaveable()
        if not isinstance(raw, dict):
            return cls._unsaveable()
        known = set(cls.__dataclass_fields__)
        data = {k: v for k, v in raw.items() if k in known}
        try:
            return cls(**data)
        except TypeError:
            return cls._unsaveable()

    @classmethod
    def _unsaveable(cls) -> "Config":
        """読み込みに失敗したときの既定値。保存を禁止しておく。

        壊れた（あるいは読めなかった）設定ファイルを、既定値で上書きして
        しまわないようにするため。dataclass のフィールドにはしないので
        保存内容には現れない。
        """
        cfg = cls()
        cfg._save_blocked = True
        return cfg

    @property
    def save_blocked(self) -> bool:
        """設定ファイルが読めなかったため保存を禁じている状態か。"""
        return bool(getattr(self, "_save_blocked", False))

    def save(self, path: Path | None = None) -> bool:
        """設定を UTF-8 JSON で保存する。書けたら True。

        読み込みに失敗して既定値になっている場合は、利用者の設定を
        既定値で潰さないよう何もしない。

        ★戻り値を必ず見ること。何もしなかったときに呼ぶ側が
        「保存しました」と読み上げると嘘になる（再起動すると消えている
        のに、耳では確かめようが無い）。
        """
        if self.save_blocked:
            return False
        p = path if path is not None else default_config_path()
        # 書き込み途中でクラッシュしても設定を壊さないよう、一時ファイルへ
        # 書き切ってから置き換える（os.replace は同一フォルダ内なら原子的）
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, p)
        return True

    def rename_scene(self, old: str, new: str) -> bool:
        """シーン名の変更に、名前で覚えている設定を追従させる。"""
        if not old or not new or old == new:
            return False
        names, changed = _rename_in_list(
            self.list_order.get("scenes"), old, new)
        if changed:
            self.list_order["scenes"] = names
        return changed

    def rename_input(self, old: str, new: str) -> bool:
        """入力（ソース）名の変更に、名前で覚えている設定を追従させる。

        ★名前をキーに持つ設定はここに全部並べる。1つでも漏れると、
        利用者から見て「名前を変えただけで機能が黙って止まる」ことに
        なる（スクリーンリーダー音声が作り直しを促してくる、BGM や
        ゲーム切り替えが選び直しを求めてくる、並び順だけ末尾へ回る）。
        画面で確かめられないので、気づくのは配信中になりかねない。
        ★UI 層に置かない。名前で持っている設定がどれかは設定の側の
        知識で、wx なしでテストできる場所に無いと漏れに気づけない。
        """
        if not old or not new or old == new:
            return False
        changed = False
        for holder, key in ((self.level_read, "order"),
                            (self.list_order, "items"),
                            (self.game_switch, "audio_sources")):
            names, hit = _rename_in_list(holder.get(key), old, new)
            if hit:
                holder[key] = names
                changed = True
        for holder, key in ((self.game_switch, "video_source"),
                            (self.bgm, "source_name")):
            if holder.get(key) == old:
                holder[key] = new
                changed = True
        for source in self.sr_sources or []:
            if isinstance(source, dict) and source.get("name") == old:
                source["name"] = new
                changed = True
        return changed

    def resolve_connection(self) -> tuple[str, int, str]:
        """接続に使う (host, port, password) を決定する。"""
        host, port, password = self.host, self.port, self.password
        if self.auto_password:
            info = read_obs_websocket_config()
            if info is not None:
                port = info.port
                if info.password:
                    password = info.password
        return host, port, password
