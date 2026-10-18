# -*- coding: utf-8 -*-
"""obs_navi メインウィンドウ。

アクセシビリティ方針:
- すべてのウィジェットに SetName() を付ける
- キー処理はパネルの EVT_CHAR_HOOK に集約（F5/F6/F8/Enter/Alt＋上下など）
  ★Escape はここでは扱わない（0.16.0。終了は Alt+F4 かメニューだけ）
- ラベル用 StaticText は、対応するコントロールより先に生成する
- 状態変化の読み上げは OBS からのイベント経由で一元化する
  （自分の操作でも OBS 側の操作でも同じように読み上げられる）
- OBSイベントは別スレッドで届くため、必ず wx.CallAfter でUIスレッドへ渡す
"""
from __future__ import annotations

import contextlib
import functools
import os
import subprocess
import time

import wx

import speech
from core import (
    camera, commands, filters, hotkeys, keymap, ordering, props, recording,
    scenes, setup, sources, speech_format, tracks, video, volume)
from core.config import Config
from core.connection import ObsConnection, ObsConnectError
from core.levels import LevelMonitor, peak_db_from_levels
from core.settings_op import SettingsOp
from core.state import Snapshot
from ui import prop_dialog
from version import VERSION

# 設定変更のイベントを待つ時間。これを過ぎたら読み直して確定させる。
SETTINGS_SETTLE_MS = 700

# ソース一覧・音声入力一覧で選択を動かしてから、フィルター一覧を
# 作り直すまでの待ち時間。★矢印キーで辿るたびにOBSへ問い合わせると
# 1打鍵ごとに通信待ちが入り、行の読み上げが詰まる。押し終わってから聞く。
FILTER_REFRESH_DELAY_MS = 250

# リプレイ保存の完了イベントを待つ時間。保存は非同期なので、要求が通った
# 時点では読み上げない（嘘になる）。届かなければこの時間で保険を出す。
REPLAY_SETTLE_MS = 2000

# 録画中の見張りタイマーの刻み。実際に何をどの間隔で見るかは設定側
# （pause_reminder_seconds / disk_check_seconds）が決めるので、ここは
# 「見に行くかどうかを判断する最小単位」でしかない。
RECORD_TICK_MS = 10000

# カメラの有効・無効を切り替えたあと、実際にそうなったかを確かめるまでの
# 待ち時間。実測で、止めるのは即座、動かし直すのは 1.8 秒ほどかかった。
# ★切り替えにはイベントが飛ばない（実測）ので、読み直すしかない。
CAMERA_SETTLE_MS = 2500

STARTED = "OBS_WEBSOCKET_OUTPUT_STARTED"
STOPPED = "OBS_WEBSOCKET_OUTPUT_STOPPED"
PAUSED = "OBS_WEBSOCKET_OUTPUT_PAUSED"
RESUMED = "OBS_WEBSOCKET_OUTPUT_RESUMED"

# キー名 → wx の仮想キーコード（グローバル登録に使える候補）
#
# 矢印キーはここに入れない。RegisterHotKey はシステム全体でキーを奪うので、
# Ctrl+Shift+矢印 を登録すると全アプリで文字の範囲選択ができなくなる
# （実測で確認済み。しかも登録自体は成功するため警告も出せない）。
# 矢印での音量調整はウィンドウ内（EVT_CHAR_HOOK）だけにしてある。
KEY_NAME_TO_WXK = {
    "F1": wx.WXK_F1, "F2": wx.WXK_F2, "F3": wx.WXK_F3, "F4": wx.WXK_F4,
    "F5": wx.WXK_F5, "F6": wx.WXK_F6, "F7": wx.WXK_F7,
    "F8": wx.WXK_F8, "F9": wx.WXK_F9, "F10": wx.WXK_F10,
    "F11": wx.WXK_F11, "F12": wx.WXK_F12,
}

# 正規修飾トークン → wx の修飾フラグ
MOD_TOKEN_TO_WX = {
    "ctrl": wx.MOD_CONTROL,
    "shift": wx.MOD_SHIFT,
    "alt": wx.MOD_ALT,
    "win": wx.MOD_WIN,
}


def _register_hotkey_norepeat(hwnd: int, hid: int, modifiers: int,
                              vk: int) -> bool:
    """Win32 の RegisterHotKey を直接呼ぶ（MOD_NOREPEAT を渡すため）。

    ★wx の RegisterHotKey は MOD_NOREPEAT を渡せない（修飾キーは
    Alt/Ctrl/Shift/Win だけを写す）。登録だけ自前でしても、WM_HOTKEY は
    wx が id で EVT_HOTKEY へ振り分けるので受け取り側はそのまま使え、
    解除も wx の UnregisterHotKey（同じ窓・同じ id）で効く。
    Windows 以外では例外になる（呼ぶ側が wx の登録へ切り替える）。
    """
    import ctypes
    from ctypes import wintypes

    register = ctypes.WinDLL("user32").RegisterHotKey
    register.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT,
                         wintypes.UINT)
    register.restype = wintypes.BOOL
    return bool(register(hwnd, hid, modifiers, vk))


def _close_enough(got, want) -> bool:
    """フィルター設定の読み戻しが、投げた値と実質同じか。

    OBSはfloat32で持つので 6.0 が 5.99999952 で返ることがある
    （音量で踏んだのと同じ問題。core/volume.py の説明を参照）。
    厳密比較だけだと「変わりませんでした」と誤報する。
    """
    try:
        return abs(float(got) - float(want)) < 1e-3
    except (TypeError, ValueError):
        return False


class MainFrame(wx.Frame):
    """OBSナビのメインウィンドウ。"""

    def __init__(self, config: Config) -> None:
        super().__init__(None, title=f"OBSナビ {VERSION}")
        self.config = config
        self.conn = ObsConnection(config)
        self.monitor = LevelMonitor(
            silence_threshold_db=config.silence_threshold_db,
            silence_seconds=config.silence_seconds,
            clip_threshold_db=config.clip_threshold_db,
            cooldown_seconds=config.warn_cooldown_seconds,
            hold_seconds=config.level_hold_seconds,
        )
        self.snapshot = Snapshot()
        self._muted: dict[str, bool] = {}
        self._input_names: list[str] = []
        # フィルター一覧に今表示しているソース名と、その並び（名前のリスト）
        self._filter_source: str = ""
        self._filter_names: list[str] = []
        # ソース一覧に今表示しているシーン名と、その並び（item_id のリスト）。
        # 可視性の操作・イベントは名前でなく item_id で行う。
        self._item_scene: str = ""
        self._item_ids: list[int] = []
        self._item_names: dict[int, str] = {}  # item_id → ソース名（読み上げ用）
        # 並べ替える前の、OBSから来た順のソース名（並べ替え画面の基準）
        self._item_obs_names: list[str] = []
        # スクリーンリーダー音声ソースの索引（名前→ソース、
        # キーコード→ソース）。名前が変わったら作り直す
        self._sr_by_name: dict[str, dict] = {}
        self._sr_key_codes: dict[int, dict] = {}
        self._build_sr_index()
        # 各SR入力の作成直後に飛ぶミュートイベントの読み上げを1回だけ抑止する
        # ため、作成中の入力名を保持する（作成成功メッセージと二重にしない）
        self._sr_setup_pending: set[str] = set()
        # グローバルホットキーの登録状態
        self._registered_hotkey_ids: list[int] = []
        self._hotkey_id_refs: list = []  # NewIdRef を GC から守る
        # モーダルダイアログの入れ子の深さ。0より大きい間は、割り込みの
        # 読み上げ（無音警告など）や副作用のあるホットキーを抑える。
        # ダイアログの操作中に読み上げを切られると現在位置を見失うため。
        self._modal_depth = 0
        # イベントコールバックで例外を報告済みのハンドラ名（1回だけ読む）
        self._callback_errors: set[str] = set()
        # ★起動して最初の1回は割り込ませない。スクリーンリーダーが読んで
        #   いる状態欄の名前（バージョン入り）を切らないため。どの経路の
        #   読み上げが最初に来ても守れるよう speech 側に持たせてある
        #   （0.17.2 は接続の読み上げだけを直したので、切断エラーや
        #     レベル警告が最初だと版が切られていた）
        speech.start_grace()
        # フィルター一覧が追従する先（最後に「選択を動かした」リスト）と、
        # 作り直しの予約（_schedule_filter_refresh を参照）
        self._filter_follow = None
        # ★録画の見張りと同じ作りに揃える（wx.Timer を1つ持ち回す）。
        #   wx.CallLater は呼ぶたびに新しいタイマーを作り、クラス側の
        #   一覧に自分を登録して窓より長生きするので、取り消しと
        #   生死の確認を自前で書く羽目になっていた
        self._filter_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_filter_refresh_timer,
                  self._filter_timer)
        # アプリケーションキーで出したメニューに結び付けた項目ID。
        # ★次にメニューを出すときまで外さない（下の popup_list_menu を参照）
        self._popup_bound: list = []
        self._pending_warnings: list[str] = []
        # 設定変更の合流（core/settings_op.py の説明を参照）
        self._settings_op: SettingsOp | None = None
        self._settings_timer = None
        self._settings_seq = 0
        self._settings_last: dict[str, dict] = {}
        # 録画の見張り（core/recording.py の説明を参照）。どちらも純ロジックで、
        # 時刻・残量を外から流し込む。回すのは録画中だけ。
        rec_cfg = config.record
        self.pause_reminder = recording.PauseReminder(
            interval_seconds=rec_cfg.get("pause_reminder_seconds", 300.0))
        self.disk_watch = recording.DiskWatch(
            warn_mb=rec_cfg.get("disk_warn_mb", 10240.0),
            critical_mb=rec_cfg.get("disk_critical_mb", 2048.0))
        self._record_timer = None
        self._last_disk_check = 0.0
        # 直近の録画ファイル（「最後の録画を開く」で使う）
        self._last_record_path = ""
        # リプレイ保存の要求中フラグ。完了イベントで読み上げるので、
        # 届かなかったときの保険（_settle_replay）と合わせて使う
        self._replay_pending = False
        # グローバルキーで配信を開始・停止するときの二度押し確認
        self._repeat_confirm = hotkeys.RepeatConfirm()
        # 今の録画で打ったチャプターの数（録画開始ごとに0へ戻す）
        self._chapter_count = 0
        # 最後に触ったリスト（メニューやグローバルキーから操作したとき、
        # どのリストの選択を対象にするかを決めるのに使う）
        self._last_list = None
        # 次にシーン一覧を作り直すとき、優先して選び直す名前
        # （リネームで古い名前が消えると選択が先頭へ飛ぶため）
        self._prefer_scene = ""
        # キー割り当ての問題（使えないキー名・重複・登録失敗・実装漏れ）。
        # 起動時に1回の読み上げにまとめる（_announce_key_problems）。
        # ★別々の CallLater で読むと、speech.warn の割り込みで先の警告が
        #   途中で切られてしまう（0.14.0 で実際に起きた）
        self._key_problems: list[str] = []
        # 窓内キーの振り分け表（(修飾フラグ, キーコード) → 実行する処理）。
        # ★keymap.WINDOW_PLAN から作る＝表示と動作の出どころを1つにする
        self._window_dispatch: dict = {}
        self._build_window_dispatch()
        self._build_ui()
        # ★メニューはリストを作ったあとに組む（項目のキー表示が設定を
        #   読むので、設定まわりの初期化が済んでからでないといけない）
        self._build_menubar()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.SetSize((640, 640))
        self.register_global_hotkeys()
        self._announce_key_problems()
        # ウィンドウ表示とフォーカス移動の読み上げが落ち着いてから接続する。
        # 直後だと接続完了の読み上げがフォーカス移動の読み上げに埋もれるため、
        # 少し待ってから、かつ起動時は接続完了メッセージのみを読む。
        wx.CallLater(600, self.do_connect, False)

    def _build_sr_index(self) -> None:
        """スクリーンリーダー音声ソースの索引を作る（名前・キーコード）。

        ★走査は keymap.sr_entries に一本化してある。ここを通すことで、
        登録・メニュー・一覧と同じ検証（キー名の正規化・不正値の除外）が
        かかる。
        ★同じキーが2つに設定されていたら先に書いた方を残す（先勝ち）。
        グローバルキーの RegisterHotKey も先勝ちなので段で規則を揃える。
        どちらが効くかは起動時の重複警告がそのとおりに読み上げる
        （keymap.duplicate_bindings）。
        ★名前が変わったら呼び直すこと。索引は名前で引くので、古いままだと
        「入力がありません。作成しますか？」と二重作成を促してしまう。
        """
        self._sr_by_name = {}
        self._sr_key_codes = {}
        for source, name, key in keymap.sr_entries(self.config):
            self._sr_by_name[name] = source
            code = KEY_NAME_TO_WXK.get(key)
            if code is not None:
                self._sr_key_codes.setdefault(code, source)

    # ------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------
    def _build_ui(self) -> None:
        # ★板は縦にスクロールさせる（0.18.3）。0.18.1 で配信・録画の一覧を
        #   足したら、起動時の窓（640×640）に入りきらず、いちばん下の
        #   フィルター一覧が 9 ポイントでも高さ 0 に潰れた。潰れた欄は
        #   Tab で止まり名前も読まれるが、選んでいる項目が読まれない
        #   （ダイアログの大きさを決め打ちにしない）。
        #   スクロールする板なら、入りきらない分は潰さずに
        #   スクロールへ逃がし、Tab で移った欄は見える位置まで送られる
        panel = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        panel.SetName("メインパネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.panel = panel
        root = wx.BoxSizer(wx.VERTICAL)

        # ★状態欄の名前にバージョンを入れてある（0.17.1）。
        #   起動して最初にフォーカスが載るのがこの欄なので、
        #   **スクリーンリーダーが最初に読む言葉がバージョンになる**。
        #   0.17.0 では読み上げの文にバージョンを前置きしていたが、それは
        #   スクリーンリーダー自身のフォーカス読み上げ（「状態の参照」）より
        #   後に来るので、「先にバージョンを読んでほしい」に応えられなかった。
        #   実測: この欄の accName が「状態」、accRole=42（読み取り専用の
        #   テキスト）で、PC-Talker は「状態の参照」と読んでいた。
        #   ＝名前より前に差し込める言葉は無い。だから名前自体に入れる。
        #   ラベルと SetName の両方を変える（どちらが読み上げ名に使われても
        #   同じになるように）。
        status_label = f"OBSナビ バージョン {VERSION} の状態"
        lbl_status = wx.StaticText(panel, label=status_label)
        self.status_text = wx.TextCtrl(
            panel,
            value="未接続",
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 56),
        )
        self.status_text.SetName(status_label)
        root.Add(lbl_status, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.status_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # 配信・録画の開始と停止（0.18.0）。状態欄の次＝起動直後に Tab
        # 1回で届く位置に置く。ほかの操作はメニューにあるが、この4つは
        # 配信の最初と最後に必ず使うので、キーを覚えていなくても
        # Tab だけで辿り着けるようにした（利用者の指示）。
        # ★ボタン4つではなくリスト1つにしてある（0.18.1、利用者の指示）。
        #   ボタンだと、シーンやソースを触りに行くたびに Tab を4回
        #   余計に押すことになる。リストなら Tab 1回で通り過ぎられ、
        #   中では上下矢印で選んで Enter で実行する（他のリストと同じ作法）
        # ★項目名にキーを入れる。矢印で選んだときに
        #   「配信を開始 Ctrl+S」と読まれ、次からキーで押せる。
        #   キー名は keymap から引く（一覧・メニューとずれないように）
        # ★状態に応じて項目を消したり入れ替えたりはしない。位置が
        #   変わると矢印の回数が変わってしまう。押したときに
        #   「すでに配信中です」と読むので足りる
        lbl_outputs = wx.StaticText(
            panel, label="配信・録画（上下矢印で選んでEnterで実行）")
        # ★実行する処理は窓内キーの対応表から引く（0.18.3）。同じ対応を
        #   ここにも書くと、片方だけ直したときに Enter とキーで違う処理が
        #   動く
        actions = self._window_actions()
        self._output_actions = []
        labels = []
        for action_id in ("stream_start", "stream_stop",
                          "record_start", "record_stop"):
            label = keymap.action_label(action_id)
            key = keymap.window_key_label(self.config, action_id)
            labels.append(f"{label} {key}" if key else label)
            self._output_actions.append(actions[action_id])
        self.output_list = wx.ListBox(panel, choices=labels, size=(-1, 72))
        self.output_list.SetName("配信・録画")
        # ★最初から先頭を選んでおく。選択の無いリストに Tab で入ると、
        #   スクリーンリーダーは項目を何も読まない
        self.output_list.SetSelection(0)
        self.output_list.Bind(
            wx.EVT_LISTBOX_DCLICK, lambda _evt: self.run_selected_output())
        root.Add(lbl_outputs, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.output_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        lbl_scenes = wx.StaticText(panel, label="シーン一覧（Enterで切り替え）")
        self.scene_list = wx.ListBox(panel, size=(-1, 120))
        self.scene_list.SetName("シーン一覧")
        self.scene_list.Bind(wx.EVT_LISTBOX, self.on_scene_selected)
        root.Add(lbl_scenes, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.scene_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # シーン内ソースの表示・非表示（シーン一覧で選択中のシーンのソース）。
        # 「今画面に何が映っているか」を読み、Enterで出し入れする。
        self.lbl_items = wx.StaticText(
            panel, label="ソース一覧（Enterで表示・非表示）")
        self.item_list = wx.ListBox(panel, size=(-1, 110))
        self.item_list.SetName("ソース一覧")
        self.item_list.Bind(wx.EVT_LISTBOX, self.on_item_selected)
        root.Add(self.lbl_items, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.item_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        lbl_inputs = wx.StaticText(
            panel,
            label="音声入力一覧（Enterでミュート切り替え、"
                  "左右キーで音量、Shift＋左右で大きく、F7で数値入力）")
        self.input_list = wx.ListBox(panel, size=(-1, 140))
        self.input_list.SetName("音声入力一覧")
        self.input_list.Bind(wx.EVT_LISTBOX, self.on_input_selected)
        root.Add(lbl_inputs, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.input_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # フィルター一覧（音声入力一覧で選択中のソースのフィルター）。
        # OBS本体でスクリーンリーダーが読めない部分をここで扱う。
        self.lbl_filters = wx.StaticText(
            panel, label="フィルター一覧（Enterでオン・オフ）")
        self.filter_list = wx.ListBox(panel, size=(-1, 110))
        self.filter_list.SetName("フィルター一覧")
        root.Add(self.lbl_filters, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.filter_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ★ボタンは置かない。操作はすべてメニューバーにある
        #   （配信・録画の4つだけは、上のリストからも実行できる）。0.13.0 まではボタンを並べていたが、機能が増えて10行・約34個に
        #   なり、Tab で最後まで辿るのが長くなりすぎた。メニューは Alt か
        #   F10 と矢印で辿れてタブ順を消費しないので、リストだけを
        #   タブ順に残せる。

        # メニューやグローバルキーから操作したとき、フォーカスがリスト上に
        # あるとは限らない（状態欄にいる、メニューを閉じた直後など）。
        # そのとき FindFocus() では対象を決められないので、最後に触った
        # リストを覚えておく（_props_target がフォールバックに使う）
        for lst in (self.scene_list, self.item_list, self.input_list,
                    self.filter_list):
            lst.Bind(wx.EVT_SET_FOCUS, self._remember_list_focus)

        panel.SetSizer(root)
        # スクロールの範囲を中身に合わせる（窓の大きさが変わったときは
        # wx が合わせ直す）
        panel.FitInside()

    # ------------------------------------------------------------
    # メニューバー
    # ------------------------------------------------------------
    def _menu_item(
        self, menu: wx.Menu, label: str, handler,
        window_id: str = "", global_id: str = "", accel: str = "",
    ) -> wx.MenuItem:
        """メニュー項目を1つ足す。

        キーの表示は core/keymap.py から引く（登録と同じ出どころなので、
        メニューに書いてあるキーと実際に効くキーがずれない）。
        タブ文字の後ろに書くとOSがアクセラレータ欄として扱い、
        スクリーンリーダーが「〜、Ctrl+B」のように読んでくれる。

        ★アクセラレータを付けても二重には動かない。実測で、
        EVT_CHAR_HOOK が先に処理し、そこで消費すれば（Skipしなければ）
        メニュー側へ流れないことを確認済み。素押しキーの処理はこれまで
        どおり on_char_hook が担い、ここは表示と、キーを覚えていなくても
        辿り着くための入口として置く。
        """
        # ★文言はキー一覧（F1）の説明と同じでなければならない。ずれると、
        #   耳で探している人には「一覧に載っている項目がメニューに無い」の
        #   と同じことになる。ここで見張って起動時に読み上げる
        known = keymap.action_label(window_id or global_id)
        if known and known != label:
            self._key_problems.append(
                f"メニューの「{label}」はキー操作の一覧では「{known}」です。"
                "文言を揃えてください")
        text = accel or keymap.menu_accel(self.config, window_id, global_id)
        item = menu.Append(wx.ID_ANY, f"{label}\t{text}" if text else label)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _build_menubar(self) -> None:
        """すべての操作をメニューへ並べる。

        並びは「よく使う順」ではなく「対象ごと」にした。目で全体を
        見渡せない以上、探すときは対象から辿るほうが速いため
        （シーンを触りたい → シーンメニュー）。
        """
        bar = wx.MenuBar()

        # --- 配信・録画 ---
        m = wx.Menu()
        self._menu_item(m, "配信を開始", self.on_stream_start,
                        window_id="stream_start")
        self._menu_item(m, "配信を停止", self.on_stream_stop,
                        window_id="stream_stop")
        m.AppendSeparator()
        self._menu_item(m, "録画を開始", self.on_record_start,
                        window_id="record_start")
        self._menu_item(m, "録画を停止", self.on_record_stop,
                        window_id="record_stop")
        self._menu_item(m, "録画の一時停止・再開", self.on_record_pause,
                        window_id="record_pause")
        self._menu_item(m, "チャプターを付ける", self.on_chapter_btn,
                        global_id="chapter")
        m.AppendSeparator()
        self._menu_item(m, "リプレイを保存", self.on_replay_btn,
                        global_id="replay")
        self._menu_item(m, "仮想カメラの切り替え", self.on_vcam_btn,
                        global_id="virtual_cam")
        m.AppendSeparator()
        self._menu_item(m, "録画設定の確認", self.on_rec_settings_btn)
        # 録画で音を別トラックに分ける（docs/SETUP_MAC.md の手順6）。
        # ソースごとの割り当ては、そのソースの設定画面にある
        self._menu_item(m, "録画のトラック設定", self.on_rec_tracks_btn)
        self._menu_item(m, "最後の録画を開く", self.on_open_rec_btn)
        m.AppendSeparator()
        # ★Escape では終了しない（0.16.0）。設定の画面を Escape で
        #   閉じたつもりが、もう1回押してアプリまで閉じかける事故が
        #   起きていた。終了は Alt+F4 かこの項目だけにしてある
        exit_item = m.Append(wx.ID_EXIT, "終了\tAlt+F4")
        self.Bind(wx.EVT_MENU, self.on_exit_menu, exit_item)
        bar.Append(m, "配信・録画(&S)")

        # --- シーン ---
        m = wx.Menu()
        self._menu_item(m, "シーンを作る", self.on_scene_add_btn)
        self._menu_item(m, "シーンの設定", self.on_scene_props_btn)
        self._menu_item(m, "シーンを削除", self.on_scene_remove_btn)
        m.AppendSeparator()
        self._menu_item(m, "シーン一覧の並び順", self.on_scene_order_btn)
        bar.Append(m, "シーン(&C)")

        # --- ソース ---
        m = wx.Menu()
        self._menu_item(m, "ソースを作る", self.on_source_add_btn)
        self._menu_item(m, "ソースの設定", self.on_props_btn)
        self._menu_item(m, "ソースを削除", self.on_source_remove_btn)
        m.AppendSeparator()
        self._menu_item(m, "ゲーム切り替え", self.on_game_btn,
                        window_id="game")
        self._menu_item(m, "映像切り替え", self.on_video_btn,
                        window_id="video")
        self._menu_item(m, "BGMの再生・一時停止", self.on_bgm_btn,
                        window_id="bgm")
        m.AppendSeparator()
        # 重なり順（OBS本体が変わる）と、一覧の並び順（OBSナビの中だけ）は
        # 別のもの。取り違えないよう言葉で区別してある
        self._menu_item(m, "ソースを前に出す（重なり順）",
                        self.on_item_front_btn)
        self._menu_item(m, "ソースを後ろに送る（重なり順）",
                        self.on_item_back_btn)
        self._menu_item(m, "ソース一覧の並び順", self.on_item_order_btn)
        bar.Append(m, "ソース(&O)")

        # --- フィルター ---
        m = wx.Menu()
        self._menu_item(m, "フィルターを追加", self.on_filter_add_btn)
        self._menu_item(m, "フィルターの設定", self.on_filter_props_btn)
        self._menu_item(m, "フィルターを削除", self.on_filter_remove_btn)
        bar.Append(m, "フィルター(&F)")

        # --- カメラ ---
        m = wx.Menu()
        self._menu_item(m, "カメラの確認", self.on_camera_check_btn)
        # ★「カメラの切り替え」とは呼ばない。配信・録画メニューの
        #   「仮想カメラの切り替え」と紛らわしく、読み上げで聞き分け
        #   にくいため（別物：こちらは実機、あちらはOBSの出力）。
        #   キー一覧の説明とも同じ言い回しに揃えてある
        self._menu_item(m, "カメラの有効・無効", self.on_camera_toggle_btn,
                        global_id="camera")
        bar.Append(m, "カメラ(&K)")

        # --- 音声 ---
        m = wx.Menu()
        # スクリーンリーダー音声は設定の数だけ増える（データ駆動）。
        # ★走査・文言・キーはすべて keymap 経由。キーは検証済みの値だけが
        #   返るので、英字などの使えない設定値がアクセラレータに載って
        #   リストの頭文字ジャンプを奪うことがない。
        # ★固定の窓内キー（F5 など）と衝突する SR キーはアクセラレータに
        #   載せない。同じキーのアクセラレータが2つあると wx がキーを
        #   飲み込んで両方とも動かなくなる（実測）。衝突自体は起動時の
        #   重複警告が知らせ、キーの実処理は on_char_hook 側が担う
        fixed_keys = {k for _aid, k, _d in keymap.WINDOW_PLAN}
        sr_items = keymap.sr_entries(self.config)
        for source, name, key in sr_items:
            self._menu_item(
                m, keymap.sr_toggle_label(name),
                lambda _evt, s=source: self.toggle_sr_source(s),
                accel="" if key in fixed_keys else key)
        if sr_items:
            m.AppendSeparator()
        self._menu_item(m, "レベル読み上げ", self.on_levels_btn,
                        window_id="levels")
        self._menu_item(m, "音量を数値で入力", self.on_volume_btn,
                        window_id="volume_prompt")
        m.AppendSeparator()
        # レベル読み上げ(F6)の出しかた。順番は並べ替えの画面、ミュートを
        # 飛ばすかはチェック項目。★設定の出どころは config.level_read の
        # 1か所だけにしてあり、ここは入口でしかない
        self._menu_item(m, "レベル読み上げの順番", self.on_level_order_btn)
        self._menu_item(m, "録画のトラック割り当てを読む",
                        self.on_tracks_overview_btn)
        self.skip_muted_item = m.AppendCheckItem(
            wx.ID_ANY, "ミュート中のソースを読み上げない")
        self.skip_muted_item.Check(
            bool(self.config.level_read.get("skip_muted", False)))
        self.Bind(wx.EVT_MENU, self.on_skip_muted_toggle, self.skip_muted_item)
        bar.Append(m, "音声(&A)")

        # --- ツール ---
        m = wx.Menu()
        self._menu_item(m, "状態読み上げ", self.on_state_btn,
                        window_id="state")
        self._menu_item(m, "統計読み上げ", self.on_stats_btn,
                        global_id="stats")
        m.AppendSeparator()
        self._menu_item(m, "OBSに再接続", self.on_reconnect_btn)
        bar.Append(m, "ツール(&T)")

        # --- ヘルプ ---
        m = wx.Menu()
        self._menu_item(m, "キー操作の一覧", self.on_help_keys,
                        window_id="help")
        about_item = m.Append(wx.ID_ABOUT, "OBSナビについて")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        bar.Append(m, "ヘルプ(&H)")

        self.SetMenuBar(bar)

    # ------------------------------------------------------------
    # 接続
    # ------------------------------------------------------------
    def _guard_ws_callback(self, fn):
        """OBSイベントのコールバックを例外から守るラッパ。

        obsws-python はコールバックを無ガードで呼ぶため、ハンドラが一度でも
        例外を出すと**イベント受信スレッドそのものが黙って死に**、以後は
        再接続まで一切の状態読み上げが止まる（このアプリで最悪の壊れ方）。
        ここで受け止めてスレッドを守り、初回だけエラーを読んで気づけるように
        する。obsws-python は fn.__name__ でイベント名を照合するため、
        functools.wraps で名前を保つこと。
        """
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                name = fn.__name__
                if name not in self._callback_errors:
                    self._callback_errors.add(name)
                    try:
                        wx.CallAfter(
                            speech.error,
                            f"イベント処理でエラーが起きました（{name}: {exc}）")
                    except Exception:  # noqa: BLE001
                        pass
        return wrapped

    def do_connect(self, announce_connecting: bool = False) -> None:
        if not self:
            # 起動直後の CallLater が、既に閉じたウィンドウで発火した場合
            return
        if self.conn.connected:
            speech.speak("すでに接続しています")
            return
        if announce_connecting:
            speech.speak("OBSに接続しています")
        callbacks = [
            self.on_stream_state_changed,
            self.on_record_state_changed,
            self.on_current_program_scene_changed,
            self.on_input_mute_state_changed,
            self.on_input_volume_changed,
            self.on_input_volume_meters,
            self.on_scene_created,
            self.on_scene_removed,
            self.on_scene_name_changed,
            self.on_input_created,
            self.on_input_removed,
            self.on_input_name_changed,
            self.on_source_filter_enable_state_changed,
            self.on_source_filter_list_reindexed,
            self.on_source_filter_created,
            self.on_source_filter_removed,
            self.on_scene_item_enable_state_changed,
            self.on_scene_item_created,
            self.on_scene_item_removed,
            self.on_scene_item_list_reindexed,
            self.on_virtualcam_state_changed,
            self.on_replay_buffer_saved,
            self.on_input_settings_changed,
            self.on_input_audio_monitor_type_changed,
            self.on_media_input_playback_started,
            self.on_media_input_playback_ended,
            self.on_media_input_action_triggered,
            self.on_exit_started,
        ]
        callbacks = [self._guard_ws_callback(fn) for fn in callbacks]
        try:
            self.conn.connect(callbacks=callbacks)
        except ObsConnectError as exc:
            self._set_status(str(exc))
            speech.error(str(exc))
            return
        self.refresh_from_obs(announce="connected")

    def refresh_from_obs(self, announce: str = "") -> None:
        """OBSから状態を取り直してUIへ反映する。"""
        if not self.conn.connected:
            return
        try:
            snap = commands.fetch_snapshot(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            self._handle_disconnect(f"OBSとの通信に失敗しました（{exc}）")
            return
        self.apply_snapshot(snap)
        if announce == "connected":
            # ★バージョンはここでは言わない。状態欄の名前が先に読まれるので
            #   二重になる（0.17.1。_build_ui の説明を参照）
            # 起動して最初の1回だけは speech 側が割り込みを外す
            speech.speak(
                f"OBSに接続しました。{speech_format.state_summary(snap)}",
                interrupt=True)

    def _monitor_should_be_active(self) -> bool:
        """レベル警告を出すべき状態か（配信中か録画中、かつ設定で有効）。

        monitor_enabled=False のときは警告を出さない。ピークの追跡は
        続けるので F6 のレベル読み上げはそのまま使える。
        """
        if not self.config.monitor_enabled:
            return False
        return bool(self.snapshot.streaming or self.snapshot.recording)

    def apply_snapshot(self, snap: Snapshot) -> None:
        # ★入力一覧の選択は「名前」で覚えてから作り直す。番号で戻すと、
        #   上にある入力が消えた（増えた）だけで黙って別の入力へずれる。
        #   そのあとの Enter はそちらをミュートし、音量キーもそちらに
        #   効く。読み上げは何も言わないので耳では気づけない
        keep_input = self._selected_input_name()
        self.snapshot = snap
        self._muted = {i.name: i.muted for i in snap.audio_inputs}
        self._input_names = [i.name for i in snap.audio_inputs]
        self.monitor.set_active(
            self._monitor_should_be_active(), time.monotonic())
        self.monitor.forget_missing(set(self._input_names))
        # 起動したときに既に録画中・一時停止中のこともある。見張りを実状態へ
        # 合わせる（イベントを取り逃していても、ここで必ず追いつく）
        self.pause_reminder.set_paused(snap.record_paused, time.monotonic())
        self._sync_record_watch()
        # ★現在のシーンへ寄せるのは、まだ何も選ばれていないとき
        #   （＝起動して最初の1回）だけ。毎回寄せると、F5 や OBS 側の
        #   イベント、設定ダイアログを閉じたときに、利用者が見ていた
        #   シーンから配信中のシーンへ選択が黙って飛ぶ。そのあとの
        #   Enter や Alt＋上下は配信中のシーンを触ってしまう
        self._refresh_scene_list(
            snap.current_scene
            if self.scene_list.GetSelection() == wx.NOT_FOUND else "")
        # 選択中のシーンに合わせてソース一覧も更新する（読み上げはしない）。
        # ★このあとフィルター一覧を必ず作り直すので、ここでは追従させない
        #   （同じ問い合わせを2回しないため）
        self.refresh_item_list(sync_filters=False)
        labels = [
            speech_format.input_list_label(i.name, i.muted, i.volume_db)
            for i in snap.audio_inputs
        ]
        self.input_list.Set(labels)
        if labels:
            if keep_input in self._input_names:
                self.input_list.SetSelection(
                    self._input_names.index(keep_input))
            else:
                self.input_list.SetSelection(0)
        # 選択中の入力に合わせてフィルター一覧も更新する（読み上げはしない）
        self.refresh_filter_list()
        self._set_status(speech_format.state_summary(snap))

    def _refresh_scene_list(self, prefer: str = "") -> None:
        """シーン一覧を今の設定の並びで作り直す。

        ★選択を必ず1つ残す。どこも選ばれていないリストは、耳で辿ると
        「何も無い」のか「選ばれていないだけ」なのか区別が付かない。
        prefer（あれば現在のシーン）→ もとの選択 → 先頭 の順で選ぶ。
        """
        keep = self._prefer_scene or self.scene_list.GetStringSelection()
        self._prefer_scene = ""
        rows = self._ordered_scenes(self.snapshot.scenes)
        self.scene_list.Set(rows)
        if not rows:
            return
        for name in (prefer, keep):
            if name and name in rows:
                self.scene_list.SetStringSelection(name)
                return
        self.scene_list.SetSelection(0)

    def _set_status(self, text: str) -> None:
        self.status_text.SetValue(text)

    def _handle_disconnect(self, message: str) -> None:
        self.conn.close()
        self.snapshot = Snapshot()
        self._set_status(message)
        speech.error(message)

    def _require_connection(self) -> bool:
        if self.conn.connected:
            return True
        speech.error("OBSに接続していません。再接続を実行してください")
        return False

    @contextlib.contextmanager
    def modal(self, restore_focus: bool = True):
        """モーダル表示中であることを記録し、閉じたらフォーカスを戻す。

        この間は無音警告などの割り込み読み上げを溜めておき、副作用のある
        グローバルホットキーも無視する（ダイアログ操作中に読み上げを
        切られると、どこにいるか分からなくなるため）。

        ★フォーカスの復帰が要る理由（0.8.1で修正した実バグ）:
        Windowsのネイティブなファイル選択ダイアログを閉じると、フォーカスが
        どのコントロールにも無い状態（hwndFocus=0）で戻ってくることがある。
        スクリーンリーダーはフォーカスのある要素を読むので、この状態になると
        **何も読み上げられなくなり、利用者は操作不能になる**。実機で発生を
        確認済み。開く前のコントロールへ必ず戻す。

        ★restore_focus=False はアプリケーションキーのメニュー用。
        メニューは閉じれば Windows が自分でフォーカスを戻すので復帰は
        要らず、メニューで選んだ動作（wx.CallAfter で後ろに並ぶ）が
        開いたダイアログの表示中に復帰が発火する余地も作らない。
        ★抑止の中身（深さの数え方と警告の吐き出し）は1か所に置く。
        0.17.3 は同じ本体を持つ別の contextmanager を並べていたので、
        どちらかだけ直す事故が起きうる形になっていた。
        """
        before = None
        if restore_focus:
            try:
                before = wx.Window.FindFocus()
            except Exception:  # noqa: BLE001
                before = None
        self._modal_depth += 1
        try:
            yield
        finally:
            self._modal_depth -= 1
            if self._modal_depth <= 0:
                self._modal_depth = 0
                self._flush_warnings()
            if restore_focus:
                self._restore_focus(before)

    def _ready_for_dialog(self) -> bool:
        """ダイアログを出す前に、ウィンドウが前面にあるか確かめる。

        グローバルホットキーから呼ばれたときはウィンドウが後ろにいる
        ことがある。そのままモーダルを開くと、見えず読まれもしない
        ダイアログに閉じ込められる（実際にフォーカス喪失で無言になる
        事故を起こしている）。前に出したうえで、押し直してもらう。
        """
        if self.IsActive():
            return True
        try:
            self.Raise()
        except Exception:  # noqa: BLE001
            pass
        speech.warn(
            "操作にはOBSナビの画面が必要です。画面を前に出しました。"
            "もう一度押してください")
        return False

    def _restore_focus(self, target) -> None:
        """モーダルを閉じたあとのフォーカス復帰。

        破棄済みのウィンドウには戻せないので、その場合は自分のパネルへ。
        どこにもフォーカスが無い状態だけは絶対に作らない。
        """
        def _apply():
            try:
                if target and bool(target):
                    target.SetFocus()
                    return
            except Exception:  # noqa: BLE001
                pass
            try:
                # 戻せなければ、せめて読み上げ対象のあるリストへ
                self.input_list.SetFocus()
            except Exception:  # noqa: BLE001
                pass
        # ネイティブダイアログが完全に閉じてから戻す必要があるため後回しにする
        wx.CallAfter(_apply)

    def _flush_warnings(self) -> None:
        """モーダル中に溜めた警告をまとめて読む（同じ内容は1回だけ）。

        ★1回の読み上げにまとめる。1件ずつ割り込みで読むと、後の警告が
        前の警告を切ってしまい、最後の1件しか聞こえない。
        ★読むのは後回しにし、割り込まない。アプリケーションキーの
        メニューで選んだ動作は wx.CallAfter ですぐ後ろに並んでいて、
        そちらも割り込みで喋るので、ここで読み始めると数音節で切られ、
        溜めた分は消えているので二度と読まれない（レビューで判明）。
        """
        pending, self._pending_warnings = self._pending_warnings, []
        seen: set[str] = set()
        msgs: list[str] = []
        for msg in pending:
            if msg in seen:
                continue
            seen.add(msg)
            msgs.append(msg)
        if msgs:
            wx.CallAfter(speech.warn, "。".join(msgs), False)

    def _confirm(self, message: str) -> bool:
        with self.modal():
            dlg = wx.MessageDialog(
                self, message, "確認",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            try:
                return dlg.ShowModal() == wx.ID_YES
            finally:
                dlg.Destroy()

    # ------------------------------------------------------------
    # グローバルホットキー（ウィンドウ非アクティブでも効く）
    # ------------------------------------------------------------
    def _hotkey_actions(self) -> dict:
        """action_id → 実行する処理の対応表。

        ★キーの定義（どの段のどのキーか）は core/keymap.py が持ち、
        ここは「その名前で何をするか」だけを持つ。分けてあるのは、
        キー一覧の読み上げと実際の登録が同じ定義から作られるようにして、
        片方だけ直して食い違うのを防ぐため。

        値がタプルのものは _run_hotkey_action が引数つきで解釈する。
        """
        step = self.config.volume_step_db
        coarse = self.config.volume_coarse_step_db
        return {
            "state": self.announce_state,
            "levels": self.announce_levels,
            # 音量はウィンドウ内では左右キーだが、グローバルでは F1/F2。
            # ★Ctrl+Shift+左右 は全アプリ共通の「単語単位の範囲選択」で、
            #   RegisterHotKey で取るとシステム全体から奪ってしまう
            #   （実測。しかも登録は成功するので警告も出せない）。
            #   F1が左・F2が右にあるので位置関係で覚えられる
            "volume_down": ("vol", -step),
            "volume_up": ("vol", step),
            "volume_next": ("pick", 1),
            "volume_down_coarse": ("vol", -coarse),
            "volume_up_coarse": ("vol", coarse),
            "stats": self.announce_stats,
            "virtual_cam": self.toggle_virtual_cam,
            "replay": self.save_replay,
            # ゲーム切り替えはウィンドウ内の素押し F3 と同じ動作。
            # 前面化を確かめてからダイアログを出す版を使う
            "game": self.open_game_switch_global,
            "bgm": self.toggle_bgm_playback,
            "record_pause": self.toggle_record_pause,
            "chapter": self.add_record_chapter,
            "camera": self.toggle_camera,
            # ★配信はダイアログではなく二度押しで確かめる版（ゲーム中に
            #   ダイアログを出すとゲームから引きはがすため）。録画は
            #   窓内と同じく確認なし
            "stream_start": lambda: self.start_stream(from_global=True),
            "stream_stop": lambda: self.stop_stream(from_global=True),
            "record_start": self.start_record,
            "record_stop": self.stop_record,
        }

    def register_global_hotkeys(self) -> None:
        """設定に従いグローバルホットキーを登録する。

        ★どのキーをどの段に置くかは core/keymap.py が持つ。ここは
        その定義を実際に登録するだけ。ヘルプの「キー操作の一覧」も
        同じ定義から作るので、一覧と実際がずれない。
        見つけた問題は読み上げず _key_problems へ積む（起動時の警告は
        _announce_key_problems が1回にまとめて読む）。
        """
        if not self.config.global_hotkeys_enabled:
            return
        tokens = hotkeys.parse_modifier_tokens(self.config.global_hotkey_modifier)
        # 修飾キーが無いと素のキーをシステム全体で奪ってしまうので登録しない
        if not tokens:
            self._key_problems.append(
                "グローバルホットキーの修飾キーが設定されていないため無効です。"
                "設定で Ctrl+Alt などを指定してください")
            return

        actions = self._hotkey_actions()
        failed: list[str] = []
        for action_id, key_tokens, key_name, desc in keymap.global_bindings(
            self.config
        ):
            if action_id.startswith("sr:"):
                # スクリーンリーダー音声は設定の数だけあるので名前で引く
                name = action_id[3:]
                source = self._sr_by_name.get(name)
                action = ("sr", source) if source else None
            else:
                action = actions.get(action_id)
            if action is None:
                # ★無言で捨てない。keymap に定義があるのに動作が無い＝
                #   キー一覧とメニューには出るのに押しても何も起きない、
                #   という一番見つけにくい壊れ方なので、必ず報告する
                self._key_problems.append(
                    f"{desc}のキーは定義されていますが動作が実装されていません")
                continue
            wxk = KEY_NAME_TO_WXK.get(key_name)
            if wxk is None:
                # keymap が検証済みの今ここへは来ないはずだが、来たら黙らない
                self._key_problems.append(
                    f"{desc}のキー {key_name} を登録できません")
                continue
            modifiers = 0
            for t in key_tokens:
                modifiers |= MOD_TOKEN_TO_WX.get(t, 0)
            id_ref = wx.NewIdRef()
            hid = int(id_ref)
            ok = False
            try:
                fs, vk = hotkeys.win32_hotkey_args(key_tokens, key_name)
                ok = _register_hotkey_norepeat(self.GetHandle(), hid, fs, vk)
            except Exception:  # noqa: BLE001
                # Win32 を直接呼べない（Windows 以外など）。押しっぱなしの
                # 抑止は無くなるが、キー自体は wx で登録する
                try:
                    ok = self.RegisterHotKey(hid, modifiers, wxk)
                except Exception:  # noqa: BLE001
                    ok = False
            if ok:
                self._hotkey_id_refs.append(id_ref)
                self._registered_hotkey_ids.append(hid)
                self.Bind(
                    wx.EVT_HOTKEY,
                    lambda _evt, a=action, aid=action_id:
                        self._run_hotkey_action(a, aid),
                    id=hid,
                )
            else:
                failed.append(hotkeys.hotkey_label(key_tokens, key_name))

        if failed:
            # ★自分の設定の重複で落ちたものを「他のアプリと競合」と
            #   言わない。重複は duplicate_bindings が別の言葉で説明する
            #   （0.14.0 では両方の警告が同じキーを別の原因で読み上げ、
            #   しかも互いに割り込んで聞き取れなかった）
            self_dupes = keymap.duplicate_global_labels(self.config)
            other = [f for f in failed if f not in self_dupes]
            if other:
                self._key_problems.append(
                    "次のグローバルホットキーは登録できませんでした"
                    "（他のアプリと競合の可能性）: " + "、".join(other))

    def _announce_key_problems(self) -> None:
        """キー割り当ての問題を起動時に1回だけまとめて読む。

        対象: 使えないキー名（設定の書き間違い）、同じキーへの二重割り当て
        （全部の段）、他アプリとの競合による登録失敗、動作の実装漏れ。
        ★必ず1回の読み上げにまとめる。speech.warn は割り込みで読むので、
        別々に予約すると後の警告が先の警告を途中で切ってしまい、
        どのキーが駄目だったのか聞き取れなくなる（0.14.0 で実際に起きた）。
        ★グローバルキーが無効でも呼ぶ。窓内のキー（SRキーと固定キー）の
        重複はグローバルの有効無効と関係なく起きる。
        """
        problems: list[str] = []
        if self.config.save_blocked:
            # ★設定ファイルが読めていない。以後どの設定を変えても
            #   保存されないので、起動時に必ず伝える（変えた直後は
            #   成功したように見え、再起動して初めて消えていると分かる）
            problems.append(
                "設定ファイルを読み込めなかったため、既定の設定で動いて"
                "います。このまま設定を変えても保存されません。"
                "obs_navi_config.json を確かめてください")
        problems.extend(keymap.invalid_key_warnings(self.config))
        dupes = keymap.duplicate_bindings(self.config)
        if dupes:
            # ★「後の方は効きません」のような一般則で言わない。段ごとに
            #   勝つ側が違うので、どちらが効くかは keymap が文ごとに言う
            problems.append(
                "同じキーに2つ割り当てられています: " + "、".join(dupes))
        problems.extend(self._key_problems)
        self._key_problems = []
        if not problems:
            return
        # ★起動時の警告も割り込まない。ここで割り込むと、状態欄の名前
        #   （バージョン）や接続の読み上げを途中で切ってしまう。
        #   この関数は起動時にしか呼ばれないので常に後ろへ並べる
        wx.CallLater(1400, speech.warn, "。".join(problems), False)

    def _run_hotkey_action(self, action, action_id: str) -> None:
        """グローバルホットキーから呼ばれる処理を実行する。

        WM_HOTKEY はモーダルダイアログ表示中でも届く。ファイル選択中に
        仮想カメラやリプレイ保存が誤爆しないよう、モーダル中は読み取り
        だけを許す。
        """
        # ★二度押し確認の待ちは、別のキーが届いたら取り消す。断る・早めに
        #   終わる経路より前で、どのキーでも必ず知らせる（0.18.3）。
        #   0.18.2 は配信以外のキーでしか取り消さなかったので、もう一方の
        #   配信キー（すでに配信中で早めに終わる）やモーダル中に断った
        #   キーを挟むと1回目が残り、「停止・開始・停止」で配信が
        #   止まっていた（レビューで判明）
        self._repeat_confirm.note(action_id)
        read_only = action in (self.announce_state, self.announce_levels,
                               self.announce_stats)
        if self._modal_depth > 0 and not read_only:
            speech.speak("今は別の画面を開いています", interrupt=True)
            return
        try:
            if isinstance(action, tuple) and action:
                kind, value = action[0], action[1]
                if kind == "sr":
                    self.toggle_sr_source(value)
                elif kind == "vol":
                    self.adjust_selected_volume(value)
                elif kind == "pick":
                    self.move_input_selection(value)
            elif callable(action):
                action()
        except Exception as exc:  # noqa: BLE001
            # ホットキー経由の例外はどこにも出ないまま無反応になるので拾う
            speech.error(f"操作に失敗しました（{exc}）")

    def unregister_global_hotkeys(self) -> None:
        """登録済みのグローバルホットキーをすべて解除する。"""
        for hid in self._registered_hotkey_ids:
            try:
                self.UnregisterHotKey(hid)
            except Exception:  # noqa: BLE001
                pass
        self._registered_hotkey_ids.clear()
        self._hotkey_id_refs.clear()


    def announce_state(self) -> None:
        if not self.conn.connected:
            speech.speak("OBSに接続していません", interrupt=True)
            return
        self.refresh_from_obs()
        if self.conn.connected:
            speech.speak(
                speech_format.state_summary(self.snapshot), interrupt=True)

    def announce_levels(self) -> None:
        if not self._require_connection():
            return
        # now を渡して、メーターが止まっているときに古い値を読まないようにする
        peaks = self.monitor.current_peaks(time.monotonic())
        cfg = self.config.level_read
        speech.speak(
            speech_format.level_summary(
                peaks, self._muted,
                order=cfg.get("order", ()),
                skip_muted=bool(cfg.get("skip_muted", False))),
            interrupt=True)

    def _save_config(self) -> bool:
        """設定を保存する。書けたら True。

        ★戻り値を見て読み上げを変えること。設定ファイルが読めなかった
        ときは上書きを避けて何もしないので、成功を読み上げると嘘になる
        （再起動して初めて消えていると分かる。耳では確かめようが無い）。
        書けなくても操作自体は続ける（他の保存と同じ方針）。
        """
        try:
            return bool(self.config.save())
        except OSError:
            return False

    def _edit_order(self, title: str, what: str, names, saved,
                    by_name: bool = False, present=None):
        """並べ替えの画面を出し、保存する並びを返す（変えなければ None）。

        3か所（レベル読み上げ・シーン一覧・ソース一覧）で同じ画面を使う。
        ★接続していなくても開ける（先に順番だけ用意しておける）。
        present は「今あるもの」の集合。省略すると names と同じ
        （ソース一覧だけは全シーンぶんを渡す。OrderDialog の説明を参照）。
        """
        names = list(names)
        saved = list(saved)
        if not names and not saved:
            speech.warn("並べ替えられるものがありません")
            return None
        order = None
        with self.modal():
            dlg = prop_dialog.OrderDialog(
                self, title, names, saved, by_name=by_name, what=what,
                present=present)
            try:
                if dlg.ShowModal() == wx.ID_OK:
                    order = dlg.result_order()
            finally:
                dlg.Destroy()
        # ★読み上げはモーダルを抜けてから。中で言うとフォーカス復帰の
        #   読み上げに切られる
        if order is None or list(order) == saved:
            # ★中身が同じなら保存しない。開いて確かめただけなのに
            #   「戻しました」と読まれると、設定を変えたように聞こえる
            speech.speak(
                speech_format.order_unchanged_speech(title), interrupt=True)
            return None
        return order

    def _apply_order(self, holder: dict, key: str, order, title: str,
                     live_names, by_name: bool, refresh=None) -> None:
        """並べ替えの結果を保存して読み上げる（3か所で同じ手順）。

        ★手順を1か所に置く。0.17.3 まで3つの入口が同じ流れを写して
        持っていたので、「今あるものだけ数える」の修正を3か所へ入れる
        羽目になり、1つでも漏れると耳では気づけない状態だった。
        live_names には「今あるもの」を渡す（読み上げる件数と先頭）。
        """
        holder[key] = order
        wrote = self._save_config()
        # ★読み上げは一覧を作り直す前に呼ぶ
        #   （あとにすると、
        #   選択が動いたことによるスクリーンリーダー自身の読み上げに
        #   上書きされる）
        if wrote:
            live = [n for n in order if n in set(live_names)]
            speech.speak(
                speech_format.order_saved_speech(title, order, by_name, live),
                interrupt=True)
        else:
            speech.error(speech_format.config_save_failed_speech(title))
        if refresh is not None:
            refresh()

    def open_level_order(self) -> None:
        """レベル読み上げ(F6)の順番を並べ替える。"""
        title = "レベル読み上げの順番"
        order = self._edit_order(
            title, "読み上げる順番",
            self._input_names,
            self.config.level_read.get("order", ()), by_name=True)
        if order is None:
            return
        self._apply_order(self.config.level_read, "order", order, title,
                          self._input_names, True)

    def _ordered_scenes(self, scenes) -> list:
        """設定の並びへシーン名を寄せる（載っていないものは後ろ）。"""
        return ordering.apply_order(
            scenes, self.config.list_order.get("scenes", ()))

    def open_scene_order(self) -> None:
        """シーン一覧の並び順を変える（OBSナビの中だけ。OBSは変わらない）。

        ★OBS本体のシーンの並びは obs-websocket からは変えられない
        （並べ替えの要求が用意されていない）。ここで変えられるのは
        OBSナビの一覧の並びだけ。
        """
        title = "シーン一覧の並び順"
        order = self._edit_order(
            title, "シーン一覧の順番",
            self.snapshot.scenes,
            self.config.list_order.get("scenes", ()))
        if order is None:
            return
        self._apply_order(self.config.list_order, "scenes", order, title,
                          self.snapshot.scenes, False,
                          refresh=self._refresh_scene_order)

    def _refresh_scene_order(self) -> None:
        """並び順を変えたあとのシーン一覧の作り直し。

        ★選んでいたシーンをそのまま選び直す。現在のシーンへ飛ばしては
        いけない（0.17.2 まではそうなっていて、ソース一覧だけが別の
        シーンのまま残っていた）。選択が動かなければソース一覧はその
        ままでよい（同じ問い合わせを繰り返さない）。
        """
        before = self.scene_list.GetStringSelection()
        self._refresh_scene_list()
        if self.scene_list.GetStringSelection() != before:
            self.refresh_item_list()

    def open_item_order(self) -> None:
        """ソース一覧の並び順を変える（OBSナビの中だけ）。

        ★重なり順は変わらない。映像の前後を変えたいときは
        「ソースを前に出す・後ろに送る」を使う。
        """
        # ★渡すのは「OBSから来た並び」。表示順（並べ替え済み）を渡すと、
        #   画面の「OBSと同じ順に戻す」がカスタム順を復元してしまい、
        #   本当のOBSの重なり順へ戻す手段が無くなる
        title = "ソース一覧の並び順"
        names = [n for n in self._item_obs_names if n]
        saved = list(self.config.list_order.get("items", ()))
        # ★「今あるもの」は全シーンで数える。この設定は全シーンで1つ
        #   なので、今開いているシーンだけで判断すると、他のシーンの
        #   ソースが「今はありません」と読まれ、戻すと消えてしまう。
        #   シーンの数だけ問い合わせるので、無言で待たせないよう先に断る
        if self.conn.connected and len(self.snapshot.scenes) > 1:
            speech.speak("ソース一覧の並び順を開きます", interrupt=True)
        present = self._all_item_names() or set(saved)
        order = self._edit_order(
            title, "ソース一覧の順番", names, saved, present=present)
        if order is None:
            return
        self._apply_order(self.config.list_order, "items", order, title,
                          present, False, refresh=self.refresh_item_list)

    def _all_item_names(self) -> set:
        """すべてのシーンに置かれているソース名の集合。

        ★ソース一覧の並び順は全シーンで1つの設定なので、「今あるもの」も
        全シーンで数える。開いているシーンだけで判断すると、他のシーンの
        ソースが「今はありません」と読まれ、「戻す」で設定ごと消える。
        取れなかったシーンは飛ばす（数え漏らして「今はありません」と
        言う方が、消してしまうより害が小さい）。
        """
        names = {n for n in self._item_obs_names if n}
        if not self.conn.connected:
            return names
        for scene in self.snapshot.scenes:
            ok, items = commands.fetch_scene_items_checked(
                self.conn.req, scene)
            if ok:
                names.update(it.name for it in items)
        return names

    def move_item_layer(self, forward: bool) -> None:
        """ソース一覧で選んでいるソースの重なり順を1段動かす。

        ★重なり順の変更は音に一切影響しない（core/video.py の説明と
        同じ理由で、この操作は安全）。だから種別で候補を絞っていない。
        ★一覧を自分で並べ替えていると行は動かないので、動いた先の位置を
        必ず言葉で読む。
        """
        if not self._require_connection():
            return
        scene = self._item_scene
        item_id = self._selected_item_id()
        if not scene or item_id is None:
            speech.speak(
                "ソース一覧でソースを選んでから実行してください",
                interrupt=True)
            return
        ok, items = commands.fetch_scene_items_checked(self.conn.req, scene)
        if not ok:
            # ★「届かなかった」と「シーンが空」を取り違えない。
            #   ソースはあるのに「見つかりません」と言うと、利用者は
            #   ソースを探し始めてしまう（本当の原因は接続）。一覧も消さない
            speech.error(
                "ソースの一覧を取得できませんでした。"
                "OBSとの接続を確かめてください")
            return
        plan = video.plan_layer_move(items, item_id, forward)
        if plan is None:
            speech.error("ソースが見つかりません")
            self.refresh_item_list()
            return
        if plan.new_index < 0:
            speech.speak(
                speech_format.item_move_edge_speech(plan.name, forward),
                interrupt=True)
            return
        try:
            commands.set_scene_item_index(
                self.conn.req, scene, item_id, plan.new_index)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"重なり順を変えられませんでした（{exc}）")
            return
        # ★ここで作り直さない。OBS が SceneItemListReindexed を返すので
        #   on_scene_item_list_reindexed が同じことをする。両方やると
        #   1打鍵につき取得が3回になり、読み上げが詰まる
        speech.speak(
            speech_format.item_moved_speech(
                plan.name, plan.pos_from_front, plan.total, forward),
            interrupt=True)

    def set_skip_muted(self, skip: bool) -> None:
        """ミュート中のソースをレベル読み上げから外すかを切り替える。"""
        skip = bool(skip)
        self.config.level_read["skip_muted"] = skip
        if not self._save_config():
            speech.error(speech_format.config_save_failed_speech(
                "ミュート中のソースの設定"))
            return
        speech.speak(speech_format.skip_muted_speech(skip), interrupt=True)

    def toggle_sr_source(self, source: dict) -> None:
        """スクリーンリーダー音声ソースの配信オン・オフを切り替える。

        入力が無ければ作成するか確認してから作る。あればミュートを切替。
        """
        if not self._require_connection():
            return
        name = source["name"]
        if self.snapshot.input_by_name(name) is None:
            # ここから確認ダイアログを出す。グローバルキー経由でウィンドウが
            # 背面のままだと「見えない・読まれないダイアログ」に閉じ込めて
            # しまうので、ゲーム切り替え・BGMと同じ前面ガードを通す。
            if not self._ready_for_dialog():
                return
            target = self._source_target_label(source)
            if self._confirm(
                f"入力「{name}」がありません。"
                f"{target}の音声を配信に乗せるための入力を作成しますか？"
            ):
                self.create_sr_source(source)
            return
        try:
            commands.toggle_mute(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"切り替えに失敗しました（{exc}）")

    def _source_target_label(self, source: dict) -> str:
        """ソースの捕捉対象を表す短い文字列（確認・警告用）。"""
        if source.get("method") == "device":
            return source.get("device_match", "対象デバイス")
        return source.get("exe", "対象アプリ")

    def create_sr_source(self, source: dict) -> None:
        """ソースの方式に応じてスクリーンリーダー音声入力を作成する。"""
        if not self._require_connection():
            return
        name = source["name"]
        # ★キー名は keymap から引く（設定の生の値を読み上げない）。
        #   使えないキー名や未設定のまま読むと「（無言）をもう一度押すと」
        #   「Delete をもう一度押すと」のような、押しても効かない案内に
        #   なる。キーが無いときはメニューから辿れることを言う
        key = keymap.sr_key_label(self.config, name)
        again = f"{key}をもう一度押すと" if key else "音声メニューでもう一度選ぶと"
        retry = (f"もう一度 {key} を押してください" if key
                 else "音声メニューからもう一度選んでください")
        target = self._source_target_label(source)
        scene = self.snapshot.current_scene
        if not scene:
            speech.error("現在のシーンが取得できないため作成できません")
            return
        # 作成に伴うミュートイベントの読み上げを1回抑止する
        self._sr_setup_pending.add(name)
        try:
            value = setup.create_sr_source_input(self.conn.req, scene, source)
        except Exception as exc:  # noqa: BLE001
            self._sr_setup_pending.discard(name)
            speech.error(f"入力の作成に失敗しました（{exc}）")
            return
        self.refresh_from_obs()
        if value:
            speech.speak(
                f"{name}の入力を作成しました。今はミュート状態です。"
                f"{again}配信に乗せます", interrupt=True)
            # 万一ミュートイベントが届かなくても抑止フラグを残さない
            # （残ると、次の手動トグル1回ぶんの読み上げが無言になる）
            wx.CallLater(3000, self._sr_setup_pending.discard, name)
        else:
            # 対象が見つからず入力は作られていない（作りかけは削除済み）
            self._sr_setup_pending.discard(name)
            if source.get("method") == "device":
                speech.warn(
                    f"録音デバイス {target} が見つかりませんでした。"
                    f"仮想ケーブルが有効か確認してから、{retry}")
            else:
                speech.warn(
                    f"対象の {target} が見つかりませんでした。"
                    f"{target} のアプリを起動してから、{retry}")


    def _confirm_by_repeat(self, action_id: str, what: str) -> bool:
        """グローバルキー用の確認。同じキーを続けて2回押したら True。

        1回目は「もう一度押すと〜します」と読むだけで何もしない。
        ダイアログを出さないので、ゲームの画面から離れずに済む。
        """
        if self._repeat_confirm.press(action_id, time.monotonic()):
            # ★決まったらすぐ言う（0.18.3）。黙っていると1回目の案内が
            #   流れ続け、OBS から開始の知らせが届くまで（Twitch への接続で
            #   数秒）効いたか分からない。toggle_camera と同じ理由
            speech.speak(f"{what}します", interrupt=True)
            return True
        # ★案内は短く（0.18.3）。キー名と秒数を入れた 0.18.2 の案内は
        #   読み終えるのに6〜7秒かかり、聞き終えたときには猶予が切れて
        #   いた（レビューで判明）。押したキーは本人が知っている
        speech.speak(f"もう一度押すと{what}します", interrupt=True)
        return False

    def start_stream(self, from_global: bool = False) -> None:
        if not self._require_connection():
            return
        if self.snapshot.streaming:
            speech.speak("すでに配信中です")
            return
        if from_global:
            if not self._confirm_by_repeat("stream_start", "配信を開始"):
                return
        elif not self._confirm("配信を開始しますか？"):
            return
        try:
            commands.start_stream(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"配信開始に失敗しました（{exc}）")

    def stop_stream(self, from_global: bool = False) -> None:
        if not self._require_connection():
            return
        if not self.snapshot.streaming:
            speech.speak("配信は停止しています")
            return
        if from_global:
            if not self._confirm_by_repeat("stream_stop", "配信を停止"):
                return
        elif not self._confirm("配信を停止しますか？"):
            return
        try:
            commands.stop_stream(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"配信停止に失敗しました（{exc}）")

    def start_record(self) -> None:
        if not self._require_connection():
            return
        if self.snapshot.recording:
            speech.speak("すでに録画中です")
            return
        try:
            commands.start_record(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"録画開始に失敗しました（{exc}）")

    def stop_record(self) -> None:
        if not self._require_connection():
            return
        if not self.snapshot.recording:
            speech.speak("録画は停止しています")
            return
        try:
            commands.stop_record(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"録画停止に失敗しました（{exc}）")

    def activate_selected_scene(self) -> None:
        """シーン一覧で選択中のシーンへ切り替える。"""
        if not self._require_connection():
            return
        idx = self.scene_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self.scene_list.GetString(idx)
        if name == self.snapshot.current_scene:
            speech.speak(f"すでにシーン {name} です", interrupt=True)
            return
        try:
            commands.set_scene(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"シーン切り替えに失敗しました（{exc}）")

    def toggle_selected_input(self) -> None:
        """音声入力一覧で選択中の入力のミュートを切り替える。"""
        if not self._require_connection():
            return
        idx = self.input_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._input_names):
            return
        name = self._input_names[idx]
        try:
            commands.toggle_mute(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"ミュート切り替えに失敗しました（{exc}）")

    # ------------------------------------------------------------
    # 音量
    # ------------------------------------------------------------
    def _selected_input_name(self) -> str:
        """音声入力一覧で選択中の入力名。無ければ空文字。"""
        idx = self.input_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._input_names):
            return ""
        return self._input_names[idx]

    def adjust_selected_volume(self, delta_db: float) -> None:
        """選択中の入力の音量を delta_db ぶん動かす。

        読み上げはしない。OBSの InputVolumeChanged イベントが飛んでくるので、
        そちらで一元的に読む（ミュートと同じ作り。OBS本体側で変えたときも
        同じように読まれ、二重にも無にもならない）。
        """
        if not self._require_connection():
            return
        name = self._selected_input_name()
        if not name:
            return
        current = commands.fetch_volume_db(self.conn.req, name)
        if current is None:
            speech.error(f"{name} の音量が取得できません")
            return
        target = volume.next_db(current, delta_db, self.config.volume_step_db)
        if target == current:
            # 値が動かないときは OBS に投げても InputVolumeChanged が飛ばず
            # 無反応になるので、ここで理由を読む。
            # 端に着いているとは限らない（設定の刻みが0など）ので決めつけない。
            if current >= volume.VOLUME_MAX_DB:
                speech.speak(
                    f"{name} はこれ以上上げられません。最大です", interrupt=True)
            elif current <= volume.VOLUME_MIN_DB:
                speech.speak(
                    f"{name} はこれ以上下げられません。最小です", interrupt=True)
            else:
                speech.speak(
                    speech_format.volume_speech(name, current), interrupt=True)
            return
        try:
            commands.set_volume_db(self.conn.req, name, target)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"音量の変更に失敗しました（{exc}）")

    def announce_selected_volume(self) -> None:
        """選択中の入力の名前と音量を読む（対象を切り替えたときに使う）。"""
        if not self._require_connection():
            return
        name = self._selected_input_name()
        if not name:
            speech.speak("音声入力がありません", interrupt=True)
            return
        current = commands.fetch_volume_db(self.conn.req, name)
        if current is None:
            speech.speak(f"{name} 音量不明", interrupt=True)
            return
        speech.speak(speech_format.volume_speech(name, current), interrupt=True)

    def move_input_selection(self, delta: int) -> None:
        """音声入力一覧の選択を動かし、名前と音量を読む。

        グローバルホットキーから使う。ウィンドウが見えていなくても
        「今どれを触っているか」が分かるように、名前と音量を必ず読む。
        """
        count = self.input_list.GetCount()
        if count == 0:
            speech.speak("音声入力がありません", interrupt=True)
            return
        idx = self.input_list.GetSelection()
        if idx == wx.NOT_FOUND:
            idx = 0
        else:
            idx = (idx + delta) % count
        self.input_list.SetSelection(idx)
        # SetSelection は EVT_LISTBOX を発火しないので、フィルター一覧は
        # 自分で追従させる（ウィンドウへ戻ったときに前の入力のフィルターが
        # 出たままになるのを防ぐ）。
        # ★追従先も自分で切り替える。0.17.3 は「最後に選択を動かした
        #   リスト」で決めるようにしたが、ここは EVT_LISTBOX を通らない
        #   ので、ソース一覧を触ったあとだと追従先が変わらず、
        #   読み上げた入力とフィルターの操作先が食い違っていた
        self._filter_follow = self.input_list
        self._last_list = self.input_list
        self.refresh_filter_list()
        self.announce_selected_volume()

    def prompt_selected_volume(self) -> None:
        """選択中の入力の音量を数値で入力して設定する。"""
        if not self._require_connection():
            return
        name = self._selected_input_name()
        if not name:
            speech.speak("音声入力がありません", interrupt=True)
            return
        current = commands.fetch_volume_db(self.conn.req, name)
        if current is None:
            speech.error(f"{name} の音量が取得できません")
            return
        message = (
            f"{name} の音量をデシベルで入力してください。\n"
            f"今は {speech_format.fmt_volume_db(current)} です。\n"
            f"入力できる範囲は {int(volume.VOLUME_MIN_DB)} から "
            f"{int(volume.VOLUME_MAX_DB)} までです。")
        with self.modal():
            dlg = wx.TextEntryDialog(
                self, message, "音量の設定", value=str(round(current, 1)))
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                text = dlg.GetValue()
            finally:
                dlg.Destroy()
        target = volume.parse_db_input(text)
        if target is None:
            speech.error(
                "数値として読み取れませんでした。5 や マイナス10 のように"
                "入力してください")
            return
        if target == current:
            speech.speak(
                speech_format.volume_speech(name, current), interrupt=True)
            return
        try:
            commands.set_volume_db(self.conn.req, name, target)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"音量の変更に失敗しました（{exc}）")

    # ------------------------------------------------------------
    # フィルター（ソース一覧・音声入力一覧で選択中のソースのフィルター）
    # ------------------------------------------------------------
    def refresh_filter_list(self, announce: bool = False) -> None:
        """選択中のソースのフィルター一覧を作り直す。

        ★対象は「最後に触っていたリスト」で決める（0.16.0）。
        0.15.0 までは音声入力一覧だけを見ていたので、音を持たない
        ソース（ゲームキャプチャや画像）のフィルターには
        **どこからも辿り着けなかった**。ソース一覧からも触れるように、
        設定を開くときと同じ _props_target() を使う。

        announce=True のとき、対象ソース名を短く読み上げる（対象が
        変わったことを知らせる）。フィルターが無いソースも多いので、
        「フィルター無し」も分かるようにする。
        """
        name = self._filter_source_target()
        # イベント駆動の作り直しで選択が先頭へ飛ばないよう、同じ対象の
        # 作り直しなら選択中のフィルター名を覚えて選び直す
        prev_idx = self.filter_list.GetSelection()
        prev_source = self._filter_source
        prev_name = (self._filter_names[prev_idx]
                     if name == self._filter_source
                     and 0 <= prev_idx < len(self._filter_names) else None)
        self._filter_source = name
        if not name or not self.conn.connected:
            self._filter_names = []
            self.filter_list.Set([])
            self.lbl_filters.SetLabel("フィルター一覧（Enterでオン・オフ）")
            return
        # ★変数名を filters にしない。core.filters モジュールを
        #   関数の中で隠してしまう（同名のローカルがあると、その関数の
        #   中では最後までローカル扱いになる）
        try:
            ok, found = commands.fetch_source_filters_checked(
                self.conn.req, name)
        except Exception:  # noqa: BLE001
            ok, found = False, []
        if not ok and name == prev_source and self._filter_names:
            # ★届かなかっただけ。見えていた一覧を消さない（消すと
            #   「フィルターが無くなった」と誤解する。実際はある）
            return
        self._filter_names = [f.name for f in found]
        self.filter_list.Set([
            speech_format.filter_list_label(f.name, f.enabled)
            for f in found
        ])
        if found:
            if prev_name in self._filter_names:
                self.filter_list.SetSelection(
                    self._filter_names.index(prev_name))
            else:
                self.filter_list.SetSelection(0)
        self.lbl_filters.SetLabel(
            f"{name} のフィルター一覧（Enterでオン・オフ）")
        if announce:
            if found:
                speech.speak(
                    f"{name} のフィルター {len(found)} 件", interrupt=True)
            else:
                # 足せることまで言う（0.11.0 で追加できるようになったため、
                # 「ありません」で終わると打つ手が無いように聞こえる）
                speech.speak(
                    speech_format.filter_none_speech(name), interrupt=True)

    def toggle_selected_filter(self) -> None:
        """フィルター一覧で選択中のフィルターのオン・オフを切り替える。

        読み上げは OBS の SourceFilterEnableStateChanged イベント経由で
        一元化する（ミュートと同じ作り。ここでは操作を投げるだけ）。
        """
        if not self._require_connection():
            return
        if not self._filter_list_ready():
            return
        idx = self.filter_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._filter_names):
            return
        source = self._filter_source
        fname = self._filter_names[idx]
        # 今の状態を反転させる。現在値は表示ラベルから取らず OBS から取り直す
        ok, found = commands.fetch_source_filters_checked(
            self.conn.req, source)
        if not ok:
            # ★接続の問題を「見つかりません」と言わない（一覧も消さない）
            speech.error(
                "フィルターの一覧を取得できませんでした。"
                "OBSとの接続を確かめてください")
            return
        current = next((f for f in found if f.name == fname), None)
        if current is None:
            speech.error("フィルターが見つかりません")
            self.refresh_filter_list()
            return
        try:
            commands.set_filter_enabled(
                self.conn.req, source, fname, not current.enabled)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"フィルターの切り替えに失敗しました（{exc}）")

    def on_input_selected(self, _evt: wx.CommandEvent) -> None:
        """音声入力一覧で選択を動かしたら、フィルター一覧を追従させる。"""
        self._filter_follow = self.input_list
        self._last_list = self.input_list
        self._schedule_filter_refresh()

    def on_item_selected(self, _evt: wx.CommandEvent) -> None:
        """ソース一覧で選択を動かしたら、フィルター一覧を追従させる。"""
        self._filter_follow = self.item_list
        self._last_list = self.item_list
        self._schedule_filter_refresh()

    def _filter_source_target(self) -> str:
        """フィルター一覧が追従すべきソース名。

        ★「最後に**選択を動かした**リスト」で決める（0.17.3）。
        フォーカスで決めていた 0.16.0〜0.17.2 には穴があった:
        タブ順は ソース一覧 → 音声入力一覧 → フィルター一覧 なので、
        ソース一覧で選んだ映像ソースのフィルターを見にいこうとすると、
        **途中で必ず音声入力一覧を通り、そこで対象がすり替わっていた**。
        画面が見えないと気づけず、Enterで別のソースのフィルターを
        切り替えてしまう。通り過ぎるだけでは対象を変えない。
        """
        if self._filter_follow is self.item_list:
            return self._selected_item_name()
        if self._filter_follow is self.input_list:
            return self._selected_input_name()
        # まだどちらの選択も動かしていない（起動直後）。今いる場所で決める
        return self._props_target()

    def _cancel_filter_refresh(self) -> None:
        """予約してあるフィルター一覧の作り直しを取り消す。"""
        self._filter_timer.Stop()

    def _schedule_filter_refresh(self) -> None:
        """少し待ってからフィルター一覧を作り直す（FILTER_REFRESH_DELAY_MS）。

        ★矢印キーで一覧を辿るたびにOBSへ問い合わせると、1打鍵ごとに
        通信待ちが入って行の読み上げが詰まる。押し終わってから1回だけ聞く。
        （StartOnce は動いていれば取り直すので、押し続けている間は延びる）
        """
        self._filter_timer.StartOnce(FILTER_REFRESH_DELAY_MS)

    def _on_filter_refresh_timer(self, _evt) -> None:
        self.refresh_filter_list()

    def _sync_filter_target(self) -> bool:
        """フィルター一覧を今の対象へ合わせる。合っていれば True。

        ★操作の直前に呼ぶためのもの。予約中の作り直しがあれば取り消して、
        その場で作り直す（0.17.3 は 250ms の待ちを入れたので、待っている
        間に Tab して Enter を押すと**前のソースのフィルターが切り替わって
        いた**。読み上げはフィルター名しか言わないので気づけない）。

        ★作り直したときは False を返す。ここでは何も読み上げない
        （一覧の作り直しは頻繁に起きるので、毎回喋ると邪魔になる）。
        選んだフィルターに対して何かする前は _filter_list_ready() を
        通すこと。
        """
        self._cancel_filter_refresh()
        if self._filter_source_target() == self._filter_source:
            return True
        self.refresh_filter_list()
        return False

    def _filter_list_ready(self) -> bool:
        """選んだフィルターを操作してよいか（対象を合わせてから判断する）。

        ★作り直しが起きたら断る。利用者が耳で確かめたのは作り直す前の
        一覧で、選択は先頭へ移っている。そのまま続けると、聞いていない
        フィルターを切り替える・削除することになる（読み上げはフィルター名
        しか言わないので、間違いに気づけない）。
        """
        if self._sync_filter_target():
            return True
        source = self._filter_source
        speech.warn(
            f"{source} のフィルター一覧に切り替えました。選び直してください"
            if source else "フィルターの対象が変わりました。選び直してください")
        return False

    # ------------------------------------------------------------
    # フィルターの追加・設定・削除
    # ------------------------------------------------------------
    def _selected_filter_name(self) -> str:
        """フィルター一覧で選択中のフィルター名。無ければ空文字。"""
        idx = self.filter_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._filter_names):
            return ""
        return self._filter_names[idx]

    def _filter_target(self) -> str:
        """フィルターを付ける対象のソース名。

        フィルター一覧はソース一覧・音声入力一覧の選択に追従しているので、
        表示中の対象（_filter_source）がそのまま操作対象になる。
        """
        return self._filter_source

    def open_filter_props(self) -> None:
        """フィルター一覧で選択中のフィルターの設定を開く。

        OBS本体のフィルター画面はスクリーンリーダーで読めない
        （このプロジェクトの出発点にある弱点）。ここで中身を触れるようにする。
        """
        if not self._require_connection():
            return
        if not self._filter_list_ready():
            return
        source = self._filter_target()
        fname = self._selected_filter_name()
        if not source or not fname:
            speech.speak(
                "フィルター一覧でフィルターを選んでから実行してください",
                interrupt=True)
            return
        speech.speak(f"{fname} の設定を開きます", interrupt=True)
        with self.modal():
            dlg = prop_dialog.FilterPropDialog(self, source, fname)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()
        self.refresh_filter_list()

    def apply_filter_change(
        self, source: str, filter_name: str, patch: dict, spec
    ) -> bool:
        """フィルターの設定を変え、読み直して結果を読み上げる。

        ★入力の設定と違い、フィルターには設定変更のイベントが無い
        （obs-websocket 5.7.3 に SourceFilterSettingsChanged は存在しない。
        実測で確認）。したがってイベント駆動の一元化は使えず、ここで
        読み直して確かめる。投げた直後に読み直せば確定していることも実測済み。

        spec が None のときは「既定値へ戻す」など複数キーの一括変更なので、
        個別の読み上げは呼び出し側が行う。
        """
        if not self._require_connection():
            return False
        try:
            commands.apply_filter_settings(
                self.conn.req, source, filter_name, patch)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"フィルターの設定に失敗しました（{exc}）")
            return False
        if spec is None:
            return True
        # 本当に変わったかを読み直して確かめる（黙って効かないのを防ぐ）
        _kind, after = commands.fetch_merged_filter_settings(
            self.conn.req, source, filter_name)
        want = patch.get(spec.key)
        got = after.get(spec.key)
        if got != want and not _close_enough(got, want):
            speech.warn(
                speech_format.filter_prop_unchanged_speech(filter_name, spec))
            return True
        speech.speak(
            speech_format.filter_prop_changed_speech(filter_name, spec, got),
            interrupt=True)
        return True

    def add_filter(self) -> None:
        """選択中のソースにフィルターを追加する。

        ★実行の直前に対象を合わせる。メニューバーから呼ばれたときや、
        シーンが切り替わった直後は、フィルター一覧がまだ前のソースを
        指していることがあり、そのまま足すと別のソースへ付いてしまう。
        """
        if not self._require_connection():
            return
        self._sync_filter_target()
        source = self._filter_target()
        if not source:
            speech.speak(
                "音声入力一覧でソースを選んでから実行してください",
                interrupt=True)
            return
        # ★追加できるのは音声フィルターだけ。音を持たないソースに
        #   音声フィルターを足しても何も起きないので、候補を出さずに断る
        #   （「作れないものを候補に出さない」= core/filters.py と同じ方針）。
        #   映像フィルターの追加は未対応
        if source not in self._input_names:
            speech.warn(
                f"{source} は音声を持たないソースです。"
                "追加できるのは音声フィルターだけなので、ここでは足せません。"
                "既にあるフィルターの確認・オン・オフ・削除はできます")
            return
        if not self._ready_for_dialog():
            return
        kinds = filters.AUDIO_FILTER_KINDS
        rows = [speech_format.filter_kind_row(k) for k in kinds]
        sel = next((i for i, k in enumerate(kinds)
                    if k.kind == filters.RECOMMENDED_FIRST), 0)
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{source} に追加するフィルター、{len(rows)}件",
                "フィルターを追加", rows)
            try:
                if 0 <= sel < len(rows):
                    dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        if not (0 <= idx < len(kinds)):
            return
        info = kinds[idx]
        # 同じ種別を2つ足すのは正当（段の違うコンプレッサーなど）なので、
        # 名前だけ空いているものにする
        existing = [f.name for f in
                    commands.fetch_source_filters(self.conn.req, source)]
        name = filters.free_filter_name(info.label, existing)
        try:
            commands.create_filter(self.conn.req, source, name, info.kind)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"フィルターの追加に失敗しました（{exc}）")
            return
        self.refresh_filter_list()
        # 作られたことを実際に確かめてから言う（作れない種別があるため）
        made = [f.name for f in
                commands.fetch_source_filters(self.conn.req, source)]
        if name not in made:
            speech.warn(
                f"{info.label} を追加できませんでした。"
                "OBSがこの種類のフィルターを作れないようです")
            return
        if name in self._filter_names:
            self.filter_list.SetSelection(self._filter_names.index(name))
        speech.speak(
            speech_format.filter_added_speech(name, source), interrupt=True)

    def remove_filter(self) -> None:
        """フィルター一覧で選択中のフィルターを削除する。"""
        if not self._require_connection():
            return
        if not self._filter_list_ready():
            return
        source = self._filter_target()
        fname = self._selected_filter_name()
        if not source or not fname:
            speech.speak(
                "フィルター一覧でフィルターを選んでから実行してください",
                interrupt=True)
            return
        if not self._ready_for_dialog():
            return
        # 削除は取り消せないので必ず確認する
        if not self._confirm(
            f"{source} のフィルター「{fname}」を削除しますか？"
        ):
            return
        try:
            commands.remove_filter(self.conn.req, source, fname)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"フィルターの削除に失敗しました（{exc}）")
            return
        self.refresh_filter_list()
        speech.speak(
            speech_format.filter_removed_speech(fname, source), interrupt=True)

    # ------------------------------------------------------------
    # シーン内ソースの表示・非表示（シーン一覧で選択中のシーンが対象）
    # ------------------------------------------------------------
    def refresh_item_list(self, announce: bool = False,
                          sync_filters: bool = True) -> None:
        """シーン一覧で選択中のシーンのソース一覧を作り直す。

        sync_filters=False は、呼んだ直後にフィルター一覧を必ず作り直す
        場合だけに使う（同じ問い合わせを2回しないため）。
        """
        idx = self.scene_list.GetSelection()
        scene = ""
        if idx != wx.NOT_FOUND:
            scene = self.scene_list.GetString(idx)
        # イベント駆動の作り直しで選択が先頭へ飛ばないよう、同じシーンの
        # 作り直しなら選択中の item_id を覚えて選び直す
        prev_idx = self.item_list.GetSelection()
        prev_scene = self._item_scene
        prev_id = (self._item_ids[prev_idx]
                   if scene == self._item_scene
                   and 0 <= prev_idx < len(self._item_ids) else None)
        self._item_scene = scene
        if not scene or not self.conn.connected:
            self._item_ids = []
            self._item_names = {}
            self._item_obs_names = []
            self.item_list.Set([])
            self.lbl_items.SetLabel("ソース一覧（Enterで表示・非表示）")
            if sync_filters:
                self._sync_filter_target()
            return
        try:
            ok, items = commands.fetch_scene_items_checked(
                self.conn.req, scene)
        except Exception:  # noqa: BLE001
            ok, items = False, []
        if not ok and scene == prev_scene and self._item_ids:
            # ★届かなかっただけ。見えていた一覧を消さない（消すと
            #   「ソースが無くなった」と誤解する。実際はある）
            if sync_filters:
                self._sync_filter_target()
            return
        # ★並べ替える前のOBSの並びを覚えておく。並べ替え画面の
        #   「OBSと同じ順に戻す」はこれを基準にする（表示順を基準に
        #   すると、カスタム順を「OBS順」として復元してしまう）
        self._item_obs_names = [it.name for it in items]
        # ★OBSから来る並びは重なり順（手前が先頭）。設定で並べ替えている
        #   ときはその意味が読み取れなくなるので、重なり順を知りたい／
        #   変えたいときは「前に出す・後ろに送る」を使う（読み上げで位置を言う）
        items = ordering.apply_order_by(
            items, self.config.list_order.get("items", ()),
            key=lambda it: it.name)
        self._item_ids = [it.item_id for it in items]
        self._item_names = {it.item_id: it.name for it in items}
        self.item_list.Set([
            speech_format.scene_item_list_label(it.name, it.enabled)
            for it in items
        ])
        if items:
            if prev_id in self._item_ids:
                self.item_list.SetSelection(self._item_ids.index(prev_id))
            else:
                self.item_list.SetSelection(0)
        self.lbl_items.SetLabel(
            f"{scene} のソース一覧（Enterで表示・非表示）")
        if announce:
            speech.speak(f"{scene} のソース {len(items)} 件", interrupt=True)
        # 選択が動いていれば（シーン切り替え・ソースの増減など）、
        # フィルター一覧の対象も合わせる
        if sync_filters:
            self._sync_filter_target()

    def toggle_selected_item(self) -> None:
        """ソース一覧で選択中のソースの表示・非表示を切り替える。

        読み上げは SceneItemEnableStateChanged イベント経由で一元化する。
        """
        if not self._require_connection():
            return
        item_id = self._selected_item_id()
        if item_id is None:
            return
        scene = self._item_scene
        # 現在値を OBS から取り直して反転させる
        ok, items = commands.fetch_scene_items_checked(self.conn.req, scene)
        if not ok:
            # ★接続の問題を「ソースが見つかりません」と言わない
            #   （言うと一覧まで消えて、探す先を間違える）
            speech.error(
                "ソースの一覧を取得できませんでした。"
                "OBSとの接続を確かめてください")
            return
        current = next((it for it in items if it.item_id == item_id), None)
        if current is None:
            speech.error("ソースが見つかりません")
            self.refresh_item_list()
            return
        try:
            commands.set_scene_item_enabled(
                self.conn.req, scene, item_id, not current.enabled)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"表示の切り替えに失敗しました（{exc}）")

    def on_scene_selected(self, _evt: wx.CommandEvent) -> None:
        """シーン一覧の選択が変わったらソース一覧を追従させる。

        ★フィルター一覧はここでは合わせない（待ってから1回だけ）。
        矢印でシーンを辿るたびに同期すると、1打鍵につきソース一覧と
        フィルター一覧で2回の通信待ちが入り、行の読み上げが詰まる
        （0.17.3 が音声入力・ソース一覧で消した詰まりが、シーン一覧では
        むしろ増えていた）。
        """
        self.refresh_item_list(sync_filters=False)
        self._schedule_filter_refresh()

    # ------------------------------------------------------------
    # 便利機能（仮想カメラ・リプレイ保存・録画一時停止・統計）
    # ------------------------------------------------------------
    def toggle_virtual_cam(self) -> None:
        """仮想カメラのオン・オフを切り替える。

        読み上げは VirtualcamStateChanged イベント経由で一元化する。
        """
        if not self._require_connection():
            return
        try:
            commands.toggle_virtual_cam(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"仮想カメラの切り替えに失敗しました（{exc}）")

    def toggle_record_pause(self) -> None:
        """録画の一時停止・再開を切り替える。"""
        if not self._require_connection():
            return
        if not self.snapshot.recording:
            speech.speak("録画していません", interrupt=True)
            return
        try:
            commands.toggle_record_pause(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"録画の一時停止に失敗しました（{exc}）")

    def save_replay(self) -> None:
        """リプレイバッファを保存する（直近の数十秒をファイルへ）。

        ★保存が終わったことは読み上げない。OBSの保存は非同期で、要求が
        通った時点ではまだ書けていないため（「保存しました」が嘘になり得る）。
        完了は ReplayBufferSaved イベントで読む。届かなかったときのために
        _settle_replay で保険を張る（設定変更の合流と同じ考え方）。
        """
        if not self._require_connection():
            return
        try:
            commands.save_replay_buffer(self.conn.req)
            self._replay_pending = True
            wx.CallLater(REPLAY_SETTLE_MS, self._settle_replay)
        except commands.ReplayBufferStarting:
            speech.speak(
                "リプレイバッファを起動しました。数十秒待ってから、"
                "もう一度リプレイ保存を実行してください", interrupt=True)
        except commands.ReplayBufferUnavailable:
            speech.warn(
                "リプレイバッファが無効です。OBSの設定、出力、リプレイバッファ"
                "で有効にしてください")
        except Exception as exc:  # noqa: BLE001
            speech.error(f"リプレイの保存に失敗しました（{exc}）")

    def _settle_replay(self) -> None:
        """リプレイ保存の完了イベントが届かなかったときの保険。

        イベントが来ていれば _apply_replay_saved がフラグを下ろしている
        ので、ここは何もしない。
        """
        if not self or not self._replay_pending:
            return
        self._replay_pending = False
        speech.speak(speech_format.replay_saved_speech(), interrupt=True)

    def announce_stats(self) -> None:
        """OBSの統計（CPU・コマ落ち・空き容量など）を読み上げる。"""
        if not self._require_connection():
            return
        stats = commands.fetch_stats(self.conn.req)
        speech.speak(speech_format.stats_summary(stats), interrupt=True)

    # ------------------------------------------------------------
    # 録画（一時停止の見張り・チャプター・設定の確認・保存先を開く）
    # ------------------------------------------------------------
    def _announce_file_name(self) -> bool:
        """録画停止・リプレイ保存でファイル名を読むか（設定）。"""
        return bool(self.config.record.get("announce_file_name", True))

    def _sync_record_watch(self) -> None:
        """録画中だけ見張りタイマーを回す。

        止めるときに見張り側の状態も畳む。畳まないと、次の録画で
        「前の録画のときに警告済み」の記録が残って警告が出なくなる。
        """
        if self.conn.connected and self.snapshot.recording:
            self._start_record_watch()
            return
        self._stop_record_watch()
        self.pause_reminder.reset()
        self.disk_watch.reset()

    def _start_record_watch(self) -> None:
        if self._record_timer is None:
            self._record_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_record_tick, self._record_timer)
        if not self._record_timer.IsRunning():
            # 録画を始めた直後に1回は空き容量を見る（開始時点で既に
            # 足りない、を録り終わってから知るのでは遅い）
            self._last_disk_check = 0.0
            self._record_timer.Start(RECORD_TICK_MS)

    def _stop_record_watch(self) -> None:
        if self._record_timer is not None and self._record_timer.IsRunning():
            self._record_timer.Stop()

    def on_record_tick(self, _evt) -> None:
        """録画中の見張り（一時停止の放置・空き容量）。

        タイマーはモーダル表示中も発火するが、読み上げは _emit_warning を
        通すのでダイアログ操作中は溜められ、閉じたあとにまとめて読まれる。
        """
        if not self.conn.connected or not self.snapshot.recording:
            self._sync_record_watch()
            return
        now = time.monotonic()
        elapsed = self.pause_reminder.tick(now)
        if elapsed is not None:
            self._emit_warning(speech_format.pause_reminder_speech(elapsed))
        interval = float(
            self.config.record.get("disk_check_seconds", 60.0) or 0.0)
        if interval > 0 and (now - self._last_disk_check) >= interval:
            self._last_disk_check = now
            self._check_disk_space()

    def _check_disk_space(self) -> None:
        """空き容量を1回見て、段階が上がっていれば知らせる。

        obs-websocket に残量のイベントは無いのでポーリングになる。
        既定60秒なら負荷は無視できる。
        """
        stats = commands.fetch_stats(self.conn.req)
        free = stats.get("disk_free_mb")
        if not isinstance(free, (int, float)):
            return
        level = self.disk_watch.check(free)
        if level != recording.DISK_OK:
            self._emit_warning(speech_format.disk_warning_speech(level, free))

    # ------------------------------------------------------------
    # カメラ（映像キャプチャデバイス）
    # ------------------------------------------------------------
    def announce_cameras(self) -> None:
        """カメラの状態をまとめて読む（確認だけ。何も変えない）。

        ★見えない利用者にとって、カメラが動いているかは読み上げでしか
        分からない（本体のランプが判断材料にならない）。確認の手段を
        切り替えと分けてあるのは、確かめたいだけのときに誤って
        切り替えてしまわないようにするため。
        """
        if not self._require_connection():
            return
        speech.speak("カメラを確認します", interrupt=True)
        try:
            names = commands.fetch_camera_names(self.conn.req)
            scene = self.snapshot.current_scene
            states = [commands.fetch_camera_state(self.conn.req, n, scene)
                      for n in names]
            unused = commands.fetch_unused_camera_devices(self.conn.req, names)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"カメラの状態を取得できませんでした（{exc}）")
            return
        speech.speak(
            speech_format.camera_list_speech(states, unused), interrupt=True)

    def _pick_camera(self) -> str:
        """操作するカメラを決める。1台ならそれ、複数なら選ばせる。"""
        names = commands.fetch_camera_names(self.conn.req)
        if not names:
            speech.warn(speech_format.camera_none_speech())
            return ""
        if len(names) == 1:
            return names[0]
        if not self._ready_for_dialog():
            return ""
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"切り替えるカメラ、{len(names)}件", "カメラ", names)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return ""
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        return names[idx] if 0 <= idx < len(names) else ""

    def toggle_camera(self) -> None:
        """カメラの有効・無効を切り替える。

        ★設定 active を書いてはいけない。書いても値が変わるだけで
        デバイスは止まらない（実測で確認。core/camera.py の冒頭）。
        必ずプロパティのボタンを押す。

        ボタンは押すたびに反転するので、押す前の状態を読んでからでないと
        結果が分からない。切り替えにはイベントが飛ばないので、
        待ってから読み直して「本当にそうなったか」を確かめて読み上げる。
        """
        if not self._require_connection():
            return
        name = self._pick_camera()
        if not name:
            return
        scene = self.snapshot.current_scene
        try:
            before = commands.fetch_camera_state(self.conn.req, name, scene)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"カメラの状態を取得できませんでした（{exc}）")
            return
        expected = camera.next_state_after_toggle(before.active)
        if self.config.camera.get("confirm_before_toggle", False):
            if not self._ready_for_dialog():
                return
            action = "動かし" if expected else "止め"
            if not self._confirm(f"{name} を{action}ますか？"):
                return
        try:
            commands.toggle_camera_active(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"カメラの切り替えに失敗しました（{exc}）")
            return
        # 切り替えは1〜2秒かかる。その間黙っていると効いたか分からないので、
        # 何をするかだけ先に伝える。結果は確かめてから言う
        speech.speak(
            speech_format.camera_toggle_intent_speech(name, expected),
            interrupt=True)
        wx.CallLater(CAMERA_SETTLE_MS, self._settle_camera, name, expected)

    def _settle_camera(self, name: str, expected: bool) -> None:
        """切り替えたあと、実際の状態を確かめて読み上げる。

        ★期待どおりでなければはっきり言う。止めたつもりで動いている、を
        黙って通すのが一番危ない。
        """
        if not self or not self.conn.connected:
            return
        try:
            state = commands.fetch_camera_state(
                self.conn.req, name, self.snapshot.current_scene)
        except Exception:  # noqa: BLE001
            state = None
        text = speech_format.camera_toggle_result_speech(state, expected)
        if state is None or state.active != expected:
            speech.warn(text)
        else:
            speech.speak(text, interrupt=True)

    def _record_section(self) -> str:
        """録画設定が入っているプロファイルのセクション名。

        簡易出力か詳細出力かでセクションもキー名も変わるので、モードを
        読んでから決める（core/recording.py の output_section）。
        """
        mode = commands.fetch_profile_parameter(self.conn.req, "Output", "Mode")
        return recording.output_section(mode)

    def add_record_chapter(self) -> None:
        """録画中のファイルにチャプター（しおり）を打つ。

        タイムラインを目で走査できないぶん、「あとで聞き直す位置」に印を
        残せると、見返しと編集がまるごと楽になる。
        """
        if not self._require_connection():
            return
        active, _paused, timecode = commands.fetch_record_status(self.conn.req)
        if not active:
            speech.speak(
                speech_format.chapter_not_recording_speech(), interrupt=True)
            return
        index = self._chapter_count + 1
        try:
            commands.create_record_chapter(
                self.conn.req, recording.chapter_name(index, timecode))
        except commands.RecordChapterUnsupported:
            # 原因はほぼ録画フォーマット。何にすればよいかまで案内する
            # （拒否されたことだけ伝えても次の手が分からないため）。
            # ★設定と実態がずれている（変えたが未反映）ことがあるので、
            #   実際に動いている出力の種別も一緒に見て案内を変える
            fmt = commands.fetch_profile_parameter(
                self.conn.req, self._record_section(), "RecFormat2")
            kind = commands.fetch_record_output_kind(self.conn.req)
            speech.warn(speech_format.chapter_unsupported_speech(fmt, kind))
            return
        self._chapter_count = index
        speech.speak(
            speech_format.chapter_added_speech(index, timecode), interrupt=True)

    def announce_record_settings(self) -> None:
        """録画設定（保存先・フォーマット・エンコーダなど）を読み上げる。

        OBS本体の[設定→出力]にはスクリーンリーダーで読めない領域がある
        ため、ここが録画設定を確かめる手段になる。読むだけで変更はしない。
        """
        if not self._require_connection():
            return
        # 数回の問い合わせが要るので、先に「今読んでいる」ことを伝える
        speech.speak("録画設定を読み込みます", interrupt=True)
        try:
            settings = commands.fetch_record_settings(self.conn.req)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"録画設定を取得できませんでした（{exc}）")
            return
        speech.speak(
            speech_format.record_settings_summary(settings), interrupt=True)

    # ------------------------------------------------------------
    # 録画の音声トラック割り当て（core/tracks.py の説明を参照）
    # ------------------------------------------------------------
    def apply_input_track(self, name: str, number: int, on: bool):
        """ソースのトラック1本を入り切りし、読み直して確かめる。

        返すのは読み直したトラックの並び（失敗したら None）。
        ★変えた結果を読み直して言う（投げっぱなしにしない）。録画されない
        トラックへ出したときは、そのことも言う（音が録れない食い違い）。
        """
        if not self._require_connection():
            return None
        try:
            commands.set_input_audio_track(self.conn.req, name, number, on)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"トラックを変えられませんでした（{exc}）")
            return None
        states = commands.fetch_input_audio_tracks(self.conn.req, name)
        if states is None or states[number - 1] != bool(on):
            speech.warn(speech_format.input_tracks_unchanged_speech(name))
            return states
        text = speech_format.input_tracks_changed_speech(
            name, number, on, states)
        rec = commands.fetch_record_tracks(self.conn.req).get("tracks")
        if on and rec is not None and not rec[number - 1]:
            text += (f"。トラック{number}は今は録画されていません。"
                     "配信・録画メニューの録画のトラック設定で足せます")
        speech.speak(text, interrupt=True)
        return states

    def apply_record_track(self, info: dict, number: int, on: bool):
        """録画するトラック1本を入り切りし、読み直して確かめる。

        返すのは読み直した並び（失敗・断ったときは None）。
        ★録画中は断る。次の録画から効く設定で、変えたつもりで今の録画には
        効いていない、を作らないため（録画フォーマットと同じ扱い）。
        """
        if not self._require_connection():
            return None
        if self.snapshot.recording:
            speech.warn("録画中は録画のトラックを変えられません。"
                        "次の録画から効く設定なので、録画を止めてから変えてください")
            return None
        current = info.get("tracks")
        if current is None:
            current = (False,) * tracks.TRACK_COUNT
        wanted = list(current)
        wanted[number - 1] = bool(on)
        section = info.get("section", recording.SECTION_SIMPLE)
        try:
            commands.apply_record_tracks(self.conn.req, section, wanted)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"録画のトラックを変えられませんでした（{exc}）")
            return None
        got = commands.fetch_record_tracks(self.conn.req).get("tracks")
        if got is None or tuple(got) != tuple(wanted):
            speech.warn("録画のトラックは変わりませんでした。"
                        "OBSが受け付けていません")
            return got
        text = speech_format.record_tracks_changed_speech(got)
        note = tracks.simple_mode_note(section, info.get("quality", ""))
        if note:
            text += "。" + note
        speech.speak(text, interrupt=True)
        return got

    def announce_tracks_overview(self) -> None:
        """録画のトラック割り当てをまとめて読む（読むだけで変えない）。

        録画されるトラックと、音声を持つソースごとの出し先を並べ、
        録画に入らないソースを言い当てる。
        """
        if not self._require_connection():
            return
        speech.speak("録画のトラック割り当てを読み込みます", interrupt=True)
        try:
            info = commands.fetch_record_tracks(self.conn.req)
            per_input: dict = {}
            for inp in self.snapshot.audio_inputs:
                states = commands.fetch_input_audio_tracks(
                    self.conn.req, inp.name)
                if states is not None:
                    per_input[inp.name] = states
        except Exception as exc:  # noqa: BLE001
            speech.error(f"トラックの割り当てを取得できませんでした（{exc}）")
            return
        note = tracks.simple_mode_note(
            info.get("section", ""), info.get("quality", ""))
        speech.speak(
            speech_format.tracks_overview_speech(
                per_input, info.get("tracks"), note),
            interrupt=True)

    def open_record_tracks(self) -> None:
        """録画するトラックを選ぶ画面を開く。"""
        if not self._require_connection():
            return
        if not self._ready_for_dialog():
            return
        with self.modal():
            dlg = prop_dialog.RecordTracksDialog(self)
            try:
                note = tracks.simple_mode_note(
                    dlg.info.get("section", ""), dlg.info.get("quality", ""))
                if note:
                    speech.warn(note)
                dlg.ShowModal()
            finally:
                dlg.Destroy()

    def open_last_recording(self) -> None:
        """最後の録画をエクスプローラーで開く（ファイルを選択した状態で）。

        このセッションで録画していなければ、保存先フォルダを開く。
        エクスプローラーは標準のUIなのでスクリーンリーダーで扱える。
        """
        if not self._require_connection():
            return
        path = self._last_record_path
        if not path:
            # このセッションでは録画していない。リプレイなら OBS が
            # 最後の1件を覚えているので、それを開く
            path = commands.fetch_last_replay_path(self.conn.req)
        if path and os.path.isfile(path):
            speech.speak(
                f"{props.file_stem(path)} の場所を開きます", interrupt=True)
            self._reveal_in_explorer(path)
            return
        folder = commands.fetch_record_directory(self.conn.req)
        if not folder or not os.path.isdir(folder):
            speech.warn("録画の保存先が分かりません")
            return
        speech.speak(
            f"録画の保存先 {speech_format.path_speech(folder)} を開きます",
            interrupt=True)
        self._reveal_in_explorer(folder)

    def _reveal_in_explorer(self, path: str) -> None:
        """エクスプローラーで開く（ファイルならそれを選択した状態にする）。

        ★explorer.exe は成功しても終了コード1を返すので結果は見ない。
        パスに空白や記号が入るのでシェルを介さずに引数で渡す。
        コンソール窓が一瞬でも出るとスクリーンリーダーが読んでしまうため
        CREATE_NO_WINDOW を付ける。
        """
        target = os.path.normpath(path)
        args = (["explorer", target] if os.path.isdir(target)
                else ["explorer", f"/select,{target}"])
        try:
            subprocess.Popen(
                args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:  # noqa: BLE001
            speech.error(f"フォルダを開けませんでした（{exc}）")

    # ------------------------------------------------------------
    # 設定変更の合流（読み上げを1回にまとめる）
    # ------------------------------------------------------------
    def _start_settings_op(
        self, kind: str, sources: list[str], expected: dict, extra: dict
    ) -> None:
        """自分が投げた設定変更を登録し、確定待ちのタイマーを張る。

        投げた直後には喋らない。OBSからの InputSettingsChanged が
        そろうか、時間切れで読み直したときに1回だけ喋る。
        """
        # 連打対策: 前の操作が残っていれば先に確定させる
        if self._settings_op is not None:
            self._stop_settings_timer()
            self._settle_settings_op(self._settings_op.op_id)
        self._settings_seq += 1
        self._settings_op = SettingsOp(
            op_id=self._settings_seq, kind=kind, sources=list(sources),
            expected=dict(expected), extra=dict(extra))
        seq = self._settings_seq
        self._settings_timer = wx.CallLater(
            SETTINGS_SETTLE_MS, self._settle_settings_op, seq)

    def _stop_settings_timer(self) -> None:
        if self._settings_timer is not None:
            try:
                self._settings_timer.Stop()
            except Exception:  # noqa: BLE001
                pass
            self._settings_timer = None

    def _settle_settings_op(self, seq: int) -> None:
        """待っている設定変更を確定させ、結果を1回だけ読み上げる。"""
        op = self._settings_op
        # 古いタイマーが後から発火しても新しい操作を横取りしない
        if op is None or op.op_id != seq:
            return
        self._stop_settings_timer()
        self._settings_op = None
        if not self.conn.connected:
            return
        # イベントが来なかった入力は読み直して埋める（不達への保険）。
        # ★読み直した値は _settings_last にも入れること。入れないと、
        #   次に OBS 本体側で設定を変えたときの差分に自分の変更が混ざり、
        #   もう一度読み上げられてしまう。
        for name in op.missing():
            try:
                latest = commands.fetch_input_settings(self.conn.req, name)
            except Exception:  # noqa: BLE001
                latest = {}
            op.note(name, latest)
            self._settings_last[name] = dict(latest)
        if op.kind == "game_switch":
            self._speak_game_switch_result(op)
        else:
            self._speak_prop_result(op)

    def _speak_game_switch_result(self, op: SettingsOp) -> None:
        video = op.extra.get("video", "")
        if not op.applied(video, "window"):
            speech.warn(speech_format.prop_unchanged_speech(video, "対象ウィンドウ"))
            return
        speech.speak(
            speech_format.game_switch_speech(
                op.extra.get("title", ""), video,
                op.extra.get("audio_ok", []), op.extra.get("audio_ng", []),
                bool(op.extra.get("running", True))),
            interrupt=True)

    def _speak_prop_result(self, op: SettingsOp) -> None:
        source = op.extra.get("source", "")
        labels = op.extra.get("labels", [])
        # 投げた値が入っていなければ、OBSが受け付けていない
        want = op.expected.get(source, {})
        for key in want:
            if not op.applied(source, key):
                label = op.extra.get("first_label", "設定")
                speech.warn(speech_format.prop_unchanged_speech(source, label))
                return
        speech.speak(
            speech_format.prop_multi_changed_speech(source, labels),
            interrupt=True)

    def _settings_event(self, name: str, settings: dict) -> None:
        """InputSettingsChanged をUIスレッドで処理する。"""
        op = self._settings_op
        if op is not None and name in op.sources:
            if op.note(name, settings):
                self._stop_settings_timer()
                self._settle_settings_op(op.op_id)
            self._settings_last[name] = dict(settings)
            return
        # 自分の操作ではない＝OBS本体側で変えられた。表に載っている項目が
        # 実際に変わったときだけ読む（イベントは値が同じでも飛ぶため）。
        before = self._settings_last.get(name)
        self._settings_last[name] = dict(settings)
        if before is None:
            return
        changed = props.diff_settings(before, settings)
        if not changed:
            return
        kind = self._settings_kind_of(name)
        pairs: list[tuple[str, str]] = []
        for key, value in changed.items():
            spec = props.spec_by_key(kind, key)
            if spec is None:
                continue
            pairs.append((spec.label, props.format_value(spec, kind, value)))
        if pairs:
            speech.speak(
                speech_format.prop_multi_changed_speech(name, pairs),
                interrupt=True)

    def _settings_kind_of(self, name: str) -> str:
        """入力の種別を返す（スナップショット優先、無ければ問い合わせ）。"""
        target = self.snapshot.input_by_name(name)
        if target is not None and target.kind:
            return target.kind
        if not self.conn.connected:
            return ""
        return commands.fetch_input_kind(self.conn.req, name)

    # ------------------------------------------------------------
    # ソースの設定（プロパティ編集）
    # ------------------------------------------------------------
    def _props_target(self) -> str:
        """設定を編集する対象ソース名を決める。

        ★「最後に触っていたリスト」で決める（今フォーカスがあるリスト、
        ではない）。メニューやグローバルキーから呼ばれた時点では、
        フォーカスが状態欄など対象外のコントロールにあることがあり、
        FindFocus() だけを見ると常に音声入力一覧へ倒れてしまって、
        **音を持たないソース（テキストや画像）を選べない**。
        0.12.0 で音無しソースが増えたときに顕在化した問題で、この
        仕組みはボタンを廃止した 0.14.0 以降も必要（理由が変わっただけ）。
        """
        target = wx.Window.FindFocus()
        if target not in (self.item_list, self.input_list):
            target = self._last_list
        if target is self.item_list:
            return self._selected_item_name()
        return self._selected_input_name()

    def _selected_item_id(self):
        """ソース一覧で選択中の item_id。選んでいなければ None。

        ★範囲の確認をここ1か所に置く。0.17.3 まで同じ確認が3か所に
        写されていて、一覧に scene item 以外の行が増えたときに、
        直し漏れた側が別のソースを操作する形になっていた。
        """
        idx = self.item_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._item_ids):
            return None
        return self._item_ids[idx]

    def _selected_item_name(self) -> str:
        """ソース一覧で選択中のソース名。無ければ空文字。"""
        item_id = self._selected_item_id()
        return "" if item_id is None else self._item_names.get(item_id, "")

    def popup_list_menu(self, target=None) -> None:
        """アプリケーションキーで、そのリストでできる操作の一覧を出す。

        ★並びは「そのリストで一番よくやること」から。0.16.0 まで
        アプリケーションキーが直接開いていた「設定」を先頭に置いてある
        （下矢印を1回押してEnterで、今までと同じ動きになる。キーボードから
        開いたメニューはどの項目も選ばれていない状態で開くので、
        Enterだけでは何も起きずに閉じる＝実測で確認）。
        ★選べないものは淡色にして残す（消すと、その操作が
        「無い」のか「今はできない」のかが分からない）。
        """
        target = target or wx.Window.FindFocus()
        if target not in (self.scene_list, self.item_list,
                          self.input_list, self.filter_list):
            return
        # ★メニューを出したリストを、そのまま追従先にする。
        #   アプリケーションキーは「このリストの、この行に対して」という
        #   意思表示なので、最後に矢印を押したリストより優先してよい。
        #   合わせておかないと、同じメニューの「ソースの設定」は
        #   フォーカス先を、「フィルターを追加」は別のリストの選択を
        #   対象にする（レビューで判明）
        if target in (self.item_list, self.input_list):
            self._filter_follow = target
            self._last_list = target
        self._sync_filter_target()
        menu = self.build_list_menu(target)
        with self.modal(restore_focus=False):
            target.PopupMenu(menu, wx.Point(10, 10))
        menu.Destroy()

    def build_list_menu(self, target) -> wx.Menu:
        """そのリスト用の操作メニューを組み立てる（表示はしない）。

        表示と分けてあるのは、中身をテストできるようにするため
        （PopupMenu は中で別のイベントループを回すので、開いたままでは
        検証できない）。
        """
        # 前回のメニューの結び付けはここで外す。★閉じた直後に外しては
        # いけない。PopupMenu が返るのと、選ばれた項目のイベントが届くのと
        # どちらが先かは保証されず、先に外すと「選んだのに何も起きない」
        # になりうる
        for item_id in self._popup_bound:
            self.Unbind(wx.EVT_MENU, id=item_id)
        self._popup_bound = []
        menu = wx.Menu()

        def add(label: str, handler, enabled: bool = True) -> None:
            # ★動作はメニューを閉じてから走らせる（wx.CallAfter）。
            #   メニューのイベントループの中からダイアログを開くと、
            #   フォーカスの戻り先を見失うことがある
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU,
                      lambda _evt, h=handler: wx.CallAfter(h), item)
            self._popup_bound.append(item.GetId())
            item.Enable(bool(enabled))

        if target is self.scene_list:
            has = self.scene_list.GetSelection() != wx.NOT_FOUND
            add("シーンの設定", self.open_scene_props, has)
            add("シーンを作る", self.create_scene)
            add("シーンを削除", self.remove_scene, has)
            menu.AppendSeparator()
            add("シーン一覧の並び順", self.open_scene_order)
        elif target is self.item_list:
            has = self.item_list.GetSelection() != wx.NOT_FOUND
            add("ソースの設定", self.open_source_props, has)
            add("フィルターを追加", self.add_filter, has)
            menu.AppendSeparator()
            add("ソースを作る", self.create_source)
            add("ソースを削除", self.remove_source, has)
            menu.AppendSeparator()
            add("ソースを前に出す（重なり順）",
                lambda: self.move_item_layer(True), has)
            add("ソースを後ろに送る（重なり順）",
                lambda: self.move_item_layer(False), has)
            add("ソース一覧の並び順", self.open_item_order)
        elif target is self.input_list:
            has = self.input_list.GetSelection() != wx.NOT_FOUND
            add("ソースの設定", self.open_source_props, has)
            add("フィルターを追加", self.add_filter, has)
            menu.AppendSeparator()
            add("音量を数値で入力", self.prompt_selected_volume, has)
            add("ソースを削除", self.remove_source, has)
            menu.AppendSeparator()
            add("レベル読み上げの順番", self.open_level_order)
            add("録画のトラック割り当てを読む", self.announce_tracks_overview)
        else:
            has = self._selected_filter_name() != ""
            add("フィルターの設定", self.open_filter_props, has)
            add("フィルターを追加", self.add_filter)
            add("フィルターを削除", self.remove_filter, has)
        return menu

    def _remember_list_focus(self, evt) -> None:
        """どのリストを最後に触っていたかを覚える（上の理由）。

        ★覚えるのはソース一覧と音声入力一覧だけ（0.16.0）。
        フィルター一覧やシーン一覧にフォーカスが移っただけで対象が
        変わってしまうと、ソース一覧で選んだ映像ソースを見ているのに
        フィルターの操作先が音声入力へすり替わる。
        """
        # ★フィルター一覧の対象はここでは変えない。タブ順の都合で
        #   通り過ぎるだけの音声入力一覧に、黙ってすり替わってしまう
        #   （_filter_source_target の説明を参照）。対象が変わるのは
        #   実際に選択を動かしたとき（on_item_selected / on_input_selected）
        obj = evt.GetEventObject()
        if obj in (self.item_list, self.input_list):
            self._last_list = obj
        elif obj is self.filter_list:
            # ★フィルター一覧へ入るときだけは、待っている作り直しを
            #   済ませてから読ませる（250ms の待ちの間に Tab して
            #   きた場合、古いソースのフィルターを読み上げてしまう）。
            #   EVT_SET_FOCUS の最中に通信しないよう後回しにする
            wx.CallAfter(self._sync_filter_target)
        evt.Skip()

    def open_source_props(self) -> None:
        """選択中のソースの設定ダイアログを開く。"""
        if not self._require_connection():
            return
        name = self._props_target()
        if not name:
            speech.speak(
                "ソース一覧か音声入力一覧でソースを選んでから実行してください",
                interrupt=True)
            return
        kind = commands.fetch_input_kind(self.conn.req, name)
        if not kind:
            speech.warn(
                f"{name} はシーンかグループのようです。設定はありません")
            return
        speech.speak(f"{name} の設定を開きます", interrupt=True)
        with self.modal():
            dlg = prop_dialog.SourcePropDialog(self, name, kind)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()

    # ------------------------------------------------------------
    # シーンの作成・設定・削除
    # ------------------------------------------------------------
    def _selected_scene(self) -> str:
        """シーン一覧で選択中のシーン名。無ければ空文字。"""
        idx = self.scene_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return ""
        return self.scene_list.GetString(idx)

    def create_scene(self) -> None:
        """シーンを作り、続けて設定を開く。

        ★作っても現在のシーンは変わらない（実測）。配信中に足しても
        画面は飛ばない。作った直後は空なので、そのまま設定へ進んで
        ソースを追加できるようにする。
        """
        if not self._require_connection():
            return
        if not self._ready_for_dialog():
            return
        existing = commands.fetch_scene_names(self.conn.req)
        suggested = scenes.free_scene_name("新しいシーン", existing)
        with self.modal():
            dlg = wx.TextEntryDialog(
                self, "シーンの名前を入力してください。", "シーンを作る",
                value=suggested)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                typed = dlg.GetValue()
            finally:
                dlg.Destroy()
        name = scenes.valid_scene_name(typed)
        if not name:
            speech.error("名前が空です。作成をやめました")
            return
        if name in existing:
            # 黙って別名にせず、変えたことを伝える
            name = scenes.free_scene_name(name, existing)
            speech.speak(f"同じ名前があるので {name} にします", interrupt=True)
        try:
            commands.create_scene(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"シーンの作成に失敗しました（{exc}）")
            return
        self.refresh_from_obs()
        if name not in commands.fetch_scene_names(self.conn.req):
            speech.warn("シーンを作れませんでした")
            return
        # 作ったシーンを選んでおく（続けて中身を作れるように）
        if name in self.snapshot.scenes:
            self.scene_list.SetStringSelection(name)
            self.refresh_item_list()
        speech.speak(speech_format.scene_created_speech(name), interrupt=True)
        wx.CallLater(100, self._open_scene_props, name)

    def open_scene_props(self) -> None:
        """シーン一覧で選択中のシーンの設定を開く。"""
        if not self._require_connection():
            return
        name = self._selected_scene()
        if not name:
            speech.speak(
                "シーン一覧でシーンを選んでから実行してください",
                interrupt=True)
            return
        speech.speak(f"{name} の設定を開きます", interrupt=True)
        self._open_scene_props(name)

    def _open_scene_props(self, name: str) -> None:
        """シーン設定ダイアログを開く（作成直後からも呼ぶ）。"""
        if not self or not self.conn.connected:
            return
        with self.modal():
            dlg = prop_dialog.ScenePropDialog(self, name)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()
        # 名前が変わっているかもしれないので一覧ごと取り直す
        self.refresh_from_obs()

    def remove_scene(self) -> None:
        """シーン一覧で選択中のシーンを削除する。

        ★そのシーンにしか無いソースは一緒に消える。他のシーンにも
        置いてあるソースは残る（実測で確認）。取り消せないので、
        何が起きるかを確認ダイアログに全部書く。
        """
        if not self._require_connection():
            return
        name = self._selected_scene()
        if not name:
            speech.speak(
                "シーン一覧でシーンを選んでから実行してください",
                interrupt=True)
            return
        # ★最後の1つは消せない。OBSのエラーを読み上げても何が悪いか
        #   分からないので、投げる前に理由を伝える
        ok, reason = scenes.can_remove(
            commands.fetch_scene_names(self.conn.req), name)
        if not ok:
            speech.warn(reason)
            return
        if not self._ready_for_dialog():
            return
        is_current = (name == self.snapshot.current_scene)
        if not self._confirm(
            speech_format.scene_remove_warning(name, is_current)
        ):
            return
        try:
            commands.remove_scene(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"シーンの削除に失敗しました（{exc}）")
            return
        self.refresh_from_obs()
        speech.speak(
            speech_format.scene_removed_speech(name), interrupt=True)

    # ------------------------------------------------------------
    # ソースの作成・削除
    # ------------------------------------------------------------
    def _target_scene(self) -> str:
        """ソースを作る先のシーン。

        シーン一覧で選択中のシーンを使う（ソース一覧が追従しているのが
        そのシーンなので、「今見ているところ」に足せる）。選択が無ければ
        配信に出ているシーンへ。
        """
        idx = self.scene_list.GetSelection()
        if idx != wx.NOT_FOUND:
            name = self.scene_list.GetString(idx)
            if name:
                return name
        return self.snapshot.current_scene

    def create_source(self) -> None:
        """新しいソースを作り、続けて設定を開く。

        ★作ったら必ず設定へ進む。キャプチャ系は対象を選ばないと何も
        映らない・鳴らないので、作っただけで放すと「足したのに使えない
        ソース」がシーンに残る。
        """
        if not self._require_connection():
            return
        scene = self._target_scene()
        if not scene:
            speech.error("シーンが取得できないため作成できません")
            return
        if not self._ready_for_dialog():
            return

        kinds = sources.CREATABLE_KINDS
        rows = [speech_format.source_kind_row(k) for k in kinds]
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{scene} に作るソースの種類、{len(rows)}件",
                "ソースを作る", rows)
            try:
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        if not (0 <= idx < len(kinds)):
            return
        info = kinds[idx]

        existing = [i.get("inputName") for i in
                    getattr(commands.fetch_input_list_raw(self.conn.req),
                            "inputs", []) or []
                    if isinstance(i, dict)]
        suggested = sources.free_source_name(info.label, existing)
        with self.modal():
            dlg = wx.TextEntryDialog(
                self,
                f"{info.label} の名前を入力してください。\n"
                f"シーン {scene} に作ります。",
                "ソースの名前", value=suggested)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                typed = dlg.GetValue()
            finally:
                dlg.Destroy()
        name = sources.valid_source_name(typed)
        if not name:
            speech.error("名前が空です。作成をやめました")
            return
        if name in existing:
            # 同名は OBS が拒否する。黙って別名にせず、何をしたか伝える
            name = sources.free_source_name(name, existing)
            speech.speak(f"同じ名前があるので {name} にします", interrupt=True)

        try:
            commands.create_source(self.conn.req, scene, name, info.kind)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"ソースの作成に失敗しました（{exc}）")
            return
        self.refresh_from_obs()
        # 本当にできたかを確かめてから言う
        if not commands.fetch_input_kind(self.conn.req, name):
            speech.warn(
                f"{info.label} を作れませんでした。"
                "OBSがこの種類のソースを受け付けていません")
            return
        speech.speak(
            speech_format.source_created_speech(name, info, scene),
            interrupt=True)
        # 設定が要る種類は、そのまま設定画面へ進む
        if info.needs:
            wx.CallLater(
                100, self._open_props_for, name, info.kind)

    def _open_props_for(self, name: str, kind: str) -> None:
        """作った直後のソースの設定を開く。"""
        if not self or not self.conn.connected:
            return
        with self.modal():
            dlg = prop_dialog.SourcePropDialog(self, name, kind)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()
        self.refresh_from_obs()

    def remove_source(self) -> None:
        """選択中のソースを削除する。

        ★取り消せない。しかも入力の削除は**すべてのシーンから消える**
        （そのシーンだけ外すのとは違う）。設定も一緒に失われるので、
        何が起きるかを確認ダイアログではっきり書く。
        """
        if not self._require_connection():
            return
        name = self._props_target()
        if not name:
            speech.speak(
                "ソース一覧か音声入力一覧でソースを選んでから実行してください",
                interrupt=True)
            return
        kind = commands.fetch_input_kind(self.conn.req, name)
        if not kind:
            speech.warn(
                f"{name} はシーンかグループのようです。ここでは削除できません")
            return
        if not self._ready_for_dialog():
            return
        warning = speech_format.source_remove_warning(
            name, self._source_roles(name))
        if not self._confirm(warning):
            return
        try:
            commands.remove_source(self.conn.req, name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"ソースの削除に失敗しました（{exc}）")
            return
        self.refresh_from_obs()
        speech.speak(
            speech_format.source_removed_speech(name), interrupt=True)

    def _source_roles(self, name: str) -> list[str]:
        """このソースが設定で使われている役割を挙げる。

        設定が指しているソースを消すと、その機能が黙って動かなくなる。
        消す前に「これは何に使っているか」を伝えるための材料。
        """
        roles: list[str] = []
        if name in self._sr_by_name:
            roles.append("スクリーンリーダー音声")
        cfg = self.config.game_switch
        if name == cfg.get("video_source"):
            roles.append("ゲーム切り替えの映像")
        if name in (cfg.get("audio_sources") or []):
            roles.append("ゲーム切り替えの音声")
        if name == self.config.bgm.get("source_name"):
            roles.append("BGM")
        return roles

    def apply_props_change(self, source: str, patch: dict, labels) -> bool:
        """設定ダイアログからの変更を投げる（読み上げはイベント側）。"""
        if not self._require_connection():
            return False
        try:
            commands.apply_input_settings(self.conn.req, source, patch)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"設定の変更に失敗しました（{exc}）")
            return False
        first_label = labels[0][0] if labels else "設定"
        self._start_settings_op(
            "prop", [source], {source: dict(patch)},
            {"source": source, "labels": list(labels),
             "first_label": first_label})
        return True

    def apply_monitor_change(self, source: str, mon_type: str) -> bool:
        """音声モニタリングを変更する（読み上げはイベント側）。"""
        if not self._require_connection():
            return False
        try:
            commands.set_monitor_type(self.conn.req, source, mon_type)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"モニタリングの変更に失敗しました（{exc}）")
            return False
        return True

    def pick_file(self, file_kind: str = "audio") -> str:
        """ファイルを選ぶ（設定ダイアログからも使う）。

        file_kind は "audio"（音楽・動画）か "image"（画像）。
        前回の場所は種類ごとに覚える（音楽と画像は別のフォルダにある）。
        """
        # ネイティブのファイル選択は表示までに数秒かかることがあり、その間
        # 無音になる。モーダル中は CallLater が動かないので案内は必ず前に。
        speech.speak("ファイルを選ぶ画面を開きます", interrupt=True)
        key = "last_dir" if file_kind == "audio" else f"last_dir_{file_kind}"
        with self.modal():
            path = prop_dialog.pick_audio_file(
                self, self.config.bgm.get(key, ""), file_kind)
        if not path:
            return ""
        self.config.bgm[key] = os.path.dirname(path)
        self._save_config()
        return path

    def pick_audio_file(self) -> str:
        """音楽ファイルを選ぶ（BGM まわりから使う既存の呼び名）。"""
        return self.pick_file("audio")

    # ------------------------------------------------------------
    # ゲーム切り替え（映像と音声をまとめて別のゲームへ向ける）
    # ------------------------------------------------------------
    def _resolve_source(self, current: str, want_kind: str, title: str) -> str:
        """設定のソース名を検証し、合わなければ選び直させる。

        設定ファイルを手で直さなくても復旧できるようにする。
        """
        if current and commands.fetch_input_kind(self.conn.req, current) == want_kind:
            return current
        names = commands.fetch_input_names_by_kind(self.conn.req, want_kind)
        if not names:
            speech.error(f"{title}に使えるソースがOBSにありません")
            return ""
        if len(names) == 1:
            return names[0]
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{title}を選んでください、{len(names)}件", title, names)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return ""
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        return names[idx] if 0 <= idx < len(names) else ""

    def open_game_switch_global(self) -> None:
        """グローバルキーからのゲーム切り替え。

        Win32 では、前面のウィンドウを持たないプロセスからの前面化は
        拒否されることがある。前面に出せていないのにモーダルを開くと、
        見えない・読まれないダイアログに閉じ込められるので、その場合は
        開かずに案内する。
        """
        if self.config.game_switch.get("raise_window", True):
            try:
                self.Raise()
                self.SetFocus()
            except Exception:  # noqa: BLE001
                pass
        wx.CallAfter(self._open_game_switch_if_front)

    def _open_game_switch_if_front(self) -> None:
        if not self:
            # CallAfter の発火前にウィンドウが閉じられた場合
            return
        if not self.IsActive():
            speech.warn(
                "OBSナビを前に出せませんでした。"
                "Alt+Tab でOBSナビに切り替えてから F3 を押してください")
            return
        self.open_game_switch()

    def open_game_switch(self) -> None:
        """ウィンドウを1回選ぶだけで、映像と音声を新しいゲームへ向ける。"""
        if not self._require_connection():
            return
        cfg = self.config.game_switch
        video = self._resolve_source(
            cfg.get("video_source", ""), props.GAME_CAPTURE_KIND,
            "ゲーム映像のソース")
        if not video:
            return
        if video != cfg.get("video_source"):
            cfg["video_source"] = video
            self._save_config()

        speech.speak("ゲーム一覧を読み込みます", interrupt=True)
        items = commands.fetch_property_items(self.conn.req, video, "window")
        # ゲームキャプチャ側の一覧を使うのが肝。アプリ音声キャプチャの
        # 一覧はブラウザやツールも全部出るので、選ぶには向かない。
        items = props.sort_window_items(props.dedupe_items(items))
        items = [it for it in items if it.get("itemValue")]
        if not items:
            speech.warn(
                "ゲームの候補がありません。"
                "ゲームを起動してから、もう一度 F3 を押してください")
            return
        rows = [speech_format.window_item_label(
            it.get("itemName", ""), it.get("itemEnabled", True))
            for it in items]
        try:
            current = commands.fetch_merged_settings(
                self.conn.req, video, props.GAME_CAPTURE_KIND).get("window", "")
        except Exception:  # noqa: BLE001
            # 現在値は初期選択を決めるためだけのもの。取れなくても
            # 切り替え自体は続けられるので、ここで止めない
            current = ""
        # 今の設定は「起動していない」ことが多く末尾に並ぶ。そこを初期選択に
        # すると矢印を最大件数ぶん押す羽目になるので、起動中の候補を選ぶ。
        sel = props.first_running_index(items, str(current))
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"切り替え先のゲーム、{len(rows)}件",
                "ゲーム切り替え", rows)
            try:
                if 0 <= sel < len(rows):
                    dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返す。必ずここで判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        if not (0 <= idx < len(items)):
            return
        self._apply_game_switch(video, items[idx], rows[idx])

    def _apply_game_switch(self, video: str, item: dict, row_label: str) -> None:
        """選ばれたウィンドウを映像・音声の各ソースへ適用する。"""
        value = str(item.get("itemValue", ""))
        running = bool(item.get("itemEnabled", True))
        title, _exe_label = speech_format.parse_window_item(
            item.get("itemName", ""))
        exe = setup.parse_window_exe(value)

        # 取り込み方法も一緒に送るのが肝。「特定のウィンドウ」以外のままだと
        # window を書いても無視され、無言で何も起きない。
        patch = {"capture_mode": "window", "window": value}
        priority = props.window_priority_for(value)
        if priority is not None:
            patch["priority"] = priority
        try:
            commands.apply_input_settings(self.conn.req, video, patch)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"ゲームの切り替えに失敗しました（{exc}）")
            return

        sources = [video]
        expected = {video: dict(patch)}
        audio_ok: list[str] = []
        audio_ng: list[str] = []
        cfg = self.config.game_switch
        if cfg.get("also_audio", True):
            for audio in cfg.get("audio_sources", []) or []:
                kind = commands.fetch_input_kind(self.conn.req, audio)
                if kind != props.APP_AUDIO_KIND:
                    audio_ng.append(audio)
                    continue
                # 候補の文字列を使い回さない。同じウィンドウでも列挙される
                # 集合が違うので、実行ファイル名で照合し直す。
                a_items = commands.fetch_property_items(
                    self.conn.req, audio, "window")
                found = setup.pick_process_window(a_items, exe)
                if not found:
                    audio_ng.append(audio)
                    continue
                a_patch = {"window": found}
                a_priority = props.window_priority_for(found)
                if a_priority is not None:
                    a_patch["priority"] = a_priority
                try:
                    commands.apply_input_settings(self.conn.req, audio, a_patch)
                except Exception:  # noqa: BLE001
                    audio_ng.append(audio)
                    continue
                audio_ok.append(audio)
                sources.append(audio)
                expected[audio] = dict(a_patch)

        self._start_settings_op(
            "game_switch", sources, expected,
            {"video": video, "title": title or row_label,
             "audio_ok": audio_ok, "audio_ng": audio_ng, "running": running})

    # ------------------------------------------------------------
    # 映像の切り替え（重なり順で切り替える。非表示は使わない）
    # ------------------------------------------------------------
    def open_video_switch(self) -> None:
        """今いちばん前に出す映像ソースを選ぶ。

        ★この機能は「非表示」を一切使わない。OBSでは非表示にすると音も
        消えるため、映像だと思ったソースが実は音を運んでいた場合に、
        目で確認できない利用者が気づけない事故になる。重なり順の変更は
        音に影響しないので、それだけで切り替える。
        """
        if not self._require_connection():
            return
        # ★対象は必ず「配信に出ているシーン」。シーン一覧で選択中のシーン
        #   ではない。見えていないシーンを触る余地を作らない。
        scene = self.snapshot.current_scene
        if not scene:
            speech.error("現在のシーンが取得できません")
            return
        ok, items = commands.fetch_scene_items_checked(self.conn.req, scene)
        if not ok:
            # ★「映像ソースがありません。作ってから実行してください」と
            #   案内してしまうと、あるのに作らせることになる
            speech.error(
                "ソースの一覧を取得できませんでした。"
                "OBSとの接続を確かめてください")
            return
        extra = self.config.video_switch.get("extra_kinds", [])
        targets = video.video_items(items, extra)
        if not targets:
            speech.warn(speech_format.video_none_speech())
            return
        if len(targets) == 1:
            speech.speak(
                f"映像ソースは {targets[0].name} だけです。切り替えるものがありません",
                interrupt=True)
            return
        top = video.front_index(items, extra)
        rows = [
            speech_format.video_item_label(
                it.name, it.index, top, it.source_width <= 0.0)
            for it in targets
        ]
        sel = video.first_other_index(items, extra)
        with self.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"前に出す映像、{len(rows)}件", "映像切り替え", rows)
            try:
                if 0 <= sel < len(rows):
                    dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
        if not (0 <= idx < len(targets)):
            return
        self._bring_video_to_front(scene, items, targets[idx].item_id)

    def _bring_video_to_front(self, scene: str, items, item_id: int) -> None:
        """選ばれた映像ソースを映像の最前面へ移す。"""
        extra = self.config.video_switch.get("extra_kinds", [])
        plan = video.plan_bring_to_front(items, item_id, extra)
        if plan is None:
            speech.error("対象の映像ソースが見つかりません")
            return
        if plan.already_front:
            speech.speak(
                speech_format.video_already_front_speech(plan.name),
                interrupt=True)
            return
        try:
            commands.set_scene_item_index(
                self.conn.req, scene, plan.item_id, plan.dest_index)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"映像の切り替えに失敗しました（{exc}）")
            return
        # 反映を読み直してから1回だけ喋る（重なり順のイベントは種類が
        # 多く、素直に喋ると複数回になるため。確認も兼ねる）
        wx.CallLater(500, self._settle_video_switch, scene, plan)

    def _settle_video_switch(self, scene: str, plan) -> None:
        """並べ替えの結果を確認して1回だけ読み上げる。"""
        if not self.conn.connected:
            return
        extra = self.config.video_switch.get("extra_kinds", [])
        try:
            items = commands.fetch_scene_items(self.conn.req, scene)
        except Exception:  # noqa: BLE001
            return
        now = next(
            (it for it in items if it.item_id == plan.item_id), None)
        top = video.front_index(items, extra)
        if now is None or now.index < top:
            speech.warn(speech_format.video_unchanged_speech(plan.name))
            return
        # 実際に絵が出ているかは今の値で読み直す（計画時とずれ得る）
        settled = video.plan_bring_to_front(items, plan.item_id, extra)
        speech.speak(
            speech_format.video_front_speech(settled or plan), interrupt=True)
        self._refresh_items_if_current(scene)

    # ------------------------------------------------------------
    # BGM（手元の音楽ファイルを鳴らす）
    # ------------------------------------------------------------
    def toggle_bgm_playback(self) -> None:
        """BGMの再生・一時停止。無ければ作成を確認する。"""
        if not self._require_connection():
            return
        name = self._resolve_bgm_source()
        if not name:
            return
        kind = commands.fetch_input_kind(self.conn.req, name)
        try:
            merged = commands.fetch_merged_settings(self.conn.req, name, kind)
        except Exception as exc:  # noqa: BLE001
            # 種別を確かめた直後にソースが消される、通信が切れる等。
            # 無言で終わらせない（読み上げが唯一の手がかりなので）
            speech.error(f"BGMの設定を取得できませんでした（{exc}）")
            return
        path = str(merged.get("local_file", "") or "")
        if not path or not os.path.isfile(path):
            # ここはファイル選択（モーダル）を開く。グローバルキーから
            # 呼ばれてウィンドウが後ろにいると見えないダイアログになる。
            if not self._ready_for_dialog():
                return
            speech.warn("音楽ファイルが見つかりません。選び直してください")
            new_path = self.pick_audio_file()
            if not new_path:
                return
            self.apply_props_change(
                name, {"local_file": new_path, "is_local_file": True},
                [("音楽ファイル", props.file_stem(new_path))])
            return
        state, _cur, _dur = commands.fetch_media_status(self.conn.req, name)
        action = props.media_action_for_state(state)
        try:
            commands.trigger_media_action(self.conn.req, name, action)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"BGMの操作に失敗しました（{exc}）")
        # 読み上げはメディアイベント側で行う（一方通行の原則）

    def _resolve_bgm_source(self) -> str:
        """BGMに使うメディアソースを決める。無ければ作成へ誘導する。

        設定のソース名が実在しなくても、OBSに既にメディアソースがあれば
        それを使う（利用者がOBS側で用意した名前に合わせられるように）。
        決まったら設定に覚える。
        """
        name = self.config.bgm.get("source_name", "BGM音楽")
        kind = commands.fetch_input_kind(self.conn.req, name)
        if props.is_media_kind(kind):
            return name
        if kind:
            # 同名だが種別が違う（アプリ音声キャプチャなど）
            speech.warn(speech_format.bgm_wrong_kind_speech(name))
        names = commands.fetch_input_names_by_kind(
            self.conn.req, props.MEDIA_KIND)
        if not names:
            if not self._ready_for_dialog():
                return ""
            # 設定名の入力が別種別で既に存在する場合、同じ名前では作れない
            # （OBSが「既にある」と拒否する）。空いている名前に変えて作る。
            self._create_bgm_source(self._free_input_name(name))
            return ""
        if len(names) == 1:
            chosen = names[0]
        else:
            if not self._ready_for_dialog():
                return ""
            with self.modal():
                dlg = wx.SingleChoiceDialog(
                    self, f"BGMに使うメディアソースを選んでください、{len(names)}件",
                    "BGMのソース", names)
                try:
                    if dlg.ShowModal() != wx.ID_OK:
                        return ""
                    idx = dlg.GetSelection()
                finally:
                    dlg.Destroy()
            if not (0 <= idx < len(names)):
                return ""
            chosen = names[idx]
        self.config.bgm["source_name"] = chosen
        self._save_config()
        speech.speak(f"BGMに {chosen} を使います", interrupt=True)
        return chosen

    def _free_input_name(self, base: str) -> str:
        """OBSに存在しない入力名を base から導く（同名衝突の回避）。"""
        if not commands.fetch_input_kind(self.conn.req, base):
            return base
        for i in range(2, 100):
            candidate = f"{base}{i}"
            if not commands.fetch_input_kind(self.conn.req, candidate):
                return candidate
        return base

    def _create_bgm_source(self, name: str) -> None:
        """BGM用のメディアソースを作る（既存のBGMには触らない）。"""
        scene = self.snapshot.current_scene
        if not scene:
            speech.error("現在のシーンが取得できないため作成できません")
            return
        if not self._confirm(
            f"音楽ファイルを再生する入力「{name}」がありません。"
            f"シーン「{scene}」に作成しますか？"
        ):
            return
        path = self.pick_audio_file()
        if not path:
            # ファイルを選ばなかったら、空のソースを作って放置しない
            return
        try:
            commands.create_media_input(self.conn.req, scene, name, path)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"BGMの作成に失敗しました（{exc}）")
            return
        # 別名で作った場合も、次回からその名前を使えるよう設定に覚える
        if self.config.bgm.get("source_name") != name:
            self.config.bgm["source_name"] = name
            self._save_config()
        # ★キー名は設定から作る。修飾キーを変えていたり、グローバルキーを
        #   切っていたりすると、決め打ちの案内は登録されていないキーを
        #   教えることになる
        window_key = keymap.window_key_label(self.config, "bgm")
        global_key = keymap.global_key_label(self.config, "bgm")
        how = "ソースメニューの「BGMの再生・一時停止」で操作できます"
        if window_key and global_key:
            how = (f"{window_key}（どこにいても {global_key}）"
                   "で再生と一時停止ができます")
        elif window_key or global_key:
            how = f"{window_key or global_key} で再生と一時停止ができます"
        speech.speak(
            speech_format.bgm_file_speech(name, path)
            + f"。{scene} で鳴ります。{how}",
            interrupt=True)

    # ------------------------------------------------------------
    # ボタンハンドラ
    # ------------------------------------------------------------
    def run_selected_output(self) -> None:
        """配信・録画リストで選んでいる操作を実行する。"""
        idx = self.output_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._output_actions[idx]()

    def on_stream_start(self, _evt: wx.CommandEvent) -> None:
        self.start_stream()

    def on_stream_stop(self, _evt: wx.CommandEvent) -> None:
        self.stop_stream()

    def on_record_start(self, _evt: wx.CommandEvent) -> None:
        self.start_record()

    def on_record_stop(self, _evt: wx.CommandEvent) -> None:
        self.stop_record()

    def on_record_pause(self, _evt: wx.CommandEvent) -> None:
        self.toggle_record_pause()

    def on_vcam_btn(self, _evt: wx.CommandEvent) -> None:
        self.toggle_virtual_cam()

    def on_replay_btn(self, _evt: wx.CommandEvent) -> None:
        self.save_replay()

    def on_stats_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_stats()

    def on_chapter_btn(self, _evt: wx.CommandEvent) -> None:
        self.add_record_chapter()

    def on_rec_settings_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_record_settings()

    def on_rec_tracks_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_record_tracks()

    def on_tracks_overview_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_tracks_overview()

    def on_open_rec_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_last_recording()

    def on_filter_add_btn(self, _evt: wx.CommandEvent) -> None:
        self.add_filter()

    def on_filter_props_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_filter_props()

    def on_filter_remove_btn(self, _evt: wx.CommandEvent) -> None:
        self.remove_filter()

    def on_scene_add_btn(self, _evt: wx.CommandEvent) -> None:
        self.create_scene()

    def on_scene_props_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_scene_props()

    def on_scene_remove_btn(self, _evt: wx.CommandEvent) -> None:
        self.remove_scene()

    def on_source_add_btn(self, _evt: wx.CommandEvent) -> None:
        self.create_source()

    def on_source_remove_btn(self, _evt: wx.CommandEvent) -> None:
        self.remove_source()

    def on_camera_check_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_cameras()

    def on_camera_toggle_btn(self, _evt: wx.CommandEvent) -> None:
        self.toggle_camera()

    def on_game_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_game_switch()

    def on_bgm_btn(self, _evt: wx.CommandEvent) -> None:
        self.toggle_bgm_playback()

    def on_video_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_video_switch()

    def on_props_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_source_props()

    def on_state_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_state()

    def on_levels_btn(self, _evt: wx.CommandEvent) -> None:
        self.announce_levels()

    def on_level_order_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_level_order()

    def on_scene_order_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_scene_order()

    def on_item_order_btn(self, _evt: wx.CommandEvent) -> None:
        self.open_item_order()

    def on_item_front_btn(self, _evt: wx.CommandEvent) -> None:
        self.move_item_layer(True)

    def on_item_back_btn(self, _evt: wx.CommandEvent) -> None:
        self.move_item_layer(False)

    def on_skip_muted_toggle(self, evt: wx.CommandEvent) -> None:
        # チェック項目なので、メニューが持っている新しい状態をそのまま使う
        self.set_skip_muted(evt.IsChecked())

    def on_volume_btn(self, _evt: wx.CommandEvent) -> None:
        self.prompt_selected_volume()

    def on_reconnect_btn(self, _evt: wx.CommandEvent) -> None:
        self.do_connect(True)

    def on_exit_menu(self, _evt: wx.CommandEvent) -> None:
        self.Close()

    def on_help_keys(self, _evt: wx.CommandEvent) -> None:
        """キー操作の一覧を出す。

        ★一覧は core/keymap.py が実際の登録と同じ定義から作る。
        手書きの一覧だと、キーを足したときに片方だけ直して食い違う。
        押しても何も起きないキーを探し続けるのは、見えない利用者に
        とって特に困る。
        """
        with self.modal():
            dlg = prop_dialog.KeyHelpDialog(self, keymap.help_text(self.config))
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()

    def on_about(self, _evt: wx.CommandEvent) -> None:
        """バージョンと接続先、ライセンスの告知を読む。"""
        parts = [f"OBSナビ バージョン {VERSION}"]
        if self.conn.connected and self.snapshot.obs_version:
            parts.append(f"OBS {self.snapshot.obs_version} に接続中")
        elif self.conn.connected:
            parts.append("OBSに接続中")
        else:
            parts.append("OBSに接続していません")
        parts.append("キー操作は、ヘルプメニューのキー操作の一覧で読めます")
        # AI を使って作ったことの告知（README・マニュアルと同じ趣旨）
        parts.append(speech_format.ai_notice_speech())
        # ★GPL-3.0 の告知（0.18.4）。理由は license_notice_speech の説明
        parts.append(speech_format.license_notice_speech())
        speech.speak("。".join(parts), interrupt=True)

    # ------------------------------------------------------------
    # キー処理（パネルの EVT_CHAR_HOOK に集約）
    # ------------------------------------------------------------
    def _build_window_dispatch(self) -> None:
        """窓内キーの振り分け表を keymap.WINDOW_PLAN から作る。

        ★0.14.0 まではここのキーが on_char_hook にハードコードされていて、
        keymap（メニュー表示・ヘルプの出どころ）と接続が無かった。
        表示だけ直して動作が変わらない片肺状態を防ぐため、振り分けも
        同じ表から作る。動作の実装が無い action_id は黙って落とさず
        _key_problems へ報告する（一覧に出るのに効かないキーを作らない）。
        """
        actions = self._window_actions()
        self._window_dispatch = {}
        for action_id, ctrl, shift, key_name, desc in keymap.window_bindings(
            self.config
        ):
            handler = actions.get(action_id)
            if handler is None:
                self._key_problems.append(
                    f"{desc}のキーは定義されていますが動作が実装されていません")
                continue
            mods = wx.MOD_NONE
            if ctrl:
                mods |= wx.MOD_CONTROL
            if shift:
                mods |= wx.MOD_SHIFT
            if key_name in KEY_NAME_TO_WXK:
                codes = (KEY_NAME_TO_WXK[key_name],)
            else:
                # 英字。EVT_CHAR_HOOK は通常大文字コードで来るが、
                # 環境差に備えて両方のコードを引けるようにしておく
                codes = (ord(key_name.upper()), ord(key_name.lower()))
            for code in codes:
                if (action_id in keymap.WINDOW_YIELD_TO_SR
                        and mods == wx.MOD_NONE
                        and code in self._sr_key_codes):
                    # ★F1 は、利用者が SR 音声のキーを F1 にしていたら
                    #   そちらへ譲る。0.13.0 まで F1 は空き枠で SR に
                    #   使えたので、あとから来たヘルプが既存の設定を
                    #   奪わないようにする。重なり自体は起動時の重複警告が
                    #   「どちらが効くか」まで含めて知らせる
                    continue
                # ★動作そのものを入れる。名前だけ入れて押すたびに引き直すと、
                #   表と実装の対応が2か所に分かれ、起動時に済ませたはずの
                #   検査をすり抜ける道ができる
                self._window_dispatch[(mods, code)] = handler

    def _window_actions(self) -> dict:
        """窓内キーの action_id → 実行する処理の対応表。

        キーの定義（keymap.WINDOW_PLAN）とはあえて分けてある。
        _hotkey_actions と同じ理由で、キー一覧と登録が同じ定義から
        作られるようにするための分離（詳細はそちらのコメント）。
        """
        return {
            "stream_start": self.start_stream,
            "stream_stop": self.stop_stream,
            "record_start": self.start_record,
            "record_stop": self.stop_record,
            "state": self.announce_state,
            "levels": self.announce_levels,
            "volume_prompt": self.prompt_selected_volume,
            "game": self.open_game_switch,
            # ★ソース一覧では素のキーが「先頭一致で選択が飛ぶ」動きに
            #   使われるため、Ctrl+英字はフォーカス位置で分岐させない
            #   （取りこぼした素の B/E/P で選択が飛ぶのを、動作を変えない
            #   ことで無害にする）
            "bgm": self.toggle_bgm_playback,
            "video": self.open_video_switch,
            "record_pause": self.toggle_record_pause,
            "help": lambda: self.on_help_keys(None),
        }

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        # ★キーを押し始めたら起動直後の割り込み抑止を打ち切る。
        #   ここから先の読み上げは操作への応答なので、待たされる方が困る
        speech.end_grace()
        key = evt.GetKeyCode()
        # ファンクションキー系は「修飾キー無しの素押し」だけを拾う。
        # 修飾キー付き（Ctrl+Shift+F8 など）はグローバルホットキー側の担当で、
        # そちらが消費するためここには来ないが、念のため素押しに限定する。
        mods = evt.GetModifiers()
        bare = mods == wx.MOD_NONE
        # 固定キー（F5 や Ctrl+B など）は keymap 由来の振り分け表で引く。
        # ★例外が1つ: F1 は、利用者が SR 音声のキーを F1 にしていたら
        #   そちらへ譲る。0.13.0 まで F1 は空き枠で SR に使えていたので、
        #   ヘルプ（0.14.0 の新顔）が既存の設定を奪わないようにする。
        #   重なり自体は起動時の重複警告が知らせる
        handler = self._window_dispatch.get((mods, key))
        if handler is not None:
            # ★押しっぱなし（自動リピート）では動かさない（0.18.3）。
            #   Ctrl+R を長めに押すと録画の開始が何度も送られ、録画は
            #   始まっているのに「失敗しました」と読まれうる（レビューで
            #   判明）。ここに割り当てているのは1回で済む操作ばかり
            if not evt.IsAutoRepeat():
                handler()
            return
        if (bare and key == wx.WXK_WINDOWS_MENU) or (
            mods == wx.MOD_SHIFT and key == wx.WXK_F10
        ):
            # アプリケーションキー（右クリック相当）。Windowsの「選択項目の
            # メニュー」の慣習に合わせる。F番号を消費しないので衝突しない。
            # ★0.17.0 でメニューにした。それまでは設定を開く動作に直結して
            #   いたので、リストの上から呼べる操作が1つしか無かった
            #   （フィルターの追加のように、他にも呼びたいものがある）。
            #   出すのはネイティブのメニューなので、メニューバーと同じように
            #   読み上げられる（MSAA 経由）
            # ★Shift＋F10 も同じ動作にする。アプリケーションキーの無い
            #   キーボードでは Windows 共通の代替キーなので、拾わないと
            #   このメニューへ辿り着く手段が無い
            focus = wx.Window.FindFocus()
            if focus in (self.scene_list, self.item_list,
                         self.input_list, self.filter_list):
                # キーの処理を終えてから開く（メニューは中で別の
                # イベントループを回すため）
                wx.CallAfter(self.popup_list_menu, focus)
            elif focus is self.output_list:
                # ★この一覧は、それ自体が操作の一覧。黙っていると壊れたと
                #   思われるので、使い方を言う（0.18.3、レビューで判明）
                speech.speak("この一覧は、上下矢印で選んでEnterで実行します",
                             interrupt=True)
            else:
                evt.Skip()
        elif bare and key in self._sr_key_codes:
            # F8/F9 など、設定されたスクリーンリーダー音声トグル
            self.toggle_sr_source(self._sr_key_codes[key])
        elif key in (wx.WXK_LEFT, wx.WXK_RIGHT) and mods in (
            wx.MOD_NONE, wx.MOD_SHIFT
        ):
            # 音声入力一覧にいるときだけ音量調整。他の場所での左右キーは
            # 本来の動き（テキストのカーソル移動など）を邪魔しない。
            if wx.Window.FindFocus() is self.input_list:
                step = (self.config.volume_coarse_step_db
                        if mods == wx.MOD_SHIFT
                        else self.config.volume_step_db)
                sign = 1.0 if key == wx.WXK_RIGHT else -1.0
                self.adjust_selected_volume(sign * step)
            else:
                evt.Skip()
        elif key in (wx.WXK_UP, wx.WXK_DOWN) and mods == wx.MOD_ALT:
            # ソース一覧にいるときだけ重なり順を1段動かす。他の場所での
            # Alt＋上下は本来の動きを邪魔しない。
            # ★一覧は手前が先頭なので、上＝前に出す で向きが一致する
            if wx.Window.FindFocus() is self.item_list:
                self.move_item_layer(key == wx.WXK_UP)
                # ★OSにもキーを渡す（DoAllowNextEvent）。ここで握り潰すと
                #   WM_SYSKEYDOWN が DefWindowProc に届かず、Windows は
                #   「Alt を単独で押して離した」と解釈してメニューバーを
                #   開いてしまう（矢印より先に Alt を離した場合。実測の
                #   Win32 挙動）。リストは Alt＋矢印を無視するので二重には
                #   動かない
                evt.DoAllowNextEvent()
            else:
                evt.Skip()
        elif bare and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            # ★素押しのときだけ。Alt＋上下で重なり順を動かしている最中に
            #   Alt を離す前 Enter を押すと、配信中のソースを非表示に
            #   したりシーンを切り替えたりしてしまう
            if evt.IsAutoRepeat():
                # 押しっぱなしの Enter で同じ操作を繰り返さない（0.18.3。
                # 録画の開始が何度も送られ、切り替えは行ったり来たりする）
                return
            focus = wx.Window.FindFocus()
            if focus is self.scene_list:
                self.activate_selected_scene()
            elif focus is self.item_list:
                self.toggle_selected_item()
            elif focus is self.input_list:
                self.toggle_selected_input()
            elif focus is self.filter_list:
                self.toggle_selected_filter()
            elif focus is self.output_list:
                self.run_selected_output()
            else:
                evt.Skip()
        elif bare and key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME,
                              wx.WXK_END, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            # ★「このリストで選択を動かそうとした」ことを合図にする。
            #   選択が実際に変わったかは見ない。EVT_LISTBOX は、項目が
            #   1つしかないリストや、端で同じ行を選び直したときには
            #   飛ばないので、そこに置かれたソースのフィルターへ
            #   **どこからも辿り着けなくなっていた**（レビューで判明）
            focus = wx.Window.FindFocus()
            if focus in (self.item_list, self.input_list):
                self._filter_follow = focus
                self._last_list = focus
                self._schedule_filter_refresh()
            evt.Skip()
        else:
            evt.Skip()

    def on_close(self, evt: wx.CloseEvent) -> None:
        # ★確認は出さない（0.16.0）。Escape で閉じなくなった以上、
        #   ここへ来るのは Alt+F4 かメニューの「終了」＝意図した操作だけ。
        #   確認を挟むと、閉じるつもりの操作に毎回ひと手間増える
        self._cancel_filter_refresh()
        self._stop_settings_timer()
        self._stop_record_watch()
        self.unregister_global_hotkeys()
        self.conn.close()
        self.Destroy()

    # ------------------------------------------------------------
    # OBSイベント受信（別スレッド。UI操作は必ず wx.CallAfter 経由）
    # ------------------------------------------------------------
    def on_stream_state_changed(self, data) -> None:
        state = getattr(data, "output_state", "")
        active = bool(getattr(data, "output_active", False))
        wx.CallAfter(self._apply_output_state, "stream", state, active)

    def on_record_state_changed(self, data) -> None:
        state = getattr(data, "output_state", "")
        active = bool(getattr(data, "output_active", False))
        if state in (PAUSED, RESUMED):
            # 一時停止・再開は録画中のまま（active は True のまま）。
            # recording フラグは変えず、一時停止フラグと読み上げだけ扱う。
            wx.CallAfter(self._apply_record_pause, state == PAUSED)
            return
        # 停止のときだけ保存先が乗る。ファイル名の読み上げに使う
        path = str(getattr(data, "output_path", "") or "")
        wx.CallAfter(self._apply_output_state, "record", state, active, path)

    def _apply_record_pause(self, paused: bool) -> None:
        """一時停止・再開を反映して読み上げる。

        ★状態要約にも出す。ここで読み上げるだけだと、聞き逃したときに
        確かめる手段が無くなる（F5で分かるようにしておく）。
        放置の見張りもここで起点を合わせる。
        """
        self.snapshot.record_paused = paused
        self.pause_reminder.set_paused(paused, time.monotonic())
        speech.speak(
            "録画を一時停止しました" if paused else "録画を再開しました",
            interrupt=True)
        self._set_status(speech_format.state_summary(self.snapshot))

    def on_current_program_scene_changed(self, data) -> None:
        name = getattr(data, "scene_name", "")
        wx.CallAfter(self._apply_scene_changed, name)

    def on_input_mute_state_changed(self, data) -> None:
        name = getattr(data, "input_name", "")
        muted = bool(getattr(data, "input_muted", False))
        wx.CallAfter(self._apply_mute_changed, name, muted)

    def on_input_volume_changed(self, data) -> None:
        name = getattr(data, "input_name", "")
        db = getattr(data, "input_volume_db", None)
        if not name or not isinstance(db, (int, float)):
            return
        wx.CallAfter(self._apply_volume_changed, name, float(db))

    def on_input_volume_meters(self, data) -> None:
        # 高頻度イベント。重い処理はせず、警告のみUIスレッドへ渡す。
        now = time.monotonic()
        messages: list[str] = []
        for item in getattr(data, "inputs", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("inputName", "")
            if not name:
                continue
            levels = item.get("inputLevelsMul", [])
            peak_db = peak_db_from_levels(levels)
            muted = self._muted.get(name, False)
            # スクリーンリーダー音声は無音が正常なので、無音・クリップ警告の
            # 対象から外す（レベル読み上げ用にピークだけは追跡し続ける）
            is_sr = name in self._sr_by_name
            for w in self.monitor.update(
                name, peak_db, now, muted=muted, suppress_warnings=is_sr
            ):
                messages.append(w.message)
        for msg in messages:
            wx.CallAfter(self._emit_warning, msg)

    def _emit_warning(self, message: str) -> None:
        """レベル警告を読む。モーダル中は溜めておく。

        wx.CallAfter はモーダル表示中も処理されるため、そのまま読むと
        割り込み読み上げでダイアログの案内を切ってしまい、利用者が今
        どこにいるか分からなくなる。閉じたときにまとめて読む。
        """
        if self._modal_depth > 0:
            self._pending_warnings.append(message)
            return
        speech.warn(message)

    def on_scene_created(self, _data) -> None:
        wx.CallAfter(self.refresh_from_obs)

    def on_scene_removed(self, _data) -> None:
        wx.CallAfter(self.refresh_from_obs)

    def on_scene_name_changed(self, data) -> None:
        old = str(getattr(data, "old_scene_name", "") or "")
        new = str(getattr(data, "scene_name", "") or "")
        wx.CallAfter(self._apply_scene_rename, old, new)
        wx.CallAfter(self.refresh_from_obs)

    def on_input_created(self, _data) -> None:
        wx.CallAfter(self.refresh_from_obs)

    def on_input_removed(self, _data) -> None:
        wx.CallAfter(self.refresh_from_obs)

    def on_input_name_changed(self, data) -> None:
        old = str(getattr(data, "old_input_name", "") or "")
        new = str(getattr(data, "input_name", "") or "")
        wx.CallAfter(self._apply_input_rename, old, new)
        wx.CallAfter(self.refresh_from_obs)

    def on_source_filter_enable_state_changed(self, data) -> None:
        source = getattr(data, "source_name", "")
        fname = getattr(data, "filter_name", "")
        enabled = bool(getattr(data, "filter_enabled", False))
        wx.CallAfter(self._apply_filter_enabled, source, fname, enabled)

    def on_source_filter_list_reindexed(self, data) -> None:
        source = getattr(data, "source_name", "")
        wx.CallAfter(self._refresh_filters_if_current, source)

    def on_source_filter_created(self, data) -> None:
        source = getattr(data, "source_name", "")
        wx.CallAfter(self._refresh_filters_if_current, source)

    def on_source_filter_removed(self, data) -> None:
        source = getattr(data, "source_name", "")
        wx.CallAfter(self._refresh_filters_if_current, source)

    def on_scene_item_enable_state_changed(self, data) -> None:
        scene = getattr(data, "scene_name", "")
        item_id = getattr(data, "scene_item_id", None)
        enabled = bool(getattr(data, "scene_item_enabled", False))
        if item_id is None:
            return
        wx.CallAfter(self._apply_item_enabled, scene, int(item_id), enabled)

    def on_scene_item_created(self, data) -> None:
        scene = getattr(data, "scene_name", "")
        wx.CallAfter(self._refresh_items_if_current, scene)

    def on_scene_item_removed(self, data) -> None:
        scene = getattr(data, "scene_name", "")
        wx.CallAfter(self._refresh_items_if_current, scene)

    def on_scene_item_list_reindexed(self, data) -> None:
        scene = getattr(data, "scene_name", "")
        wx.CallAfter(self._refresh_items_if_current, scene)

    def on_virtualcam_state_changed(self, data) -> None:
        state = getattr(data, "output_state", "")
        active = bool(getattr(data, "output_active", False))
        # STARTED/STOPPED のときだけ読む（STARTING/STOPPING は読み上げ対象外）
        if state in (STARTED, STOPPED):
            wx.CallAfter(
                lambda: speech.speak(
                    speech_format.onoff_speech("仮想カメラ", active),
                    interrupt=True))

    def on_replay_buffer_saved(self, data) -> None:
        """リプレイが実際に保存された（OBS本体のホットキーで保存しても来る）。

        ★ここが「本当に保存できた」ことの確認になる。要求を投げた時点では
        まだ書けていないので、読み上げは必ずこちらで行う。
        """
        path = str(getattr(data, "saved_replay_path", "") or "")
        wx.CallAfter(self._apply_replay_saved, path)

    def _apply_replay_saved(self, path: str) -> None:
        self._replay_pending = False
        speech.speak(
            speech_format.replay_saved_speech(
                path if self._announce_file_name() else ""),
            interrupt=True)

    def on_input_settings_changed(self, data) -> None:
        """ソースの設定が変わった（自分の操作でもOBS本体側の操作でも来る）。"""
        name = getattr(data, "input_name", "")
        settings = getattr(data, "input_settings", None)
        if not name or not isinstance(settings, dict):
            return
        wx.CallAfter(self._settings_event, name, dict(settings))

    def on_input_audio_monitor_type_changed(self, data) -> None:
        """音声モニタリングが変わった（OBS本体側で変えたときも来る）。"""
        name = getattr(data, "input_name", "")
        mon = str(getattr(data, "monitor_type", "") or "")
        if not name or not mon:
            return
        wx.CallAfter(
            lambda: speech.speak(
                speech_format.monitor_changed_speech(name, mon),
                interrupt=True))

    def on_media_input_playback_started(self, data) -> None:
        name = getattr(data, "input_name", "")
        if not name:
            return
        wx.CallAfter(
            lambda: speech.speak(
                speech_format.media_started_speech(name), interrupt=True))

    def on_media_input_playback_ended(self, data) -> None:
        name = getattr(data, "input_name", "")
        if not name:
            return
        wx.CallAfter(
            lambda: speech.speak(
                speech_format.media_ended_speech(name), interrupt=True))

    def on_media_input_action_triggered(self, data) -> None:
        """メディア操作のイベント。

        再生(PLAY)は PlaybackStarted 側でも飛ぶので、ここでは読まない
        （media_action_speech が空文字を返す）。
        """
        name = getattr(data, "input_name", "")
        action = str(getattr(data, "media_action", "") or "")
        if not name or not action:
            return
        text = speech_format.media_action_speech(name, action)
        if not text:
            return
        wx.CallAfter(lambda: speech.speak(text, interrupt=True))

    def on_exit_started(self, _data) -> None:
        wx.CallAfter(
            self._handle_disconnect,
            "OBSが終了しました。OBSを起動してから再接続してください")

    # ------------------------------------------------------------
    # UIスレッドでの状態適用
    # ------------------------------------------------------------
    def _apply_output_state(
        self, kind: str, state: str, active: bool, path: str = ""
    ) -> None:
        if kind == "stream":
            self.snapshot.streaming = active
            if state == STARTED:
                speech.speak("配信を開始しました", interrupt=True)
            elif state == STOPPED:
                speech.speak("配信を停止しました", interrupt=True)
        else:
            self.snapshot.recording = active
            if state == STARTED:
                # 前の録画の名残（一時停止・チャプター番号・警告済みの記録）を
                # 畳んでから始める。残すと次の録画の判断を誤らせる
                self.snapshot.record_paused = False
                self._chapter_count = 0
                self._last_record_path = ""
                self.pause_reminder.reset()
                self.disk_watch.reset()
                speech.speak("録画を開始しました", interrupt=True)
            elif state == STOPPED:
                self.snapshot.record_paused = False
                self.pause_reminder.reset()
                self.disk_watch.reset()
                if path:
                    self._last_record_path = path
                speech.speak(
                    speech_format.record_stopped_speech(
                        path if self._announce_file_name() else ""),
                    interrupt=True)
        self.monitor.set_active(
            self._monitor_should_be_active(), time.monotonic())
        self._sync_record_watch()
        self._set_status(speech_format.state_summary(self.snapshot))

    def _apply_scene_changed(self, name: str) -> None:
        if not name:
            return
        self.snapshot.current_scene = name
        if name in self.snapshot.scenes:
            self.scene_list.SetStringSelection(name)
        # SetStringSelection は EVT_LISTBOX を発火しないため、ソース一覧は
        # 自分で追従させる（OBS本体側でシーンを切り替えたときに、シーン
        # 一覧のハイライトとソース一覧の中身が食い違ったままになるのを防ぐ）
        self.refresh_item_list()
        speech.speak(f"シーン {name}", interrupt=True)
        self._set_status(speech_format.state_summary(self.snapshot))

    def _apply_scene_rename(self, old: str, new: str) -> None:
        """シーン名の変更に、設定と一覧の選択を追従させる。

        ★並び順の設定は名前で持っている。追従しないと**設定した位置が
        黙って失われ**（末尾へ回る）、古い名前がゴミとして残り続ける。
        """
        if not old or not new or old == new:
            return
        if self.scene_list.GetStringSelection() == old:
            # ★作り直しで選択が先頭へ飛ばないよう、新しい名前で選び直す
            self._prefer_scene = new
        if self.config.rename_scene(old, new):
            self._save_config()

    def _apply_input_rename(self, old: str, new: str) -> None:
        """ソース（入力）名の変更に、名前で覚えている設定を追従させる。

        ★名前をキーに持つ設定がどれかは Config が知っている
        （Config.rename_input）。UI 側で並べ直すと必ず漏れる。
        ★スクリーンリーダー音声の名前が変わったら索引とメニューを作り直す。
        索引は名前で引くので、古いままだと F8 が「入力がありません。
        作成しますか？」と**同じデバイスの入力を二重に作らせ**、
        名前が変わった方は無音警告の対象から外れなくなる。
        """
        if not old or not new or old == new:
            return
        before = [s.get("name") for s in (self.config.sr_sources or [])
                  if isinstance(s, dict)]
        if not self.config.rename_input(old, new):
            return
        after = [s.get("name") for s in (self.config.sr_sources or [])
                 if isinstance(s, dict)]
        if before != after:
            self._build_sr_index()
            # キーの振り分け（F1 を SR に譲るかどうか）とメニューの文言も
            # 名前・キーから作っているので、まとめて作り直す
            self._build_window_dispatch()
            self._build_menubar()
        self._save_config()

    def _refresh_input_label(self, name: str) -> None:
        """一覧の1行を今の状態（ミュート・音量）で書き直す。"""
        if name not in self._input_names:
            return
        idx = self._input_names.index(name)
        if idx >= self.input_list.GetCount():
            return
        target = self.snapshot.input_by_name(name)
        volume_db = target.volume_db if target is not None else None
        self.input_list.SetString(
            idx,
            speech_format.input_list_label(
                name, self._muted.get(name, False), volume_db))

    def _apply_volume_changed(self, name: str, db: float) -> None:
        """OBSからの音量変更イベントを反映して読み上げる。

        自分の操作でもOBS本体側の操作でも、ここを通るので読み上げは一元化
        される（ミュートと同じ作り）。
        """
        target = self.snapshot.input_by_name(name)
        if target is not None:
            target.volume_db = db
        self._refresh_input_label(name)
        speech.speak(speech_format.volume_speech(name, db), interrupt=True)

    def _refresh_filters_if_current(self, source: str) -> None:
        """今フィルター一覧に出しているソースなら、一覧を作り直す。"""
        if source and source == self._filter_source:
            self.refresh_filter_list()

    def _apply_filter_enabled(
        self, source: str, fname: str, enabled: bool
    ) -> None:
        """フィルターのオン・オフ変更を反映して読み上げる。

        自分の操作でもOBS本体側の操作でも、ここを通るので読み上げは
        一元化される（ミュートと同じ作り）。今フィルター一覧に出している
        ソースのものだけ、一覧のラベルも更新する。
        """
        if source == self._filter_source and fname in self._filter_names:
            idx = self._filter_names.index(fname)
            if idx < self.filter_list.GetCount():
                self.filter_list.SetString(
                    idx, speech_format.filter_list_label(fname, enabled))
        speech.speak(
            speech_format.filter_toggle_speech(fname, enabled), interrupt=True)

    def _refresh_items_if_current(self, scene: str) -> None:
        """今ソース一覧に出しているシーンなら、一覧を作り直す。"""
        if scene and scene == self._item_scene:
            self.refresh_item_list()

    def _apply_item_enabled(
        self, scene: str, item_id: int, enabled: bool
    ) -> None:
        """シーン内ソースの表示・非表示の変更を反映して読み上げる。

        イベントは item_id で来るので、名前は保持している対応表から引く。
        今ソース一覧に出しているシーンのものだけ、一覧のラベルも更新する。
        """
        name = self._item_names.get(item_id, "")
        if scene == self._item_scene and item_id in self._item_ids:
            idx = self._item_ids.index(item_id)
            if not name:
                name = self._item_names.get(item_id, "")
            if idx < self.item_list.GetCount() and name:
                self.item_list.SetString(
                    idx, speech_format.scene_item_list_label(name, enabled))
        if not name:
            # 対応表に無い（別シーンのソース等）。読み上げは控える
            return
        speech.speak(
            speech_format.scene_item_toggle_speech(name, enabled),
            interrupt=True)

    def _mute_caveat(self, name: str, muted: bool) -> str:
        """ミュートの読み上げに添える補足（モニタリングとの食い違い）。

        ミュートは配信・録画に乗せないだけで、自分の耳へ返すモニタリングは
        止めない。実機で「BGMをミュートしたのに鳴り続ける」が起きたため、
        読み上げ側で必ず伝える（判断材料が読み上げしかないので、黙ると
        原因に辿り着けない）。モニタリング設定は一覧の作り直しごとに全入力
        ぶん引くと重いので、ミュートが変わったこの瞬間だけ問い合わせる。
        """
        if not self.conn.connected:
            return ""
        mon = commands.fetch_monitor_type(self.conn.req, name)
        if not mon:
            return ""
        target = self.snapshot.input_by_name(name)
        kind = target.kind if target is not None else ""
        media_state = ""
        if props.is_media_kind(kind):
            # メディアは「今鳴っているか」で案内を変える。止まっているBGMに
            # 「聞こえ続けます」と言うと嘘になるため（利用者の指摘で修正）。
            media_state, _cur, _dur = commands.fetch_media_status(
                self.conn.req, name)
            if not media_state:
                # 状態が分からないメディアには何も言わない。確かでない案内は
                # 出さない方針（読み上げが唯一の判断材料なので嘘が重い）。
                return ""
        return speech_format.mute_monitor_caveat(muted, mon, media_state)

    def _apply_mute_changed(self, name: str, muted: bool) -> None:
        if not name:
            return
        self._muted[name] = muted
        target = self.snapshot.input_by_name(name)
        if target is not None:
            target.muted = muted
        self._refresh_input_label(name)
        # スクリーンリーダー音声の作成直後に飛ぶミュートイベントは、
        # 作成成功メッセージと二重にならないよう1回だけ読み上げを抑止する
        if name in self._sr_by_name and name in self._sr_setup_pending:
            self._sr_setup_pending.discard(name)
            return
        caveat = self._mute_caveat(name, muted)
        tail = f"。{caveat}" if caveat else ""
        if name in self._sr_by_name:
            if muted:
                speech.speak(f"{name}を配信から外しました{tail}", interrupt=True)
            else:
                speech.speak(f"{name}を配信に乗せます{tail}", interrupt=True)
        else:
            if muted:
                speech.speak(f"{name}をミュートしました{tail}", interrupt=True)
            else:
                speech.speak(f"{name}のミュートを解除しました{tail}",
                             interrupt=True)
