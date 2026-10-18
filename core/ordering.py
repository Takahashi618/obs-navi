# -*- coding: utf-8 -*-
"""一覧の並び順を決める純ロジック（wx・obsws非依存）。

3か所で同じ考え方を使うのでここにまとめてある。

    レベル読み上げ(F6)   config.level_read["order"]
    シーン一覧           config.list_order["scenes"]
    ソース一覧           config.list_order["items"]

★共通の約束: **設定に載っていないものを落とさない。**
あとから足したシーンやソースが黙って一覧から消えると、
「無くなったのか、並びの都合で下にいるのか」が耳では区別できない。
設定が決めるのは「どれを先に出すか」だけで、「出すかどうか」は決めない。

★「残り」をどう並べるかは呼ぶ側が決める。
レベル読み上げは名前順（もともと名前順だった）、シーンとソースは
OBS から来た順のまま（ソース一覧の順は重なり順という意味を持つため、
設定していない間はその意味を壊さない）。
"""
from __future__ import annotations


def apply_order_by(items, order=None, key=None, sort_rest=False) -> list:
    """items を order の並びへ寄せる。

    order に載っている名前をその順で先に、残りを後ろへ。
    ★同じ名前が複数あっても落とさない（OBSは同じソースを1つのシーンへ
    2回置ける。名前で消し込むと片方が消えてしまう）。

    key は items の要素から名前を取り出す関数。省略すると要素そのもの。
    sort_rest=True なら「残り」を名前順にする（既定は元の並びのまま）。
    """
    get = key or (lambda x: x)
    rest = list(items or [])
    out: list = []
    for name in order or ():
        matched = [x for x in rest if get(x) == name]
        if not matched:
            continue
        out.extend(matched)
        rest = [x for x in rest if get(x) != name]
    if sort_rest:
        rest = sorted(rest, key=get)
    return out + rest


def apply_order(names, order=None, sort_rest=False) -> list:
    """名前のリストを order の並びへ寄せる（apply_order_by の名前版）。"""
    return apply_order_by(names, order, None, sort_rest)


def order_for_edit(names, saved_order=None, sort_rest=False) -> list:
    """並べ替え画面の初期表示を作る。

    保存済みの並びをそのまま先に置く。★今は無い名前もその位置に残す
    （シーンコレクションを切り替えて戻ったときに順番だけ失われるのを
    防ぐ）。そのあとに、保存に無いものを続ける。

    ★開いてそのまま保存しても並びが変わらないこと。これを守らないと、
    確かめるために開いただけで設定が書き換わる。
    """
    saved = [n for n in (saved_order or ()) if n]
    seen = set()
    rows: list = []
    for name in saved:
        if name not in seen:
            seen.add(name)
            rows.append(name)
    rest = [n for n in (names or []) if n and n not in seen]
    if sort_rest:
        rest = sorted(rest)
    for name in rest:
        if name not in seen:
            seen.add(name)
            rows.append(name)
    return rows


def default_rows(names, sort_rest: bool = False) -> list:
    """設定が空のときに使われる並び（＝「既定の並び」）。

    並べ替え画面の「戻す」ボタンが戻す先であり、保存を空にしたときに
    実際に使われる並びでもある。★同じ名前は1つにまとめる
    （OBSは同じソースを1シーンに2回置けるので、名前の並びとしては
    1つで足りる。まとめないと戻すたびに行が増える）。

    ★中身は order_for_edit(names, ()) と同じでなければならない。
    「戻す」先と、設定が空のときの初期表示がずれると、戻したのに
    順番が変わらない（あるいはその逆）が起きる。同じ処理を2回
    書かずに委譲して、ずれようが無いようにしてある。
    """
    return order_for_edit(names, (), sort_rest)


def is_default(rows, names, sort_rest: bool = False) -> bool:
    """今の並びが「既定の並び」と同じか。

    同じなら設定は空で保存してよい（＝以後もOBSや名前順に追従する）。
    明示的に並びを書き込んでしまうと、あとからシーンやソースが増えても
    常に末尾へ回り続け、「戻したはずなのに追従しない」状態になる。
    """
    return list(rows) == default_rows(names, sort_rest)


def default_label(sort_rest: bool = False) -> str:
    """既定の並びの呼び名（設定を空にしたときに戻る並び）。

    ★呼び名は1か所に置く。保存の読み上げ・「戻す」ボタンの文言・
    戻したときの読み上げの3か所で別々に書いていたので、片方だけ
    言い換えると同じ並びが場面ごとに違う名前で読まれてしまう。
    """
    return "名前順" if sort_rest else "OBSと同じ順"


def move(rows, index: int, delta: int) -> int:
    """rows の index の要素を delta だけ動かす。動かせなければ -1。

    動かせたときは移動後の位置を返す（読み上げに使う）。
    rows はその場で書き換える。
    """
    if not (0 <= index < len(rows)):
        return -1
    dest = index + delta
    if not (0 <= dest < len(rows)):
        return -1
    rows[index], rows[dest] = rows[dest], rows[index]
    return dest
