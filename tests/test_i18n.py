# -*- coding: utf-8 -*-
"""表示の言語（日本語と英語）のテスト。

1. 言語の決め方（環境変数・設定・PC の表示言語）と設定の正規化
2. ソースを読んで調べる静的な検査:
   - 利用者に見せる日本語の文字列は、すべて tr("日本語", "English") の
     日本語側にあること（英語のときに日本語が残らない）
   - tr の英語側に日本語の文字が無いこと
   わざと残してある日本語（入力の解釈に使う全角文字など）は
   ALLOWED に理由つきで並べる

英語の画面を実際に作って調べるのは tests/en_probe.py（wx を使うので
run_tests.py には入れていない。別のプロセスで英語にして走らせる）。
"""
from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import i18n  # noqa: E402
from core.config import Config  # noqa: E402

_results: list[tuple[str, bool, str]] = []

# かな・漢字・全角の記号と英数字
JP = re.compile(r"[　-ヿ一-鿿！-｠]")

# 調べるファイル（利用者に見せる文がある所）
SOURCES = ["app.py", "speech.py"] + [
    os.path.join(d, f) for d in ("core", "ui")
    for f in sorted(os.listdir(os.path.join(ROOT, d))) if f.endswith(".py")]

# わざと tr を通さない日本語。(ファイル, 文字列) と理由
ALLOWED = {
    # 音量の入力を解釈する（全角の数字・記号・単位を受け付ける）
    ("core/volume.py", "０１２３４５６７８９＋－．"),
    ("core/volume.py", "デシベル"),
    ("core/volume.py", "ー"),
    # 読み上げで記号名を読ませないための文字の一覧
    ("core/speech_format.py", "\\/|<>*?\"[]{}【】《》＜＞«»"),
    # _count に渡す日本語の単位（英語の単位と並べて渡している）
    ("core/speech_format.py", "時間"),
    ("core/speech_format.py", "分"),
    ("core/speech_format.py", "秒"),
    # 「表示の言語」は日本語と英語を併記する（読めない言語になっても
    # この項目だけは見つけられるように）。ui/main_frame.py の on_language
    ("ui/main_frame.py", "表示の言語 (Language)"),
    ("ui/main_frame.py", "日本語"),
    ("ui/main_frame.py", "日本語 (Japanese)"),
    ("ui/main_frame.py", "English (英語)"),
    ("ui/main_frame.py", "表示と読み上げの言語 (Display language)"),
    ("ui/main_frame.py", "保存しました。日本語にするため、今すぐ OBSナビを"
                         "再起動しますか？"),
    ("ui/main_frame.py", "次に OBSナビを起動したときから日本語になります"),
}
# f 文字列で、固定の部分にだけ日本語があるもの（ファイル, 固定の部分）
ALLOWED_FSTRING_PARTS = {
    ("ui/main_frame.py", "自動 PC の言語に合わせる (Automatic, "),
}


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


def _is_tr(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "tr")


def _texts(node) -> list[str]:
    """文字列の式に含まれる固定の部分（f 文字列は差し込み以外の部分）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def scan(rel: str):
    """(tr を通していない日本語, 英語側に日本語がある tr) を返す。"""
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    tree = ast.parse(src)
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    bare: list[str] = []
    bad_en: list[str] = []
    for node in ast.walk(tree):
        if _is_tr(node):
            if len(node.args) != 2:
                bad_en.append(f"L{node.lineno} 引数が2つでない")
            elif any(JP.search(t) for t in _texts(node.args[1])):
                bad_en.append(f"L{node.lineno} {_texts(node.args[1])}")
            continue
        texts = _texts(node)
        if not texts or isinstance(parents.get(node), ast.JoinedStr):
            continue
        if not any(JP.search(t) for t in texts):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Expr):
            continue  # docstring
        # tr(...) の日本語側（第1引数）なら良い。英語側の日本語は
        # 上の bad_en が数えるので、ここでは二重に数えない
        child, up, ok = node, parent, False
        while up is not None:
            if _is_tr(up):
                ok = any(arg is child for arg in up.args)
                break
            child, up = up, parents.get(up)
        if ok:
            continue
        key = rel.replace(os.sep, "/")
        if isinstance(node, ast.Constant) and (key, node.value) in ALLOWED:
            continue
        if isinstance(node, ast.JoinedStr) and all(
                (key, t) in ALLOWED_FSTRING_PARTS or not JP.search(t)
                for t in texts):
            continue
        bare.append(f"L{node.lineno} {texts}")
    return bare, bad_en


def test_static_sources() -> None:
    for rel in SOURCES:
        bare, bad_en = scan(rel)
        check(f"{rel}: 日本語の文字列はすべて tr を通している",
              not bare, "; ".join(bare[:5]))
        check(f"{rel}: tr の英語側に日本語が無い",
              not bad_en, "; ".join(bad_en[:5]))


def test_scan_finds_mistakes() -> None:
    """検査そのものが効いていること（わざと間違えた例を見つける）。"""
    import tempfile
    sample = ('def f(name):\n'
              '    """説明は対象外"""\n'
              '    a = tr("日本語", "English")\n'
              '    b = "残っている日本語"\n'
              '    c = tr(f"{name}を消しました", f"{name}を消しました")\n'
              '    return a, b, c\n')
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        path = os.path.join(tmp, "sample.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sample)
        bare, bad_en = scan(os.path.relpath(path, ROOT))
    check("tr を通していない日本語を見つける",
          len(bare) == 1 and "残っている日本語" in bare[0], str(bare))
    check("英語側の日本語を見つける",
          len(bad_en) == 1 and "L5" in bad_en[0], str(bad_en))


def test_normalize() -> None:
    check("ja はそのまま", i18n.normalize("ja") == "ja")
    check("en-US は en", i18n.normalize("en-US") == "en")
    check("EN は en", i18n.normalize("EN") == "en")
    check("ja_JP.UTF-8 は ja", i18n.normalize("ja_JP.UTF-8") == "ja")
    check("fr は決まらない", i18n.normalize("fr") is None)
    check("文字列でなければ決まらない", i18n.normalize(None) is None)
    check("設定の auto はそのまま", i18n.normalize_setting("auto") == "auto")
    check("設定の English は en", i18n.normalize_setting("English") == "en")
    check("読めない設定は auto", i18n.normalize_setting("日本語") == "auto")
    check("設定が数値でも auto", i18n.normalize_setting(3) == "auto")


def test_resolve_order() -> None:
    saved = os.environ.get(i18n.ENV_VAR)
    try:
        os.environ[i18n.ENV_VAR] = "en"
        check("環境変数は設定より強い", i18n.resolve("ja") == "en")
        os.environ[i18n.ENV_VAR] = ""
        check("環境変数が無ければ設定", i18n.resolve("en") == "en")
        check("設定が ja なら ja", i18n.resolve("ja") == "ja")
        check("設定が auto なら PC の表示言語",
              i18n.resolve("auto") == i18n.system_language())
        check("PC の表示言語は ja か en",
              i18n.system_language() in i18n.LANGUAGES)
    finally:
        if saved is None:
            os.environ.pop(i18n.ENV_VAR, None)
        else:
            os.environ[i18n.ENV_VAR] = saved
        i18n.init(None)


def test_tr() -> None:
    saved = i18n._current
    try:
        i18n._current = "en"
        check("英語なら英語側", i18n.tr("日本語", "English") == "English")
        i18n._current = "ja"
        check("日本語なら日本語側", i18n.tr("日本語", "English") == "日本語")
    finally:
        i18n._current = saved


def test_config_language() -> None:
    import json
    import tempfile
    check("既定は auto", Config().language == "auto")
    check("手編集の English を en に寄せる",
          Config(language="English").language == "en")
    check("読めない値は auto", Config(language="xx").language == "auto")
    saved = i18n._current
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"language": "en"}, fh)
            from pathlib import Path
            cfg = Config.load(Path(path))
            # テストは OBSNAVI_LANG=ja で走るので、環境変数が勝つ
            check("読み込むと言語が決まる（環境変数が勝つ）",
                  i18n.language() == i18n.resolve("en"))
            check("保存すると language が残る",
                  cfg.save(Path(path))
                  and json.load(open(path, encoding="utf-8"))["language"]
                  == "en")
    finally:
        i18n._current = saved


def run() -> tuple[int, int]:
    _results.clear()
    for fn in (test_normalize, test_resolve_order, test_tr,
               test_config_language, test_static_sources,
               test_scan_finds_mistakes):
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
    os.environ.setdefault("OBSNAVI_LANG", "ja")
    p, f = run()
    for nm, ok, detail in _results:
        mark = "OK" if ok else "NG"
        line = f"[{mark}] {nm}"
        if not ok and detail:
            line += f" -> {detail}"
        print(line)
    print(f"i18n: {p} passed, {f} failed")
