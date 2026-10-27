"""HTML の解説文書を、読み上げ向けのプレーンテキストに変換する。

HTML 側を直して再実行すれば txt が追従するので、二重管理にならない。
見出しは記号で階層を示し、リストは番号・中黒を残す。table は
行ごとに「見出し: 値」の形へ展開する（読み上げでセルの対応が
崩れないようにするため）。

英語の文書（<html lang="en">）は英語向けの記号で書く。■ や ・ は
英語の声だと記号の名前を読まれるので、見出しは「== 」「-- 」、
箇条は「- 」、用語は「用語:」、名前の無い列は「Column N」にする。
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# 見出しの深さごとの装飾。読み上げたときに階層がわかる形にする。
HEADING_PREFIX: dict[str, str] = {
    "h1": "",
    "h2": "■ ",
    "h3": "◆ ",
    "h4": "・",
}
# 英語の文書の記号（言語ごとに違うものだけ）
SYMBOLS = {
    "ja": {"h2": "■ ", "h3": "◆ ", "h4": "・", "bullet": "・",
           "dt_open": "【", "dt_close": "】", "column": "項目{n}"},
    "en": {"h2": "== ", "h3": "-- ", "h4": "- ", "bullet": "- ",
           "dt_open": "", "dt_close": ":", "column": "Column {n}"},
}

BLOCK_TAGS = frozenset(
    {"p", "div", "section", "header", "main", "nav", "article",
     "h1", "h2", "h3", "h4", "li", "dt", "dd", "tr"}
)
# 中身を丸ごと捨てるタグ。必ず閉じタグを持つものだけを入れること。
# meta や link のような空要素をここに入れると、閉じタグが来ないまま
# 深度が加算され続けて以降の本文がすべて消える（一度これで踏んだ）。
SKIP_TAGS = frozenset({"style", "script", "title"})

# 空要素。開始タグだけが来るので、深度を触らずに無視する。
VOID_TAGS = frozenset({"meta", "link", "br", "img", "hr", "input", "source"})


class DocumentToText(HTMLParser):
    """必要な構造だけを残してテキスト化する。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        # ol のネストごとに連番を持つ。ul は None を積む。
        self._list_stack: list[int | None] = []
        self._pending_prefix = ""
        self._in_table_header = False
        self._header_cells: list[str] = []
        self._row_cells: list[str] = []
        self._cell_buffer: list[str] | None = None
        self.sym = SYMBOLS["ja"]

    # -- 内部ユーティリティ ------------------------------------------------

    def _flush(self) -> None:
        text = "".join(self._buffer)
        self._buffer.clear()
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            self._pending_prefix = ""
            return
        self.lines.append(self._pending_prefix + text)
        self._pending_prefix = ""

    def _blank_line(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    # -- HTMLParser のフック ----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "html":
            lang = (dict(attrs).get("lang") or "ja").lower()
            self.sym = SYMBOLS["en" if lang.startswith("en") else "ja"]
            return
        if tag in VOID_TAGS and tag != "br":
            return

        if tag in ("ol", "ul"):
            self._flush()
            self._list_stack.append(0 if tag == "ol" else None)
            return

        if tag == "li":
            self._flush()
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] is not None:
                self._list_stack[-1] += 1
                self._pending_prefix = f"{indent}{self._list_stack[-1]}. "
            else:
                self._pending_prefix = f"{indent}{self.sym['bullet']}"
            return

        if tag in ("th", "td"):
            self._cell_buffer = []
            self._in_table_header = tag == "th"
            return

        if tag == "tr":
            self._row_cells = []
            return

        if tag == "br":
            self._flush()
            return

        if tag in BLOCK_TAGS:
            self._flush()
            if tag in HEADING_PREFIX:
                self._blank_line()
                self._pending_prefix = self.sym.get(tag, HEADING_PREFIX[tag])
            elif tag == "dt":
                self._pending_prefix = self.sym["dt_open"]
            elif tag == "dd":
                self._pending_prefix = "  "

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag in ("th", "td"):
            cell = re.sub(r"\s+", " ", "".join(self._cell_buffer or [])).strip()
            self._row_cells.append(cell)
            self._cell_buffer = None
            return

        if tag == "tr":
            if self._in_table_header and not self._header_cells:
                self._header_cells = list(self._row_cells)
            else:
                # ヘッダー名とセルを組にして1行ずつ出す。
                parts = []
                for index, cell in enumerate(self._row_cells):
                    label = (
                        self._header_cells[index]
                        if index < len(self._header_cells)
                        else self.sym["column"].format(n=index + 1)
                    )
                    parts.append(f"{label}: {cell}")
                if parts:
                    self.lines.append(self.sym["bullet"] + " / ".join(parts))
            self._row_cells = []
            self._in_table_header = False
            return

        if tag in ("ol", "ul"):
            self._flush()
            if self._list_stack:
                self._list_stack.pop()
            if not self._list_stack:
                self._blank_line()
            return

        if tag == "dt":
            self._buffer.append(self.sym["dt_close"])
            self._flush()
            return

        if tag in BLOCK_TAGS:
            self._flush()
            if tag in HEADING_PREFIX:
                self.lines.append("")
        if tag == "table":
            self._header_cells = []
            self._blank_line()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell_buffer is not None:
            self._cell_buffer.append(data)
        else:
            self._buffer.append(data)

    # -- 出力 --------------------------------------------------------------

    def render(self) -> str:
        self._flush()
        out: list[str] = []
        for line in self.lines:
            if line == "" and out and out[-1] == "":
                continue  # 空行の連続はひとつにまとめる
            out.append(line)
        return "\n".join(out).strip() + "\n"


def convert(source: Path, destination: Path) -> int:
    """source の HTML を読み、destination へテキストを書く。文字数を返す。"""
    parser = DocumentToText()
    parser.feed(source.read_text(encoding="utf-8"))
    text = parser.render()
    destination.write_text(text, encoding="utf-8", newline="\r\n")
    return len(text)


def main() -> int:
    if len(sys.argv) != 3:
        print("使い方: python html_to_txt.py <入力.html> <出力.txt>")
        return 1
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    if not source.is_file():
        print(f"[エラー] 入力が見つかりません: {source}")
        return 1
    size = convert(source, destination)
    print(f"変換しました: {destination} ({size} 文字)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
