# -*- coding: utf-8 -*-
"""OBS に繋がずに、wx のウィジェットを実際に作って動かす煙試験。

★run_tests.py には入れていない（wx.App を作るので重く、環境に依存する）。
手で走らせる:

    python -X utf8 tests/smoke_ui.py

ここが見ているのは**純ロジックのテストが届かない層**——一覧を作り直した
ときに選択がどこへ行くか、リネームで索引が付いてくるか、並べ替えの保存が
何を返すか。2026-09-02 のレビューで見つかった不具合は、ほぼ全部この層に
あった（テストは 1200 件すべて通っていたのに）。
"""
import io
import os
import sys

os.environ["OBSNAVI_SILENT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx  # noqa: E402

import speech  # noqa: E402
import ui.main_frame as mf  # noqa: E402
from core.config import Config  # noqa: E402
from core.connection import ObsConnectError  # noqa: E402
from core.state import AudioInput, Snapshot  # noqa: E402
from ui.prop_dialog import OrderDialog  # noqa: E402

fails = []


def _refuse_connect(self, callbacks=None):
    raise ObsConnectError("煙試験では OBS に接続しない")


# ★本物の OBS には絶対に繋がない。フレームは作った 0.6 秒後に接続を
#   始める（wx.CallLater）ので、窓を出してイベントを回す試験があると、
#   利用者の OBS へ実際に接続してしまう。接続そのものを断っておく
mf.ObsConnection.connect = _refuse_connect


def check(name, cond, detail=""):
    print(("[OK] " if cond else "[NG] ") + name + ("" if cond else f" -> {detail}"))
    if not cond:
        fails.append(name)


def snap(scenes, current, inputs):
    s = Snapshot(connected=True)
    s.scenes = list(scenes)
    s.current_scene = current
    s.audio_inputs = [AudioInput(name=n, muted=False, volume_db=0.0)
                      for n in inputs]
    return s


def _sandbox_config() -> Config:
    """設定ファイルへ絶対に書かない Config を作る。

    ★これを忘れると、この煙試験が**利用者の実際の設定を既定値で
    上書きする**（フレームの中では設定変更のたびに save が走る）。
    2026-09-03 に実際にやってしまい、git から戻した。
    Config は読み込みに失敗したときのために「保存しない」状態を
    持っているので、それをそのまま使う。
    """
    cfg = Config()
    cfg._save_blocked = True
    return cfg


CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "obs_navi_config.json")
_before = (io.open(CONFIG_PATH, "rb").read()
           if os.path.exists(CONFIG_PATH) else None)

app = wx.App()
frame = mf.MainFrame(_sandbox_config())

# --- 1. シーンの選択が配信中のシーンへ飛ばない ---
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["マイク", "BGM"]))
check("最初は現在のシーンを選ぶ",
      frame.scene_list.GetStringSelection() == "配信",
      frame.scene_list.GetStringSelection())
frame.scene_list.SetStringSelection("休憩")
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["マイク", "BGM"]))
check("作り直しても選んでいたシーンのまま",
      frame.scene_list.GetStringSelection() == "休憩",
      frame.scene_list.GetStringSelection())

# --- 2. 音声入力の選択が名前で残る ---
frame.input_list.SetSelection(1)
check("BGM を選んでいる", frame._selected_input_name() == "BGM",
      frame._selected_input_name())
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["デスクトップ", "マイク", "BGM"]))
check("上に増えても同じ入力のまま", frame._selected_input_name() == "BGM",
      frame._selected_input_name())
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["マイク", "BGM"]))
check("上が消えても同じ入力のまま", frame._selected_input_name() == "BGM",
      frame._selected_input_name())
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["マイク"]))
check("消えたら先頭へ", frame._selected_input_name() == "マイク",
      frame._selected_input_name())

# --- 3. シーンのリネームで選択が残る ---
frame.apply_snapshot(snap(["配信", "休憩"], "配信", ["マイク"]))
frame.scene_list.SetStringSelection("休憩")
frame.config.list_order["scenes"] = ["休憩", "配信"]
frame._apply_scene_rename("休憩", "待機")
frame.apply_snapshot(snap(["配信", "待機"], "配信", ["マイク"]))
check("リネームしても選択が残る",
      frame.scene_list.GetStringSelection() == "待機",
      frame.scene_list.GetStringSelection())
check("並び順の設定も追従",
      frame.config.list_order["scenes"] == ["待機", "配信"],
      str(frame.config.list_order))

# --- 4. 入力のリネームで SR の索引が付いてくる ---
before = sorted(frame._sr_by_name)
frame._apply_input_rename("NVDA音声", "読み上げ音声")
check("SR索引が新しい名前になる",
      "読み上げ音声" in frame._sr_by_name and "NVDA音声" not in frame._sr_by_name,
      str(sorted(frame._sr_by_name)) + " / was " + str(before))
check("メニューを作り直しても壊れない",
      frame.GetMenuBar() is not None and frame.GetMenuBar().GetMenuCount() > 0)

# --- 5. 接続していないときの「今あるもの」 ---
check("未接続なら見えている分だけ", frame._all_item_names() == set(),
      str(frame._all_item_names()))

# --- 6. リストのメニューが4種類とも組める ---
for lst, label in ((frame.scene_list, "シーン"), (frame.item_list, "ソース"),
                   (frame.input_list, "音声入力"), (frame.filter_list, "フィルター")):
    menu = frame.build_list_menu(lst)
    check(f"{label}一覧のメニューが組める", menu.GetMenuItemCount() > 0)
    menu.Destroy()

# --- 7. 並べ替えダイアログの保存判断 ---
dlg = OrderDialog(frame, "ソース一覧の並び順", ["ゲーム", "マイク"], ["ゲーム"],
                  present={"ゲーム", "マイク", "テロップ"})
check("開いてそのままなら設定が変わらない",
      dlg.result_order() == ["ゲーム"], str(dlg.result_order()))
dlg._reset_order()
check("戻すと既定＋他シーンのぶん", dlg.rows == ["ゲーム", "マイク"], str(dlg.rows))
check("戻して既定なら空を保存", dlg.result_order() == [], str(dlg.result_order()))
dlg.Destroy()

dlg = OrderDialog(frame, "ソース一覧の並び順", ["ゲーム", "マイク"],
                  ["テロップ", "ゲーム"],
                  present={"ゲーム", "マイク", "テロップ"})
check("他シーンのソースは「今はありません」にしない",
      OrderDialog.MISSING_MARK not in dlg._row_label(0), dlg._row_label(0))
check("開いてそのままなら設定が変わらない（他シーン込み）",
      dlg.result_order() == ["テロップ", "ゲーム"], str(dlg.result_order()))
dlg._reset_order()
check("戻しても他シーンのぶんは残す",
      dlg.rows == ["ゲーム", "マイク", "テロップ"], str(dlg.rows))
check("残りがあるので明示的に保存する",
      dlg.result_order() == ["ゲーム", "マイク", "テロップ"],
      str(dlg.result_order()))
dlg.Destroy()

dlg = OrderDialog(frame, "レベル読み上げの順番", ["マイク", "BGM"], [],
                  by_name=True)
check("設定が空なら空のまま", dlg.result_order() == [], str(dlg.result_order()))
dlg.order_list.SetSelection(0)
dlg._move(1)
check("動かしたら明示的に保存", dlg.result_order() == ["マイク", "BGM"]
      or dlg.result_order() == ["BGM", "マイク"], str(dlg.result_order()))
dlg.Destroy()

# --- 配信・録画のボタンとキー（0.18.0） ---
items = list(frame.output_list.GetItems())
check("配信・録画リストに4項目、キーつき",
      items == ["配信を開始 Ctrl+S", "配信を停止 Ctrl+Shift+S",
                "録画を開始 Ctrl+R", "録画を停止 Ctrl+Shift+R"], str(items))
check("最初から先頭が選ばれている", frame.output_list.GetSelection() == 0)
# Tab 順＝パネルの子の並び順。状態欄の直後に配信・録画リスト、次にシーン一覧
focusable = [w for w in frame.panel.GetChildren() if w.AcceptsFocus()]
check("Tab順: 状態欄→配信・録画→シーン一覧",
      focusable[:3] == [frame.status_text, frame.output_list,
                        frame.scene_list],
      str([w.GetName() for w in focusable[:3]]))
check("項目の並びと実行する処理が対応",
      frame._output_actions == [frame.start_stream, frame.stop_stream,
                                frame.start_record, frame.stop_record])
ctrl_shift = wx.MOD_CONTROL | wx.MOD_SHIFT
check("Ctrl+S が配信を開始へ",
      frame._window_dispatch.get((wx.MOD_CONTROL, ord("S")))
      == frame.start_stream)
check("Ctrl+Shift+S が配信を停止へ",
      frame._window_dispatch.get((ctrl_shift, ord("S"))) == frame.stop_stream)
check("Ctrl+R が録画を開始へ",
      frame._window_dispatch.get((wx.MOD_CONTROL, ord("R")))
      == frame.start_record)
check("Ctrl+Shift+R が録画を停止へ",
      frame._window_dispatch.get((ctrl_shift, ord("R"))) == frame.stop_record)
check("キー割り当ての問題が報告されていない",
      frame._key_problems == [], str(frame._key_problems))
labels = [frame.GetMenuBar().GetMenu(0).FindItemByPosition(i).GetItemLabel()
          for i in (0, 1, 3, 4)]
check("メニューにもキーが出る",
      labels == ["配信を開始	Ctrl+S", "配信を停止	Ctrl+Shift+S",
                 "録画を開始	Ctrl+R", "録画を停止	Ctrl+Shift+R"],
      str(labels))

# --- 0.18.3: 窓の中の欄が高さ 0 に潰れない（文字の大きさ4通り） ---
# ★0.18.1 で配信・録画の一覧を足したら、起動時の窓（640×640）に入り
#   きらず、フィルター一覧が 9 ポイントでも高さ 0 になっていた。潰れた
#   欄は Tab で止まり名前も読まれるが、選んでいる項目が読まれない。
#   文字の大きさで潰れ始めが動くので
#   複数通りで見る


def _walk(w):
    yield w
    for c in w.GetChildren():
        yield from _walk(c)


def _quiet_frame():
    """グローバルキーを登録しない（動いている OBSナビとぶつけない）窓。"""
    cfg = _sandbox_config()
    cfg.global_hotkeys_enabled = False
    return mf.MainFrame(cfg)


# ★文字は画面を作る前に決める（子は作るときに親の文字を継ぐ）。作った
#   あとで欄ごとに文字を変えて FitInside や Layout を試験の側から呼ぶと、
#   素の wx.Panel でも仮想の大きさで並び直されて潰れが隠れ、直す前の
#   実装でも通ってしまった（試験が効くかを確かめたときに判明）
_font_pt = [9]
_orig_build_ui = mf.MainFrame._build_ui


def _build_ui_at_size(self):
    self.SetFont(wx.Font(_font_pt[0], wx.FONTFAMILY_DEFAULT,
                         wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
    _orig_build_ui(self)


mf.MainFrame._build_ui = _build_ui_at_size
for pt in (9, 11, 14, 18):
    _font_pt[0] = pt
    lf = _quiet_frame()
    lf.Show()
    wx.Yield()
    check(f"{pt}ポイントの文字で作れた",
          lf.filter_list.GetFont().GetPointSize() == pt,
          str(lf.filter_list.GetFont().GetPointSize()))
    flat = [f"{w.GetName()}={w.GetSize().height}"
            for w in _walk(lf.panel)
            if w is not lf.panel and w.AcceptsFocus()
            and w.GetSize().height <= 1]
    check(f"{pt}ポイントで高さ0に潰れた欄が無い", not flat, "、".join(flat))
    lf.Destroy()
    wx.Yield()
mf.MainFrame._build_ui = _orig_build_ui

# --- 0.18.3: 配信・録画のキー（2回押し・押しっぱなし・案内） ---
sent, said = [], []
_saved = {n: getattr(mf.commands, n)
          for n in ("start_stream", "stop_stream", "start_record",
                    "stop_record")}
for _n in _saved:
    setattr(mf.commands, _n, (lambda name: lambda _c: sent.append(name))(_n))
_saved_speak = speech.speak
speech.speak = lambda text, *a, **k: said.append(text)

kf = _quiet_frame()
kf._require_connection = lambda: True
kf.snapshot.streaming = True
kf.snapshot.recording = False
acts = kf._hotkey_actions()


def press(aid):
    """グローバルキーが届いたときと同じ呼び方をする。"""
    kf._run_hotkey_action(acts[aid], aid)


press("stream_stop")
check("1回目では配信を止めない", sent == [], str(sent))
check("1回目の案内は短い（キー名も秒数も言わない）",
      said[-1:] == ["もう一度押すと配信を停止します"], str(said))
press("stream_stop")
check("2回目で配信を止める", sent == ["stop_stream"], str(sent))
check("決まったらすぐ言う", "配信を停止します" in said, str(said))

sent.clear()
kf._repeat_confirm.reset()
press("stream_stop")
press("record_start")
press("stream_stop")
check("別のキー（録画の開始）を挟んだら取り消す",
      "stop_stream" not in sent, str(sent))

sent.clear()
kf._repeat_confirm.reset()
press("stream_stop")
press("stream_start")          # すでに配信中なので早めに終わる
press("stream_stop")
check("もう一方の配信キーを挟んでも取り消す",
      "stop_stream" not in sent, str(sent))

sent.clear()
kf._repeat_confirm.reset()
press("stream_stop")
kf._modal_depth = 1
press("record_start")          # 別の画面を開いているので断られる
kf._modal_depth = 0
press("stream_stop")
check("断られたキーを挟んでも取り消す", "stop_stream" not in sent, str(sent))


class FakeKey:
    """on_char_hook に渡す、キー入力の代わり。"""

    def __init__(self, code, mods=wx.MOD_NONE, repeat=False):
        self._code, self._mods, self._repeat = code, mods, repeat
        self.skipped = False

    def GetKeyCode(self):
        return self._code

    def GetModifiers(self):
        return self._mods

    def IsAutoRepeat(self):
        return self._repeat

    def Skip(self, skip=True):
        self.skipped = skip

    def DoAllowNextEvent(self):
        pass


sent.clear()
kf.on_char_hook(FakeKey(ord("R"), wx.MOD_CONTROL))
check("Ctrl+R で録画の開始を1回送る", sent == ["start_record"], str(sent))
sent.clear()
kf.on_char_hook(FakeKey(ord("R"), wx.MOD_CONTROL, repeat=True))
check("押しっぱなしのリピートでは送らない", sent == [], str(sent))

kf.Show()
kf.Raise()
kf.output_list.SetFocus()
wx.Yield()
if wx.Window.FindFocus() is kf.output_list:
    kf.output_list.SetSelection(2)      # 録画を開始
    sent.clear()
    kf.on_char_hook(FakeKey(wx.WXK_RETURN))
    check("一覧の Enter で録画の開始を送る", sent == ["start_record"],
          str(sent))
    sent.clear()
    kf.on_char_hook(FakeKey(wx.WXK_RETURN, repeat=True))
    check("一覧の Enter も押しっぱなしでは送らない", sent == [], str(sent))
    said.clear()
    kf.on_char_hook(FakeKey(wx.WXK_WINDOWS_MENU))
    check("一覧でアプリケーションキーを押したら案内を読む",
          any("上下矢印" in t for t in said), str(said))
else:
    check("配信・録画の一覧にフォーカスを置けた", False,
          str(wx.Window.FindFocus()))

# --- 0.18.4: 「OBSナビについて」がライセンスの告知まで読む ---
# ★GPL-3.0 の「適切な法的告知」。文言は speech_format の試験が見るので、
#   ここはメニューの処理から実際に読まれること（配線）だけを見る
said.clear()
kf.on_about(None)
check("OBSナビについて でライセンスの告知を読む",
      bool(said) and "GPL 第3版" in said[-1] and "LICENSE.txt" in said[-1],
      str(said))
check("OBSナビについて で AI を使って作ったことを読む",
      bool(said) and "AI" in said[-1] and "作りました" in said[-1],
      str(said))

for _n, _fn in _saved.items():
    setattr(mf.commands, _n, _fn)
speech.speak = _saved_speak
kf.Destroy()

# --- 録画の音声トラック割り当て（0.19.0） ---
import ui.prop_dialog as pd  # noqa: E402

said2 = []
_saved_speak2 = speech.speak
speech.speak = lambda text, *a, **k: said2.append(text)
_saved_warn = speech.warn
speech.warn = lambda text, *a, **k: said2.append("[警告] " + text)
_fake = {"tracks": {"Logic": [True, True, False, False, False, False]},
         "rec": [True, True, True, True, False, False],
         "writes": []}
_saved_cmd = {n: getattr(mf.commands, n) for n in (
    "fetch_input_audio_tracks", "set_input_audio_track",
    "fetch_record_tracks", "apply_record_tracks")}
mf.commands.fetch_input_audio_tracks = (
    lambda _c, name: tuple(_fake["tracks"][name])
    if name in _fake["tracks"] else None)


def _set_track(_c, name, number, on):
    _fake["tracks"][name][number - 1] = on


def _apply_rec(_c, section, states):
    _fake["writes"].append((section, tuple(states)))
    _fake["rec"] = list(states)


mf.commands.set_input_audio_track = _set_track
mf.commands.fetch_record_tracks = lambda _c: {
    "section": "AdvOut", "tracks": tuple(_fake["rec"]), "quality": ""}
mf.commands.apply_record_tracks = _apply_rec
frame._require_connection = lambda: True

# ソースのトラックを入り切りする（トラック5は録画されていない）
said2.clear()
got = frame.apply_input_track("Logic", 5, True)
check("ソースのトラックを足して読み直す", got is not None and got[4] is True,
      str(got))
check("足したことと今の全体を言う",
      any("トラック5に出しました" in t and "今はトラック1、2、5" in t
          for t in said2), str(said2))
check("録画されないトラックなら、そのことも言う",
      any("今は録画されていません" in t for t in said2), str(said2))

# 録画するトラック: 録画中は断る
frame.snapshot.recording = True
said2.clear()
info = mf.commands.fetch_record_tracks(None)
check("録画中は録画のトラックを変えない",
      frame.apply_record_track(info, 5, True) is None
      and _fake["writes"] == [], str(said2))
check("録画中だと言う", any("録画中は" in t for t in said2), str(said2))
frame.snapshot.recording = False
said2.clear()
got = frame.apply_record_track(info, 5, True)
check("録画しないときは書いて読み直す",
      got == (True, True, True, True, True, False), str(got))
check("次の録画から効くと言う",
      any("次の録画から" in t for t in said2), str(said2))

# 録画のトラック設定の画面（リスト1本。1行1トラック）
pd.commands.fetch_record_tracks = mf.commands.fetch_record_tracks
rdlg = pd.RecordTracksDialog(frame)
items = list(rdlg.prop_list.GetItems())
check("録画のトラック設定に6本と2つの行",
      len(items) == 8 and items[0] == "トラック1を録画する、オン"
      and items[5] == "トラック6を録画する、オフ", str(items))
check("一覧に名前", rdlg.prop_list.GetName() == "録画するトラック")
rdlg.prop_list.SetSelection(5)
rdlg.activate_selected()
check("Enter でトラック6を録画する",
      rdlg.prop_list.GetString(5) == "トラック6を録画する、オン",
      rdlg.prop_list.GetString(5))
rdlg.Destroy()

# まとめて読む
said2.clear()
frame.snapshot.audio_inputs = [AudioInput(name="Logic", muted=False,
                                          volume_db=0.0),
                               AudioInput(name="マイク", muted=False,
                                          volume_db=0.0)]
_fake["tracks"]["マイク"] = [False] * 6
frame.announce_tracks_overview()
check("割り当てをまとめて読む",
      any("Logic はトラック1、2、5" in t for t in said2), str(said2))
check("録画に入らないソースを言い当てる",
      any("次のソースは録画に入りません。マイク" in t for t in said2),
      str(said2))
# ★メニューは変数で持っておく（一時の wx.Menu のまま項目を引くと、
#   先に消えて空に見える）
_menu = frame.build_list_menu(frame.input_list)
labels = [it.GetItemLabelText() for it in _menu.GetMenuItems()
          if not it.IsSeparator()]
_menu.Destroy()
check("音声入力一覧の操作メニューにも入口",
      "録画のトラック割り当てを読む" in labels, str(labels))

for _n, _fn in _saved_cmd.items():
    setattr(mf.commands, _n, _fn)
pd.commands.fetch_record_tracks = _saved_cmd["fetch_record_tracks"]
speech.speak = _saved_speak2
speech.warn = _saved_warn

frame.Destroy()
app.Destroy()

# ★最後に必ず確かめる。設定ファイルに触っていたら、それ自体が不具合
after = (io.open(CONFIG_PATH, "rb").read()
         if os.path.exists(CONFIG_PATH) else None)
check("設定ファイルに書き込んでいない", after == _before,
      "obs_navi_config.json が書き換わった")

print("FAILS:", fails)
sys.exit(1 if fails else 0)
