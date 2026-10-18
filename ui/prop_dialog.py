# -*- coding: utf-8 -*-
"""ソースの設定（プロパティ）編集ダイアログ。

アクセシビリティ方針（メインウィンドウと同じ）:
- コントロールは「リスト1本＋ボタン3個」だけに固定する。
  値の編集はすべてOS標準のダイアログ（選択・数値入力・ファイル選択）へ
  委譲する。項目ごとにコントロールを作る方式は、ラベルとコントロールの
  対応を1組でも間違えるとスクリーンリーダーが無言になる事故が起きやすく、
  その面積を増やしたくないため。
- ラベル用 StaticText は対応するコントロールの直前に生成する。
- 選択肢の取得は「その行で Enter を押したとき」だけ行う（開いた瞬間に
  全項目ぶん問い合わせると数秒待たされるため）。
"""
from __future__ import annotations

import os

import wx

import speech
from core import (
    commands, filters, ordering, props, scenes, speech_format, tracks,
    volume)

AUDIO_WILDCARD = (
    "音声ファイル|*.mp3;*.wav;*.ogg;*.flac;*.m4a;*.aac;*.opus"
    "|動画ファイル|*.mp4;*.mkv;*.mov;*.webm;*.avi"
    "|すべてのファイル|*.*")
IMAGE_WILDCARD = (
    "画像ファイル|*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"
    "|すべてのファイル|*.*")

# 種類 → (ダイアログの見出し, ワイルドカード)
FILE_KINDS = {
    "audio": ("音楽や動画のファイルを選んでください", AUDIO_WILDCARD),
    "image": ("画像ファイルを選んでください", IMAGE_WILDCARD),
}

# メディアソースに足す操作行（設定値ではなく動作）
_MEDIA_ROWS = [
    ("再生・一時停止", ""),           # 状態を見て決めるので action は実行時に決定
    ("停止", props.MEDIA_STOP),
    ("最初から", props.MEDIA_RESTART),
]


class SourcePropDialog(wx.Dialog):
    """選択中ソースの設定を一覧・変更するダイアログ。"""

    def __init__(self, frame, source_name: str, kind: str) -> None:
        super().__init__(frame, title=f"{source_name} の設定")
        self.frame = frame
        self.source_name = source_name
        self.kind = kind
        self.specs = props.specs_for_kind(kind)
        self.settings: dict = {}
        self.media_state: str = ""
        self.media_cursor = None
        self.media_duration = None
        # 行の実体: ("prop", spec) / ("action", label, action) / ("none", ...)
        self._rows: list[tuple] = []
        self._load_state()
        self._build_ui()
        self.SetSize((520, 420))
        self.SetEscapeId(wx.ID_CANCEL)
        # 明示的にリストへフォーカスを置く。置かないと既定ボタンに載って
        # 「空のダイアログ」に聞こえる。
        # ★表示される前の SetFocus は載らないことがあるので、実際に
        #   表示されたあとにもう一度置く（EVT_SHOW）。
        self.prop_list.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            wx.CallAfter(self.focus_list)
        evt.Skip()

    def focus_list(self) -> None:
        """設定項目リストへフォーカスを戻す。

        どこにもフォーカスが無い状態になるとスクリーンリーダーが
        何も読まなくなるため、子ダイアログを閉じたあとは必ず呼ぶ。
        """
        try:
            self.prop_list.SetFocus()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------
    # 状態の取得
    # ------------------------------------------------------------
    def _load_state(self) -> None:
        """OBSから現在の設定を読む。

        選択肢の一覧は原則ここでは取りに行かない（開くのが遅くなるため）。
        例外は device_id で、値が GUID なので一覧を引かないと現在値を
        読み上げられない。デバイス列挙は速いのでここで1回だけ引く。
        """
        client = self.frame.conn.req
        try:
            self.settings = commands.fetch_merged_settings(
                client, self.source_name, self.kind)
        except Exception:  # noqa: BLE001
            self.settings = {}
        self._value_names: dict[str, dict] = {}
        for spec in self.specs:
            # 値がGUIDやデバイスのパスで、一覧を引かないと現在値を読み上げ
            # られない項目。列挙は速いのでここで1回だけ引く
            if spec.type == "list" and spec.key in ("device_id",
                                                    "video_device_id"):
                items = commands.fetch_property_items(
                    client, self.source_name, spec.key)
                self._value_names[spec.key] = {
                    it.get("itemValue"): it.get("itemName", "")
                    for it in items}
        # 音声モニタリングは設定値ではなく専用APIなので別に読む。
        # 取れた＝音声を持つ入力、なので行を出すかの判定も兼ねる。
        self.monitor_type = commands.fetch_monitor_type(client, self.source_name)
        # 録画の音声トラック（トラック1〜6のオン・オフ）。音声を持たない
        # 入力では None（行を出さない）
        self.input_tracks = commands.fetch_input_audio_tracks(
            client, self.source_name)
        if props.is_media_kind(self.kind):
            self.media_state, self.media_cursor, self.media_duration = (
                commands.fetch_media_status(client, self.source_name))

    def _build_rows(self) -> list[str]:
        """一覧に出す行文字列を作り、対応表(_rows)も更新する。"""
        self._rows = []
        labels: list[str] = []
        if (not self.specs and not self.monitor_type
                and self.input_tracks is None):
            self._rows.append(("none",))
            labels.append("このソースの設定は、このアプリでは変えられません")
            return labels
        # 音声を持つ入力なら、まずモニタリングを出す。
        # 「入れたのに聞こえない」の原因はたいていここなので上に置く。
        if self.monitor_type:
            self._rows.append(("monitor",))
            labels.append(speech_format.prop_row_label(
                props.MONITOR_SPEC.label,
                props.monitor_label(self.monitor_type)))
        for spec in self.specs:
            raw = self.settings.get(spec.key)
            value_text = self._value_text(spec, raw)
            self._rows.append(("prop", spec))
            labels.append(speech_format.prop_row_label(spec.label, value_text))
        if props.is_media_kind(self.kind):
            for label, action in _MEDIA_ROWS:
                self._rows.append(("action", label, action))
                if action:
                    labels.append(label)
                else:
                    state = speech_format.media_state_jp(self.media_state)
                    labels.append(f"{label}、今は {state}")
        # 録画の音声トラック。1行1トラックで、Enter で入り切りする
        # （OBS 本体の「オーディオの詳細プロパティ」のチェックの表に当たる。
        #   表はスクリーンリーダーで扱いにくいので、オン・オフの行に並べ直した）
        if self.input_tracks is not None:
            for number in tracks.TRACK_NUMBERS:
                self._rows.append(("track", number))
                labels.append(speech_format.input_track_row(
                    number, self.input_tracks[number - 1]))
        return labels

    def _value_text(self, spec, raw) -> str:
        """項目1つの現在値を読み上げ用の文字列にする。

        window は設定値そのものが "タイトル:クラス:実行ファイル" という
        記号だらけの文字列なので、一覧を引かずにここで読める形へ直す。
        device_id は GUID なので、開いたときに引いた対応表から名前を出す。
        """
        if spec.type == "list":
            if spec.key == "window":
                return speech_format.window_value_label(str(raw or ""))
            names = getattr(self, "_value_names", {}).get(spec.key)
            if names:
                name = names.get(raw)
                if name:
                    return speech_format.device_item_label(name, True)
        return props.format_value(spec, self.kind, raw)

    def _refresh_list(self, keep_selection: bool = True) -> None:
        idx = self.prop_list.GetSelection() if keep_selection else wx.NOT_FOUND
        labels = self._build_rows()
        self.prop_list.Set(labels)
        if labels:
            if 0 <= idx < len(labels):
                self.prop_list.SetSelection(idx)
            else:
                self.prop_list.SetSelection(0)

    # ------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------
    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("設定パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="設定項目（Enterで変更）")
        self.prop_list = wx.ListBox(panel, size=(-1, 260))
        self.prop_list.SetName("設定項目")
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.prop_list, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_reload = self._button(panel, "読み直す", self.on_reload)
        self.btn_obs = self._button(
            panel, "OBSのプロパティ画面を開く", self.on_open_obs)
        self.btn_close = wx.Button(panel, wx.ID_CANCEL, "閉じる")
        self.btn_close.SetName("閉じる")
        for btn in (self.btn_reload, self.btn_obs, self.btn_close):
            row.Add(btn, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)

        panel.SetSizer(root)
        self._refresh_list(keep_selection=False)

    def _button(self, parent, label: str, handler) -> wx.Button:
        btn = wx.Button(parent, label=label)
        btn.SetName(label)
        btn.Bind(wx.EVT_BUTTON, handler)
        return btn

    # ------------------------------------------------------------
    # 行の実行
    # ------------------------------------------------------------
    def activate_selected(self) -> None:
        idx = self.prop_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._rows):
            return
        row = self._rows[idx]
        if row[0] == "none":
            self.on_open_obs(None)
            return
        if row[0] == "monitor":
            self._choose_monitor()
            return
        if row[0] == "action":
            self._run_media_action(row[1], row[2])
            return
        if row[0] == "track":
            self._toggle_track(row[1])
            return
        spec = row[1]
        if spec.type == "bool":
            self._toggle_bool(spec)
        elif spec.type == "list":
            self._choose_list(spec)
        elif spec.type == "int":
            self._enter_int(spec)
        elif spec.type == "file":
            self._choose_file(spec)
        elif spec.type == "text":
            self._enter_text(spec)
        elif spec.type == "choice":
            self._choose_fixed(spec)

    def _apply(self, patch: dict, labels) -> None:
        """設定変更を投げる。読み上げはフレーム側のイベントで行う。"""
        ok = self.frame.apply_props_change(self.source_name, patch, labels)
        if ok:
            # 送った値で手元の表示を更新する（OBSの反映は映像ソースだと
            # 1フレーム遅れるので、読み直しに頼らず楽観的に更新する）
            self.settings.update(patch)
            self._refresh_list()

    def _toggle_bool(self, spec) -> None:
        new_value = not bool(self.settings.get(spec.key))
        text = "オン" if new_value else "オフ"
        self._apply({spec.key: new_value}, [(spec.label, text)])

    def _choose_list(self, spec) -> None:
        speech.speak(f"{spec.label}の候補を読み込みます", interrupt=True)
        items = commands.fetch_property_items(
            self.frame.conn.req, self.source_name, spec.key)
        items = props.dedupe_items(items)
        if spec.running_flag:
            items = props.sort_window_items(items)
        if not items:
            speech.warn(f"{spec.label} の候補が取得できません")
            return
        if spec.key in ("device_id", "video_device_id"):
            rows = [speech_format.device_item_label(
                it.get("itemName", ""), it.get("itemEnabled", True))
                for it in items]
        elif spec.running_flag:
            rows = [speech_format.window_item_label(
                it.get("itemName", ""), it.get("itemEnabled", True))
                for it in items]
        else:
            rows = [props.value_label(self.kind, spec.key,
                                      it.get("itemValue"),
                                      it.get("itemName", ""))
                    for it in items]
        current = self.settings.get(spec.key)
        sel = props.index_of_value(items, current)
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{spec.label}、{len(rows)}件", spec.label, rows)
            try:
                if sel >= 0:
                    dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ずここで判定
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if not (0 <= idx < len(items)):
            return
        value = items[idx].get("itemValue")
        patch = {spec.key: value}
        # ウィンドウ指定は一致方式も一緒に送らないと、タイトルが変わった
        # ときに見失う（UWPは逆に狭くなるので送らない）
        if spec.key == "window":
            priority = props.window_priority_for(str(value))
            if priority is not None:
                patch["priority"] = priority
        self._apply(patch, [(spec.label, rows[idx])])

    def _enter_int(self, spec) -> None:
        current = self.settings.get(spec.key, spec.min_value)
        message = (f"{spec.label}を数値で入力してください。\n"
                   f"今は {current}{spec.unit} です。\n"
                   f"{spec.min_value} から {spec.max_value} まで。")
        with self.frame.modal():
            dlg = wx.TextEntryDialog(
                self, message, spec.label, value=str(current))
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                text = dlg.GetValue()
            finally:
                dlg.Destroy()
                self.focus_list()
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            speech.error("数値として読み取れませんでした")
            return
        if not (spec.min_value <= value <= spec.max_value):
            speech.error(
                f"{spec.min_value} から {spec.max_value} までで入力してください")
            return
        self._apply({spec.key: value}, [(spec.label, f"{value}{spec.unit}")])

    def _choose_file(self, spec) -> None:
        path = self.frame.pick_file(spec.file_kind)
        # ネイティブのファイル選択はフォーカスを持たない状態で戻ることが
        # あるので、選んでも選ばなくても必ずリストへ戻す
        self.focus_list()
        if not path:
            speech.speak("ファイルを選びませんでした", interrupt=True)
            return
        patch = {spec.key: path}
        # メディアソースだけは「ローカルファイルを使う」印が要る。
        # 画像ソースにこれを送ると、誰も読まない設定キーになる
        if spec.key == "local_file":
            patch["is_local_file"] = True
        self._apply(patch, [(spec.label, props.file_stem(path))])

    def _enter_text(self, spec) -> None:
        """自由入力の項目（テキストの本文、ブラウザのアドレス）。"""
        current = str(self.settings.get(spec.key, "") or "")
        shown = current if current else "（空）"
        message = (f"{spec.label}を入力してください。\n"
                   f"今は {shown} です。")
        with self.frame.modal():
            dlg = wx.TextEntryDialog(
                self, message, spec.label, value=current)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                text = dlg.GetValue()
            finally:
                dlg.Destroy()
                self.focus_list()
        if text == current:
            speech.speak("変更はありません", interrupt=True)
            return
        self._apply({spec.key: text}, [(spec.label, text or "空")])

    def _choose_fixed(self, spec) -> None:
        """種別の表が持つ選択肢から選ぶ（OBSから引けない項目。色など）。"""
        values = [value for value, _label in spec.choices]
        rows = [label for _value, label in spec.choices]
        current = self.settings.get(spec.key)
        sel = values.index(current) if current in values else 0
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{spec.label}、{len(rows)}件", spec.label, rows)
            try:
                dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if 0 <= idx < len(values):
            self._apply({spec.key: values[idx]}, [(spec.label, rows[idx])])

    def _toggle_track(self, number: int) -> None:
        """録画のトラック1本を入り切りする（読み上げはフレーム側）。"""
        states = self.frame.apply_input_track(
            self.source_name, number,
            not self.input_tracks[number - 1])
        if states is not None:
            self.input_tracks = states
            self._refresh_list()

    def _choose_monitor(self) -> None:
        """音声モニタリング（自分の耳に返すか）を選ぶ。"""
        choices = props.MONITOR_CHOICES
        rows = [props.monitor_label(m) for m in choices]
        try:
            sel = choices.index(self.monitor_type)
        except ValueError:
            sel = 0
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{props.MONITOR_SPEC.label}、{len(rows)}件",
                props.MONITOR_SPEC.label, rows)
            try:
                dlg.SetSelection(sel)
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if not (0 <= idx < len(choices)):
            return
        chosen = choices[idx]
        if chosen == self.monitor_type:
            speech.speak("変更はありません", interrupt=True)
            return
        ok = self.frame.apply_monitor_change(self.source_name, chosen)
        if ok:
            self.monitor_type = chosen
            self._refresh_list()

    def _run_media_action(self, label: str, action: str) -> None:
        if not action:
            # 「再生・一時停止」は今の状態から送る操作を決める
            state, cur, dur = commands.fetch_media_status(
                self.frame.conn.req, self.source_name)
            self.media_state, self.media_cursor, self.media_duration = (
                state, cur, dur)
            action = props.media_action_for_state(state)
        try:
            commands.trigger_media_action(
                self.frame.conn.req, self.source_name, action)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"操作に失敗しました（{exc}）")
            return
        # 読み上げはメディアイベント側で行う（一方通行の原則）。
        # 行ラベル「再生・一時停止、今は〜」は古くなるので、OBS側の反映を
        # 少し待ってから実状態で書き直す。
        wx.CallLater(400, self._refresh_media_row)

    def _refresh_media_row(self) -> None:
        """メディアの再生状態を取り直して一覧の行を書き直す。"""
        if not self:
            return  # タイマー発火前にダイアログが閉じられた
        self.media_state, self.media_cursor, self.media_duration = (
            commands.fetch_media_status(self.frame.conn.req, self.source_name))
        self._refresh_list()

    # ------------------------------------------------------------
    # ボタン・キー
    # ------------------------------------------------------------
    def on_reload(self, _evt) -> None:
        speech.speak("設定を読み直します", interrupt=True)
        self._load_state()
        self._refresh_list()

    def on_open_obs(self, _evt) -> None:
        try:
            commands.open_properties_dialog(
                self.frame.conn.req, self.source_name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"OBSのプロパティ画面を開けませんでした（{exc}）")
            return
        speech.speak(
            "OBSのプロパティ画面を開きました。"
            "OBSの画面に切り替えて、閉じてください", interrupt=True)
        self.EndModal(wx.ID_CANCEL)

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        key = evt.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if wx.Window.FindFocus() is self.prop_list:
                self.activate_selected()
                return
        evt.Skip()


class FilterPropDialog(wx.Dialog):
    """フィルターの設定を一覧・変更するダイアログ。

    作りは SourcePropDialog と同じ（リスト1本＋ボタン）。値の編集は
    OS標準のダイアログへ委譲する。同じ操作感に揃えることを優先している。

    ★入力の設定と違い、フィルターには**設定変更のイベントが無い**
    （obs-websocket 5.7.3 に SourceFilterSettingsChanged は存在しない。
    実測で確認）。そのため読み上げはイベント駆動にできず、投げたあとに
    読み直して確かめる。投げた直後に読み直せば確定していることも実測済み。
    """

    def __init__(self, frame, source_name: str, filter_name: str) -> None:
        super().__init__(frame, title=f"{filter_name} の設定")
        self.frame = frame
        self.source_name = source_name
        self.filter_name = filter_name
        self.kind = ""
        self.settings: dict = {}
        self._rows: list = []
        self._load_state()
        self._build_ui()
        self.SetSize((520, 400))
        self.SetEscapeId(wx.ID_CANCEL)
        self.prop_list.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            wx.CallAfter(self.focus_list)
        evt.Skip()

    def focus_list(self) -> None:
        """設定項目リストへフォーカスを戻す（無言状態を作らないため）。"""
        try:
            self.prop_list.SetFocus()
        except Exception:  # noqa: BLE001
            pass

    def _load_state(self) -> None:
        self.kind, self.settings = commands.fetch_merged_filter_settings(
            self.frame.conn.req, self.source_name, self.filter_name)

    def _build_rows(self) -> list[str]:
        """一覧に出す行を作る。今の値で意味を持つ項目だけ出す。"""
        self._rows = []
        specs = filters.visible_specs(self.kind, self.settings)
        if not specs:
            self._rows.append(None)
            return [speech_format.filter_no_props_speech(
                self.filter_name, filters.is_known_kind(self.kind))]
        labels: list[str] = []
        for spec in specs:
            self._rows.append(spec)
            labels.append(speech_format.filter_prop_row(
                spec, self.settings.get(spec.key)))
        return labels

    def _refresh_list(self, keep_selection: bool = True) -> None:
        idx = self.prop_list.GetSelection() if keep_selection else wx.NOT_FOUND
        labels = self._build_rows()
        self.prop_list.Set(labels)
        if labels:
            self.prop_list.SetSelection(idx if 0 <= idx < len(labels) else 0)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("フィルター設定パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="設定項目（Enterで変更）")
        self.prop_list = wx.ListBox(panel, size=(-1, 240))
        self.prop_list.SetName("設定項目")
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.prop_list, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_reset = self._button(panel, "既定値に戻す", self.on_reset)
        self.btn_reload = self._button(panel, "読み直す", self.on_reload)
        self.btn_close = wx.Button(panel, wx.ID_CANCEL, "閉じる")
        self.btn_close.SetName("閉じる")
        for btn in (self.btn_reset, self.btn_reload, self.btn_close):
            row.Add(btn, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)

        panel.SetSizer(root)
        self._refresh_list(keep_selection=False)

    def _button(self, parent, label: str, handler) -> wx.Button:
        btn = wx.Button(parent, label=label)
        btn.SetName(label)
        btn.Bind(wx.EVT_BUTTON, handler)
        return btn

    def activate_selected(self) -> None:
        idx = self.prop_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._rows):
            return
        spec = self._rows[idx]
        if spec is None:
            return  # 設定項目が無い旨の行
        if spec.type in ("float", "int"):
            self._enter_number(spec)
        elif spec.type == "choice":
            self._choose(spec)
        elif spec.type == "source":
            self._choose_source(spec)
        elif spec.type == "bool":
            self._toggle(spec)

    def _apply(self, spec, value) -> None:
        """設定を1つ変え、読み直して結果を読み上げる。

        ★イベントが無いので、変わったかどうかはここで確かめるしかない。
        投げっぱなしにすると「変えたつもりで変わっていない」に気づけない。
        """
        ok = self.frame.apply_filter_change(
            self.source_name, self.filter_name, {spec.key: value}, spec)
        if ok:
            self._load_state()
            self._refresh_list()

    def _enter_number(self, spec) -> None:
        current = self.settings.get(spec.key, spec.min_value)
        message = (
            f"{spec.label}を数値で入力してください。\n"
            f"今は {speech_format.fmt_filter_value(spec, current)} です。\n"
            f"入力できる範囲は {_fmt_limit(spec.min_value)} から "
            f"{_fmt_limit(spec.max_value)} までです。")
        with self.frame.modal():
            dlg = wx.TextEntryDialog(
                self, message, spec.label, value=_fmt_limit(current))
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                text = dlg.GetValue()
            finally:
                dlg.Destroy()
                self.focus_list()
        # 音量の数値入力と同じ解釈を使う（全角・単位付きも通す）
        parsed = volume.parse_db_input(text)
        if parsed is None:
            speech.error(
                "数値として読み取れませんでした。5 や マイナス10 のように"
                "入力してください")
            return
        # 範囲外は拒否せず端へ丸める（打ち間違いで弾かれるより親切。
        # 音量の parse_db_input と同じ方針）
        self._apply(spec, filters.clamp(spec, parsed))

    def _choose(self, spec) -> None:
        rows = [label for _value, label in spec.choices]
        values = [value for value, _label in spec.choices]
        current = self.settings.get(spec.key)
        sel = values.index(current) if current in values else 0
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{spec.label}、{len(rows)}件", spec.label, rows)
            try:
                dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if 0 <= idx < len(values):
            self._apply(spec, values[idx])

    def _choose_source(self, spec) -> None:
        """サイドチェーンの元になる音声入力を選ぶ。"""
        names = [i.name for i in self.frame.snapshot.audio_inputs
                 if i.name != self.source_name]
        rows = ["なし"] + names
        values = [filters.SIDECHAIN_NONE] + names
        current = str(self.settings.get(spec.key, "") or
                      filters.SIDECHAIN_NONE)
        sel = values.index(current) if current in values else 0
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{spec.label}、{len(rows)}件", spec.label, rows)
            try:
                dlg.SetSelection(sel)
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if 0 <= idx < len(values):
            self._apply(spec, values[idx])

    def _toggle(self, spec) -> None:
        self._apply(spec, not bool(self.settings.get(spec.key)))

    def on_reset(self, _evt) -> None:
        """このフィルターの設定を既定値へ戻す。

        いじりすぎて分からなくなったときの逃げ道。消して作り直すのと
        同じことだが、名前と並び順が変わらないので安全。
        """
        defaults = commands.fetch_filter_default_settings(
            self.frame.conn.req, self.kind)
        if not defaults:
            speech.warn("このフィルターに既定値はありません")
            return
        if not self.frame._confirm(
            f"{self.filter_name} の設定を既定値に戻しますか？"
        ):
            return
        ok = self.frame.apply_filter_change(
            self.source_name, self.filter_name, dict(defaults), None)
        if ok:
            self._load_state()
            self._refresh_list()
            speech.speak(f"{self.filter_name} を既定値に戻しました",
                         interrupt=True)

    def on_reload(self, _evt) -> None:
        speech.speak("設定を読み直します", interrupt=True)
        self._load_state()
        self._refresh_list()

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        key = evt.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if wx.Window.FindFocus() is self.prop_list:
                self.activate_selected()
                return
        evt.Skip()


class ScenePropDialog(wx.Dialog):
    """シーンの設定ダイアログ（名前・切り替え効果・ソースの追加）。

    作りは SourcePropDialog と同じ（リスト1本＋ボタン）。操作感を
    揃えることを優先している。

    ★入力の設定と違い、シーンの設定にも変更イベントは無い
    （SceneNameChanged は飛ぶが、トランジションの上書きには無い）。
    投げたあとに読み直して確かめる。
    """

    def __init__(self, frame, scene_name: str) -> None:
        super().__init__(frame, title=f"{scene_name} の設定")
        self.frame = frame
        self.scene_name = scene_name
        self.transitions: list = []
        self.current = scenes.SceneTransition()
        self._rows: list = []
        self._load_state()
        self._build_ui()
        self.SetSize((520, 360))
        self.SetEscapeId(wx.ID_CANCEL)
        self.prop_list.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            wx.CallAfter(self.focus_list)
        evt.Skip()

    def focus_list(self) -> None:
        """設定項目リストへフォーカスを戻す（無言状態を作らないため）。"""
        try:
            self.prop_list.SetFocus()
        except Exception:  # noqa: BLE001
            pass

    def _load_state(self) -> None:
        client = self.frame.conn.req
        self.transitions = commands.fetch_transitions(client)
        self.current = commands.fetch_scene_transition(client, self.scene_name)

    def _build_rows(self) -> list[str]:
        """一覧に出す行を作る。今の設定で意味を持つ行だけ出す。"""
        self._rows = []
        labels: list[str] = []

        self._rows.append(("name",))
        labels.append(speech_format.prop_row_label("名前", self.scene_name))

        self._rows.append(("transition",))
        labels.append(speech_format.scene_transition_row(self.current))

        # ★長さは「上書きしていて、かつ長さを変えられる効果」のときだけ。
        #   カットのように長さが効かない効果で行を出すと、変えても何も
        #   起きない項目を触らせることになる
        if scenes.shows_duration(self.transitions, self.current):
            self._rows.append(("duration",))
            labels.append(speech_format.scene_duration_row(self.current))

        self._rows.append(("add_source",))
        labels.append("このシーンにソースを追加する")
        return labels

    def _refresh_list(self, keep_selection: bool = True) -> None:
        idx = self.prop_list.GetSelection() if keep_selection else wx.NOT_FOUND
        labels = self._build_rows()
        self.prop_list.Set(labels)
        if labels:
            self.prop_list.SetSelection(idx if 0 <= idx < len(labels) else 0)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("シーン設定パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="設定項目（Enterで変更）")
        self.prop_list = wx.ListBox(panel, size=(-1, 200))
        self.prop_list.SetName("設定項目")
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.prop_list, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_reload = self._button(panel, "読み直す", self.on_reload)
        self.btn_close = wx.Button(panel, wx.ID_CANCEL, "閉じる")
        self.btn_close.SetName("閉じる")
        for btn in (self.btn_reload, self.btn_close):
            row.Add(btn, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)

        panel.SetSizer(root)
        self._refresh_list(keep_selection=False)

    def _button(self, parent, label: str, handler) -> wx.Button:
        btn = wx.Button(parent, label=label)
        btn.SetName(label)
        btn.Bind(wx.EVT_BUTTON, handler)
        return btn

    def activate_selected(self) -> None:
        idx = self.prop_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._rows):
            return
        kind = self._rows[idx][0]
        if kind == "name":
            self._rename()
        elif kind == "transition":
            self._choose_transition()
        elif kind == "duration":
            self._enter_duration()
        elif kind == "add_source":
            self._add_source()

    def _rename(self) -> None:
        with self.frame.modal():
            dlg = wx.TextEntryDialog(
                self, "シーンの名前を入力してください。", "名前の変更",
                value=self.scene_name)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                typed = dlg.GetValue()
            finally:
                dlg.Destroy()
                self.focus_list()
        new_name = scenes.valid_scene_name(typed)
        if not new_name or new_name == self.scene_name:
            speech.speak("変更はありません", interrupt=True)
            return
        existing = commands.fetch_scene_names(self.frame.conn.req)
        if new_name in existing:
            speech.warn(f"{new_name} という名前のシーンが既にあります")
            return
        old = self.scene_name
        try:
            commands.rename_scene(self.frame.conn.req, old, new_name)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"名前を変えられませんでした（{exc}）")
            return
        self.scene_name = new_name
        self.SetTitle(f"{new_name} の設定")
        self._refresh_list()
        speech.speak(
            speech_format.scene_renamed_speech(old, new_name), interrupt=True)

    def _choose_transition(self) -> None:
        rows = ["全体の設定に従う"] + [t.name for t in self.transitions]
        values = [scenes.USE_GLOBAL] + [t.name for t in self.transitions]
        sel = (values.index(self.current.name)
               if self.current.name in values else 0)
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"切り替え効果、{len(rows)}件", "切り替え効果", rows)
            try:
                dlg.SetSelection(sel)
                # ★キャンセルでも GetSelection は値を返すので必ず判定する
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if not (0 <= idx < len(values)):
            return
        name = values[idx]
        # 効果を選び直したら、長さは今の値を引き継ぐ（未設定なら既定）
        duration = self.current.duration_ms
        if name and not isinstance(duration, int):
            duration = scenes.DEFAULT_DURATION_MS
        if name and scenes.is_fixed(self.transitions, name):
            duration = None  # 長さが効かない効果には送らない
        self._apply_transition(name, duration)

    def _enter_duration(self) -> None:
        current = self.current.duration_ms or scenes.DEFAULT_DURATION_MS
        message = (f"切り替えの長さをミリ秒で入力してください。\n"
                   f"今は {int(current)}ミリ秒 です。\n"
                   f"{scenes.DURATION_MIN_MS} から "
                   f"{scenes.DURATION_MAX_MS} まで。")
        with self.frame.modal():
            dlg = wx.TextEntryDialog(
                self, message, "切り替えの長さ", value=str(int(current)))
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                text = dlg.GetValue()
            finally:
                dlg.Destroy()
                self.focus_list()
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            speech.error("数値として読み取れませんでした")
            return
        # 範囲外は拒否せず端へ丸める（音量の数値入力と同じ方針）
        self._apply_transition(
            self.current.name, scenes.clamp_duration(value))

    def _apply_transition(self, name: str, duration) -> None:
        """トランジションの上書きを投げ、読み直して確かめる。"""
        try:
            commands.apply_scene_transition(
                self.frame.conn.req, self.scene_name, name, duration)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"切り替え効果を変えられませんでした（{exc}）")
            return
        # イベントが無いので読み直して確かめる
        self.current = commands.fetch_scene_transition(
            self.frame.conn.req, self.scene_name)
        self._refresh_list()
        if self.current.name != (name or scenes.USE_GLOBAL):
            speech.warn(
                f"{self.scene_name} の切り替え効果は変わりませんでした。"
                "OBSが受け付けていません")
            return
        speech.speak(
            speech_format.scene_transition_changed_speech(
                self.scene_name, self.current),
            interrupt=True)

    def _add_source(self) -> None:
        """既にあるソースを、このシーンにも置く。"""
        client = self.frame.conn.req
        placed = [i.name for i in commands.fetch_scene_items(
            client, self.scene_name)]
        # ★グローバル音声デバイス（設定→音声のマイクなど）は候補から外す。
        #   全シーンで常に有効なので足す必要が無く、足すと一覧に二重に
        #   現れて混乱するだけ（実測で「マイク」がこれに当たる）
        names = scenes.addable_sources(
            commands.fetch_input_names(client), placed,
            commands.fetch_special_input_names(client))
        if not names:
            speech.warn(
                speech_format.scene_no_addable_speech(self.scene_name))
            return
        with self.frame.modal():
            dlg = wx.SingleChoiceDialog(
                self, f"{self.scene_name} に追加するソース、{len(names)}件",
                "ソースを追加", names)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
                self.focus_list()
        if not (0 <= idx < len(names)):
            return
        source = names[idx]
        try:
            commands.add_source_to_scene(client, self.scene_name, source)
        except Exception as exc:  # noqa: BLE001
            speech.error(f"ソースを追加できませんでした（{exc}）")
            return
        speech.speak(
            speech_format.scene_source_added_speech(self.scene_name, source),
            interrupt=True)

    def on_reload(self, _evt) -> None:
        speech.speak("設定を読み直します", interrupt=True)
        self._load_state()
        self._refresh_list()

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        key = evt.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if wx.Window.FindFocus() is self.prop_list:
                self.activate_selected()
                return
        evt.Skip()


class KeyHelpDialog(wx.Dialog):
    """キー操作の一覧を出すダイアログ。

    ★読み上げで辿れることを最優先にした作り。
    - 本文は読み取り専用の複数行テキストに入れる。リストにすると1行が
      1項目になって「行の途中を読み返す」ができないが、テキストなら
      スクリーンリーダーの文字・単語単位の読み返しがそのまま使える
    - 開いたらテキストへフォーカスを置く。置かないとボタンに載って
      「空のダイアログ」に聞こえる（他の設定ダイアログと同じ理由）
    - 読み上げは1行ずつ辿ってもらう。全文を speak すると長すぎて
      途中で見失う（「長い出力を一度に出さない」の方針）
    """

    def __init__(self, frame, text: str) -> None:
        super().__init__(frame, title="キー操作の一覧")
        self.frame = frame
        panel = wx.Panel(self)
        panel.SetName("キー一覧パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(
            panel, label="キー操作の一覧（上下キーで1行ずつ読めます）")
        self.text = wx.TextCtrl(
            panel, value=text,
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_DONTWRAP)
        self.text.SetName("キー操作の一覧")
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.text, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_close = wx.Button(panel, wx.ID_CANCEL, "閉じる")
        self.btn_close.SetName("閉じる")
        row.Add(self.btn_close, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)

        panel.SetSizer(root)
        self.SetSize((620, 520))
        self.SetEscapeId(wx.ID_CANCEL)
        self.text.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            # 表示される前の SetFocus は載らないことがあるので置き直す
            wx.CallAfter(self._focus_text)
        evt.Skip()

    def _focus_text(self) -> None:
        try:
            self.text.SetFocus()
            self.text.SetInsertionPoint(0)
        except Exception:  # noqa: BLE001
            pass

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        # ★F1 でこの画面を開いたあと、もう一度 F1 を押しても
        #   入れ子で開かないようにする（閉じる動きにする）
        if evt.GetKeyCode() == wx.WXK_F1 and evt.GetModifiers() == wx.MOD_NONE:
            self.EndModal(wx.ID_CANCEL)
            return
        evt.Skip()


class OrderDialog(wx.Dialog):
    """一覧の並び順を並べ替えるダイアログ（3か所で使い回す）。

    レベル読み上げ(F6)の順番、シーン一覧の順番、ソース一覧の順番。
    どれも「名前の並びを決める」だけなので、同じ画面・同じ操作にしてある
    （場面ごとに操作が違うと、目で見比べられない分だけ覚え直しが要る）。

    ★並べ替えはキー（Altと上下）とボタンの両方でできるようにしてある。
      ドラッグでしか並べ替えられない作りはマウスが要る＝操作不能になる。
    ★作りは他の設定ダイアログと同じ「リスト1本＋ボタン」に揃えた。

    ★保存済みの順番に載っているが今はOBSに無い名前も、消さずに
      「（今はありません）」を付けて出す。黙って捨てると、シーンコレクション
      を切り替えて戻ってきたときに順番だけが失われる。要らなくなった
      ものは「一覧から外す」で消せる。
    ★開いてそのまま保存しても順番が変わらないようにしてある
      （保存済みの並びを先に、そこに無い入力だけを名前順で後ろへ足す）。
    """

    MISSING_MARK = "（今はありません）"

    def __init__(self, frame, title, names, saved_order,
                 by_name: bool = False, what: str = "並べる順番",
                 present=None) -> None:
        super().__init__(frame, title=title)
        self.frame = frame
        self.what = what
        # by_name=True: 設定に無いものは名前順で後ろへ（レベル読み上げ）
        # by_name=False: OBSから来た順のまま後ろへ（シーン・ソース一覧）
        self.by_name = bool(by_name)
        self.natural: list[str] = [n for n in names if n]
        # ★「今あるもの」は natural より広いことがある。ソース一覧の
        #   並び順は全シーンで1つの設定なのに、natural は今開いている
        #   シーンのソースだけなので、他のシーンのソースまで
        #   「今はありません」と読まれ、「戻す」で設定ごと消えていた
        #   （0.17.3 の退行。レビューで判明）。呼ぶ側が広い集合を
        #   渡せるようにしてある。
        self.present = (set(present) if present is not None
                        else set(self.natural))
        self.rows: list[str] = ordering.order_for_edit(
            self.natural, saved_order, sort_rest=self.by_name)
        # 保存の判断に使う。開いたときの並びと、開いたときの設定。
        # ★「開いて確かめただけ」を書き換えにしない（下の result_order）
        self._saved: list[str] = [n for n in (saved_order or ()) if n]
        self._opened: list[str] = list(self.rows)
        self._reset_used = False
        self._build_ui()
        self.SetSize((520, 360))
        self.SetEscapeId(wx.ID_CANCEL)
        self.order_list.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    # --- 組み立て ---
    @property
    def reset_label(self) -> str:
        """並べ直しボタンの文言（戻す先を名前で言う）。"""
        return "名前順に並べ直す" if self.by_name else "OBSと同じ順に戻す"

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("並び順パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(
            panel,
            label=f"{self.what}（Altと上下キーで入れ替え、"
                  "Deleteで一覧から外す）")
        self.order_list = wx.ListBox(panel, size=(-1, 200))
        self.order_list.SetName(self.what)
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.order_list, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_up = self._button(panel, "上へ移動", self.on_up)
        self.btn_down = self._button(panel, "下へ移動", self.on_down)
        self.btn_sort = self._button(panel, self.reset_label, self.on_sort)
        self.btn_drop = self._button(panel, "一覧から外す", self.on_drop)
        # ★OK・キャンセルは EndModal を直接呼ぶ
        #   （ストックIDの既定処理任せにすると、閉じ方が環境依存になる）
        self.btn_ok = wx.Button(panel, wx.ID_OK, "保存")
        self.btn_ok.SetName("保存")
        self.btn_ok.SetDefault()
        self.btn_ok.Bind(wx.EVT_BUTTON,
                         lambda _evt: self.EndModal(wx.ID_OK))
        self.btn_cancel = wx.Button(panel, wx.ID_CANCEL, "キャンセル")
        self.btn_cancel.SetName("キャンセル")
        self.btn_cancel.Bind(wx.EVT_BUTTON,
                             lambda _evt: self.EndModal(wx.ID_CANCEL))
        for btn in (self.btn_up, self.btn_down, self.btn_sort,
                    self.btn_drop, self.btn_ok, self.btn_cancel):
            row.Add(btn, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)

        panel.SetSizer(root)
        self._refresh(0)

    def _button(self, parent, label: str, handler) -> wx.Button:
        btn = wx.Button(parent, label=label)
        btn.SetName(label)
        btn.Bind(wx.EVT_BUTTON, handler)
        return btn

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            wx.CallAfter(self.focus_list)
        evt.Skip()

    def focus_list(self) -> None:
        """並び順リストへフォーカスを戻す（無言状態を作らないため）。"""
        try:
            self.order_list.SetFocus()
        except Exception:  # noqa: BLE001
            pass

    # --- 表示 ---
    def _row_label(self, idx: int) -> str:
        """1行の文言。★何番目かを後ろに付ける。

        並べ替えの画面では「今どこにいるか」が要る。名前を先に置くのは、
        リストの頭文字ジャンプを数字で潰さないため。
        """
        name = self.rows[idx]
        mark = "" if name in self.present else self.MISSING_MARK
        return f"{name}{mark} {idx + 1}番目"

    def _refresh(self, select: int) -> None:
        labels = [self._row_label(i) for i in range(len(self.rows))]
        self.order_list.Set(labels)
        if labels:
            self.order_list.SetSelection(
                select if 0 <= select < len(labels) else 0)

    # --- 操作 ---
    def _move(self, delta: int) -> None:
        idx = self.order_list.GetSelection()
        if idx == wx.NOT_FOUND:
            speech.warn("動かすものを選んでください")
            return
        new = ordering.move(self.rows, idx, delta)
        if new < 0:
            speech.speak(
                "これ以上、上へは動かせません" if delta < 0
                else "これ以上、下へは動かせません", interrupt=True)
            return
        # ★読み上げはリストを作り直す前に呼ぶ
        #   （あとにすると、選択が動いたことによる
        #   スクリーンリーダー自身の読み上げに上書きされる）
        speech.speak(self._row_label(new), interrupt=True)
        self._refresh(new)

    def _drop(self) -> None:
        """今は無いもの（設定に残った古い名前）を一覧から外す。"""
        idx = self.order_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self.rows[idx]
        if name in self.present:
            # 外しても今あるソースは名前順の後ろへ回るだけで消えない。
            # 「外れた」と誤解させないよう断る
            speech.warn(f"{name} は今あるものなので外せません。"
                        "順番だけ変えられます")
            return
        del self.rows[idx]
        speech.speak(f"{name} を一覧から外しました", interrupt=True)
        self._refresh(min(idx, len(self.rows) - 1))

    def _reset_order(self) -> None:
        """既定の並びへ戻す（今は無い名前はここで落ちる）。

        ★戻す先は core/ordering.py の default_rows が決める。設定を空に
        したときに実際に使われる並びと、ここで見せる並びを同じものに
        しておかないと、「戻したのに順番が変わらない」ことになる。
        ★self.rows から作り直してはいけない。渡された natural から作る
        （0.17.2 までは self.rows を絞っていたので、ソース一覧の場合は
        既に並べ替え済みの並びが「OBSと同じ順」として戻ってきていた）。
        ★今あるのに natural に無いもの（他のシーンに置かれているソース）は
        後ろへ残す。落とすと、そのシーンの並びが黙って消える。
        """
        dropped = [n for n in self.rows if n not in self.present]
        base = ordering.default_rows(self.natural, self.by_name)
        kept = [n for n in self.rows
                if n in self.present and n not in base]
        self.rows = base + kept
        self._reset_used = True
        speech.speak(
            speech_format.order_reset_speech(self.by_name, len(dropped)),
            interrupt=True)
        self._refresh(0)

    def result_order(self) -> list[str]:
        """保存する並び（ShowModal が ID_OK のときに読む）。

        ★何も動かしていなければ、開いたときの設定をそのまま返す。
        確かめるために開いて保存を押しただけで設定が変わってはいけない
        （0.17.3 は既定と同じ形なら常に空を返していたので、ソース一覧の
        場合に**別のシーン向けに設定した並びが丸ごと消えていた**。
        並び順は全シーンで1つなのに、既定かどうかは今開いているシーンの
        並びで判断していたため。レビューで判明）。

        ★「戻す」を押したときだけ、既定と同じなら**空**を返す。空は
        「OBS（または名前）の並びに従う」という意味なので、あとから
        シーンやソースが増えても自然な位置に入る。今の並びを書き込むと
        「戻した」つもりが今の順番の固定になる（0.17.2 までの不具合）。
        """
        if not self._reset_used and self.rows == self._opened:
            return list(self._saved)
        if ordering.is_default(self.rows, self.natural, self.by_name):
            return []
        return list(self.rows)

    # --- ハンドラ ---
    def on_up(self, _evt) -> None:
        self._move(-1)
        self.focus_list()

    def on_down(self, _evt) -> None:
        self._move(1)
        self.focus_list()

    def on_sort(self, _evt) -> None:
        self._reset_order()
        self.focus_list()

    def on_drop(self, _evt) -> None:
        self._drop()
        self.focus_list()

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        key = evt.GetKeyCode()
        on_list = wx.Window.FindFocus() is self.order_list
        if evt.GetModifiers() == wx.MOD_ALT and key == wx.WXK_UP:
            self._move(-1)
            # ★OSにもキーを渡す。握り潰すと WM_SYSKEYDOWN が
            #   DefWindowProc に届かず、Windows は「Alt を単独で押して
            #   離した」と解釈する。この窓にメニューバーは無いので
            #   システムメニューの追跡に入り、読み上げが「システム」に
            #   なって矢印が効かなくなる（実測の Win32 挙動）
            evt.DoAllowNextEvent()
            return
        if evt.GetModifiers() == wx.MOD_ALT and key == wx.WXK_DOWN:
            self._move(1)
            evt.DoAllowNextEvent()
            return
        if key == wx.WXK_DELETE and on_list:
            self._drop()
            return
        evt.Skip()


class RecordTracksDialog(wx.Dialog):
    """録画するトラック（トラック1〜6）を選ぶダイアログ。

    OBS 本体の「設定→出力→録画→音声トラック」に当たる。作りは他の設定
    ダイアログと同じ「リスト1本＋ボタン」で、1行1トラックを Enter で
    入り切りする。
    ★次の録画から効く設定なので、録画中は変えさせない（フレーム側の
    apply_record_track が断る）。
    """

    def __init__(self, frame) -> None:
        super().__init__(frame, title="録画のトラック設定")
        self.frame = frame
        self.info: dict = {}
        self._load_state()
        self._build_ui()
        self.SetSize((520, 360))
        self.SetEscapeId(wx.ID_CANCEL)
        self.prop_list.SetFocus()
        self.Bind(wx.EVT_SHOW, self._on_show)

    def _on_show(self, evt) -> None:
        if evt.IsShown():
            wx.CallAfter(self.focus_list)
        evt.Skip()

    def focus_list(self) -> None:
        try:
            self.prop_list.SetFocus()
        except Exception:  # noqa: BLE001
            pass

    def _load_state(self) -> None:
        self.info = commands.fetch_record_tracks(self.frame.conn.req)

    def _states(self):
        states = self.info.get("tracks")
        return states if states is not None else (False,) * tracks.TRACK_COUNT

    def _build_rows(self) -> list[str]:
        states = self._states()
        labels = [speech_format.record_track_row(n, states[n - 1])
                  for n in tracks.TRACK_NUMBERS]
        labels.append("割り当てをまとめて読む")
        labels.append("おすすめの割り当てを聞く")
        return labels

    def _refresh_list(self, keep_selection: bool = True) -> None:
        idx = self.prop_list.GetSelection() if keep_selection else wx.NOT_FOUND
        labels = self._build_rows()
        self.prop_list.Set(labels)
        self.prop_list.SetSelection(idx if 0 <= idx < len(labels) else 0)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("録画のトラック設定パネル")
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        root = wx.BoxSizer(wx.VERTICAL)
        lbl = wx.StaticText(
            panel, label="録画するトラック（Enterで入り切り。次の録画から効く）")
        self.prop_list = wx.ListBox(panel, size=(-1, 200))
        self.prop_list.SetName("録画するトラック")
        root.Add(lbl, 0, wx.LEFT | wx.TOP, 8)
        root.Add(self.prop_list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_reload = wx.Button(panel, label="読み直す")
        self.btn_reload.SetName("読み直す")
        self.btn_reload.Bind(wx.EVT_BUTTON, self.on_reload)
        self.btn_close = wx.Button(panel, wx.ID_CANCEL, "閉じる")
        self.btn_close.SetName("閉じる")
        for btn in (self.btn_reload, self.btn_close):
            row.Add(btn, 0, wx.ALL, 4)
        root.Add(row, 0, wx.LEFT, 4)
        panel.SetSizer(root)
        self._refresh_list(keep_selection=False)

    def activate_selected(self) -> None:
        idx = self.prop_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        if idx < tracks.TRACK_COUNT:
            number = idx + 1
            states = self.frame.apply_record_track(
                self.info, number, not self._states()[idx])
            if states is not None:
                self.info = dict(self.info, tracks=states)
                self._refresh_list()
        elif idx == tracks.TRACK_COUNT:
            self.frame.announce_tracks_overview()
        else:
            speech.speak(speech_format.tracks_recommendation_speech(),
                         interrupt=True)

    def on_reload(self, _evt) -> None:
        speech.speak("設定を読み直します", interrupt=True)
        self._load_state()
        self._refresh_list()

    def on_char_hook(self, evt: wx.KeyEvent) -> None:
        key = evt.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if wx.Window.FindFocus() is self.prop_list:
                self.activate_selected()
                return
        evt.Skip()


def _fmt_limit(value) -> str:
    """範囲や初期値を入力欄に出すときの文字列（整数なら整数で）。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num == int(num) else str(round(num, 2))


def pick_audio_file(parent, last_dir: str = "", file_kind: str = "audio") -> str:
    """ファイルを選ぶ（呼び出し側でモーダル管理をすること）。

    ネイティブのファイル選択ダイアログは表示までに数秒かかることがあり、
    その間は無音になる。案内は必ず ShowModal の前に読むこと
    （モーダル中は wx.CallLater が動かない）。
    """
    title, wildcard = FILE_KINDS.get(file_kind, FILE_KINDS["audio"])
    dlg = wx.FileDialog(
        parent, title,
        defaultDir=last_dir or "",
        wildcard=wildcard,
        # ★FD_CHANGE_DIR は付けない（プロセスの作業フォルダが変わる）
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return ""
        path = dlg.GetPath()
    finally:
        dlg.Destroy()
    if not path or not os.path.isfile(path):
        return ""
    return path
