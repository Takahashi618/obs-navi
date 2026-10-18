"""配布用の説明文書（HTML）の構造を検査する。外部ライブラリを使わない。

    python -X utf8 tools/check_html.py <検査する.html> [...]

検査対象はコマンドラインで受け取る。検査するのは5点。
  1. html 要素に lang="ja" があり、タグの入れ子が閉じているか
  2. 見出しが h1 → h2 → h3 と飛ばずに下がっているか
     （読み上げは見出しで移動するので、飛ぶと構造が壊れて聞こえる）
  3. ページ内リンク（#で始まる href）の飛び先 id が存在するか
  4. dl の中の dt / dd が対になっているか
  5. 表があるなら見出しセル（th）があるか
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"meta", "link", "br", "hr", "img", "input", "area", "base", "col",
        "source"}


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unbalanced: list[str] = []
        self.headings: list[int] = []
        self.ids: set[str] = set()
        self.internal_links: list[str] = []
        self.lang: str | None = None
        self.counts: dict[str, int] = {}

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag == "html":
            self.lang = a.get("lang")
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.internal_links.append(a["href"][1:])
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.unbalanced.append(tag)


def check_file(path: Path) -> list[str]:
    """1つの HTML を検査して、失敗の説明を返す（空なら合格）。"""
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        print(f"  {'OK  ' if condition else 'NG  '} {message}")
        if not condition:
            failures.append(f"{path.name}: {message}")

    source = path.read_text(encoding="utf-8")
    parser = Collector()
    parser.feed(source)
    print(f"検査対象: {path}  ({len(source)} 文字)")

    check(parser.lang == "ja", "html 要素に lang='ja' がある")
    check(not parser.unbalanced,
          f"閉じタグの不整合がない（{parser.unbalanced[:5]}）")
    check(not parser.stack, f"閉じ忘れがない（{parser.stack[:5]}）")

    jumps = [(i, prev, cur) for i, (prev, cur)
             in enumerate(zip(parser.headings, parser.headings[1:]))
             if cur > prev + 1]
    check(parser.headings[:1] == [1], "最初の見出しが h1")
    check(parser.headings.count(1) == 1, "h1 は1つだけ")
    check(not jumps, f"見出しの階層が飛んでいない（{jumps[:5]}）")

    missing = sorted({t for t in parser.internal_links
                      if t not in parser.ids})
    check(not missing, f"リンク先の id がすべて存在する（欠落: {missing}）")

    dt = parser.counts.get("dt", 0)
    dd = parser.counts.get("dd", 0)
    check(dt == dd, f"dt と dd の数が一致する（dt={dt} dd={dd}）")
    if parser.counts.get("table", 0):
        check(parser.counts.get("th", 0) > 0, "表に見出しセル（th）がある")
    print(f"  参考  見出し: {len(parser.headings)} / 用語（dt）: {dt} / "
          f"表: {parser.counts.get('table', 0)}")
    return failures


def main(argv: list[str]) -> int:
    if not argv:
        print("使い方: python -X utf8 tools/check_html.py <検査する.html> [...]")
        return 1
    failures: list[str] = []
    for name in argv:
        path = Path(name)
        if not path.is_file():
            print(f"見つかりません: {path}")
            failures.append(f"{path}: 見つからない")
            continue
        failures.extend(check_file(path))
        print()
    if failures:
        print(f"失敗 {len(failures)} 件")
        return 1
    print("すべて通過")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
