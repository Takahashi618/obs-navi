# -*- coding: utf-8 -*-
"""テスター向けの配布パッケージ（zip）を作る。

    python -X utf8 tools/build_release.py                 本番（git がきれいなこと）
    python -X utf8 tools/build_release.py --allow-dirty   試しに作る（書きかけの変更あり）

できるもの（release/ は git 管理外）:
    release/obs-navi-<版>-test/        中身を並べたフォルダ（確かめる用）
    release/obs-navi-<版>-test.zip     配るもの

★配布物のファイル名とフォルダ名はすべて英字にする（0.20.1、利用者の
  指示）。日本語の名前は、展開する道具や環境によって文字化けすることが
  ある。zip の名前は GitHub のリポジトリ名（obs-navi）とそろえる。
  日本語の書類は名前に「(Japanese)」、英語の書類は「(English)」を付ける

手順。どこかで失敗したら zip は作らない:
 1. 実行ファイルを確かめる。exe の中の版が version.py と同じか、exe が
    ソースより新しいか、読み上げ用の DLL が8個あるか
 2. 文書のうちコードから作る節を作り直し（tools/doc_parts.py）、構造を
    検査する（tools/check_html.py）
 3. ソースに書きかけの変更が無いかを git で確かめる（同梱するソースと
    exe・文書がずれないように）
 4. 並べる: exe 一式、文書（HTML と txt。日本語と英語）、ライセンス、
    同梱部品のライセンス、ソースコード
 5. zip にして、中身を確かめる

★OBSナビは GPL-3.0 で配る（使っている obsws-python が GPL-3.0 のため）。
  だからソースコードとライセンスの全文を同じ zip に入れる。同梱部品の
  ライセンスは、手で書かずに「実際に exe に入ったファイル」から作る
  （PyInstaller の目録 → 各部品の RECORD で持ち主を引く）。一覧に無い
  部品が入っていたら止まる。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata as md
import re
import shutil
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import check_html  # noqa: E402
import doc_parts  # noqa: E402  （import した時点で読み上げを無音にする）
from html_to_txt import DocumentToText  # noqa: E402
from version import VERSION  # noqa: E402

DIST = ROOT / "dist" / "OBSNavi"
EXE = DIST / "OBSNavi.exe"
BUILD = ROOT / "build" / "obs_navi"
RELEASE = ROOT / "release"
DOCS = ROOT / "docs"
NAME = f"obs-navi-{VERSION}-test"
SOURCE_DIR = "source"
# ソースコードのフォルダに入れる説明（日本語と英語）
SOURCE_ABOUT = "About the source code (Japanese).txt"
SOURCE_ABOUT_EN = "About the source code (English).txt"

# 読み上げの橋渡しをする DLL。1つでも欠けると「起動するが喋らない」
# （obs_navi.spec の説明）
EXPECTED_DLLS = frozenset({
    "PCTKUSR.dll", "PCTKUSR64.dll",
    "nvdaControllerClient32.dll", "nvdaControllerClient64.dll",
    "SAAPI32.dll", "ZDSRAPI.dll", "ZDSRAPI_x64.dll", "dolapi.dll",
})

# exe がこれより古ければ作り直しが要る
SOURCE_GLOBS = ("app.py", "version.py", "speech.py", "obs_navi.spec",
                "core/*.py", "ui/*.py")

# 同梱するソース（git で追跡しているもののうち、ここで始まるもの）。
# ★開発中の確かめ用スクリプト、作業記録、利用者の設定
#   （obs_navi_config.json）は入れない
SOURCE_INCLUDE = ("app.py", "version.py", "speech.py", "obs_navi.spec",
                  "LICENSE.txt", "README.md", "README.en.md", "core/", "ui/",
                  "tests/", "tools/", "docs/")

# 文書: (元の HTML, 配布物での名前（拡張子なし）)。名前は英字にし、
# 言語を「(Japanese)」「(English)」で見分ける
DOC_PAGES = (("manual.html", "Manual (Japanese)"),
             ("tester.html", "Testing Guide (Japanese)"),
             ("manual.en.html", "Manual (English)"),
             ("tester.en.html", "Testing Guide (English)"))

# はじめにお読みください: (元のテンプレート, 配布物での名前)
README_FIRST = (("readme_first.txt", "README (Japanese).txt"),
                ("readme_first.en.txt", "README (English).txt"))

# 配布物の直下に並ぶもの。はじめにお読みくださいの「ファイルが13、
# フォルダが2つ」（英語版は 13 files and 2 folders）と一致させる
# （ずれたら止める）
TOP_FILES = frozenset({
    "OBSNavi.exe", "README (Japanese).txt", "README (English).txt",
    "Manual (Japanese).html", "Manual (Japanese).txt",
    "Manual (English).html", "Manual (English).txt",
    "Testing Guide (Japanese).html", "Testing Guide (Japanese).txt",
    "Testing Guide (English).html", "Testing Guide (English).txt",
    "LICENSE.txt", "THIRD-PARTY-NOTICES.txt",
})
TOP_DIRS = frozenset({"_internal", SOURCE_DIR})

# zip に入っていたら止めるもの
FORBIDDEN = ("obs_navi_config.json", "HANDOFF.md", "CC_LOG.md", "__pycache__",
             ".pyc", "/.git", ".claude", "/diag_", "/live_", "/probe_",
             "_last_run.txt", "_result.txt", ".tmp")

LICENSE_NAME_RE = re.compile(r"^(licen[cs]e|copying|notice)", re.I)
# license.py のようなコードを拾わないよう、文書の拡張子に限る
LICENSE_SUFFIXES = frozenset({"", ".txt", ".md", ".rst", ".apache", ".bsd",
                              ".mit", ".psf"})


class ReleaseError(Exception):
    """配布物を作れない理由（利用者に読ませる日本語）。"""


def step(title: str) -> None:
    print(f"\n== {title}")


# ------------------------------------------------------------
# 1. 実行ファイル
# ------------------------------------------------------------
def embedded_version(exe: Path) -> str:
    """exe の中に入っている version.VERSION を読む（起動せずに）。

    ★起動して窓のタイトルで確かめると、読み上げが始まってしまう。
    PyInstaller の読み取り機能で、埋め込まれた PYZ から version を
    取り出し、定数を見る。
    """
    from PyInstaller.archive.readers import CArchiveReader

    pkg = CArchiveReader(str(exe))
    pyz_name = next(n for n in pkg.toc if n.upper().startswith("PYZ"))
    code = pkg.open_embedded_archive(pyz_name).extract("version")
    found = [c for c in code.co_consts
             if isinstance(c, str) and re.fullmatch(r"\d+\.\d+\.\d+", c)]
    return found[0] if found else ""


def check_exe() -> None:
    step("1. 実行ファイルを確かめる")
    if not EXE.is_file():
        raise ReleaseError(f"実行ファイルがありません: {EXE}")
    got = embedded_version(EXE)
    if got != VERSION:
        raise ReleaseError(
            f"exe の中の版が {got or '不明'} で、version.py の {VERSION} と"
            "違います。python -X utf8 -m PyInstaller --noconfirm "
            "obs_navi.spec で作り直してください")
    print(f"  exe の中の版: {got}")
    exe_time = EXE.stat().st_mtime
    newer = [p for g in SOURCE_GLOBS for p in ROOT.glob(g)
             if p.stat().st_mtime > exe_time]
    if newer:
        names = "、".join(str(p.relative_to(ROOT)) for p in newer)
        raise ReleaseError(f"exe より新しいソースがあります（{names}）。"
                           "exe を作り直してください")
    print("  exe はソースより新しい")
    have = {p.name for p in (DIST / "_internal" / "accessible_output2"
                             / "lib").glob("*.dll")}
    missing = sorted(EXPECTED_DLLS - have)
    if missing:
        raise ReleaseError(f"読み上げ用の DLL が足りません: {missing}")
    print(f"  読み上げ用の DLL: {len(EXPECTED_DLLS)}個そろっている")
    toc = BUILD / "PYZ-00.toc"
    if not toc.is_file() or abs(toc.stat().st_mtime - exe_time) > 600:
        raise ReleaseError(
            "build フォルダの目録が、今の exe と同じビルドのものではありません。"
            "exe を作り直してください（同梱部品の一覧を目録から作るため）")


# ------------------------------------------------------------
# 2. 文書
# ------------------------------------------------------------
def check_docs() -> None:
    step("2. 文書を今のコードに合わせて、検査する")
    changed = doc_parts.update_docs()
    for path in changed:
        print(f"  作り直した: {path.relative_to(ROOT)}")
    if not changed:
        print("  文書は今のコードと合っている")
    targets = [str(DOCS / src) for src, _ in DOC_PAGES]
    if check_html.main(targets) != 0:
        raise ReleaseError("文書の検査に通りませんでした（上の NG を参照）")
    check_readme()


def check_readme() -> None:
    """README.md と README.en.md の部品の版が、今入っている版と同じか。

    ★README はテンプレートにせず、そのまま読める形で置く（GitHub で
    表示する）。そのかわり、書いてある入れ方の行が今の版とずれたら止める。
    """
    values = dependency_values()
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        stale = [values[k] for k in ("PIP_INSTALL", "PYINSTALLER_PIN")
                 if values[k] not in text]
        if stale:
            raise ReleaseError(f"{name} の部品の版が古くなっています。"
                               "次の行に合わせてください: " + " / ".join(stale))
        print(f"  {name} の部品の版は今と同じ")


# ------------------------------------------------------------
# 3. git
# ------------------------------------------------------------
def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8").stdout


def check_git(allow_dirty: bool) -> str:
    """同梱するソースに書きかけの変更が無いか。コミットの名前を返す。"""
    step("3. 同梱するソースに書きかけの変更が無いか確かめる")
    commit = git("rev-parse", "--short", "HEAD").strip()
    dirty = [line[3:] for line in git("status", "--porcelain").splitlines()
             if line[3:].startswith(SOURCE_INCLUDE)]
    if dirty:
        if not allow_dirty:
            raise ReleaseError(
                "コミットしていない変更があります: " + "、".join(dirty)
                + "。コミットしてから実行してください"
                "（試しに作るだけなら --allow-dirty）")
        print("  ★書きかけの変更がある（--allow-dirty）: " + "、".join(dirty))
        return f"{commit}（書きかけの変更あり）"
    print(f"  変更なし。コミット {commit}")
    return commit


def source_files() -> list[str]:
    files = [f for f in git("ls-files").splitlines()
             if f.startswith(SOURCE_INCLUDE)]
    # --allow-dirty のときだけ、まだ追跡していない新しいファイルも入れる
    files += [line[3:] for line in git("status", "--porcelain",
                                       "--untracked-files=all").splitlines()
              if line.startswith("??") and line[3:].startswith(SOURCE_INCLUDE)
              and "__pycache__" not in line]
    return sorted(set(files))


# ------------------------------------------------------------
# 4. 同梱部品のライセンス
# ------------------------------------------------------------
def _toc_entries(path: Path) -> list[tuple]:
    """PyInstaller の目録から (名前, 元のファイル, 種類) を全部取り出す。"""
    data = ast.literal_eval(path.read_text(encoding="utf-8"))
    out: list[tuple] = []

    def walk(obj) -> None:
        if isinstance(obj, (list, tuple)):
            if (len(obj) == 3 and all(isinstance(x, str) for x in obj)
                    and obj[2].isupper()):
                out.append(obj)
                return
            for x in obj:
                walk(x)

    walk(data)
    return out


def _dist_index() -> dict[str, md.Distribution]:
    """site-packages のファイル（小文字の相対パス）→ そのファイルを入れた部品。

    ★setuptools は中に別の部品を抱えている（setuptools/_vendor）。
    setuptools 自身の RECORD にも同じファイルが載っているので、抱えている
    部品の方で上書きする（より細かい持ち主を答える）。
    """
    index: dict[str, md.Distribution] = {}
    for dist in md.distributions():
        for f in dist.files or []:
            index[str(f).replace("\\", "/").lower()] = dist
    site = Path(md.distribution("setuptools").locate_file(""))
    vendor = site / "setuptools" / "_vendor"
    for dist in md.distributions(path=[str(vendor)]):
        for f in dist.files or []:
            key = "setuptools/_vendor/" + str(f).replace("\\", "/")
            index[key.lower()] = dist
    return index


def _dist_key(dist: md.Distribution) -> str:
    """部品を見分ける鍵。★名前だけでは足りない（setuptools が抱えている
    packaging と、単独で入っている packaging は版が違う別物）。"""
    return (f"{dist.metadata['Name']}=={dist.version}"
            f"@{dist.locate_file('')}")


def _is_vendored(dist: md.Distribution) -> bool:
    return "_vendor" in Path(str(dist.locate_file(""))).parts


def bundled_components() -> tuple[dict, set[str]]:
    """exe に入れたファイルの持ち主を調べる。

    返すのは ({部品の場所: Distribution}, 分類したもの) 。
    分類したものは "python"（Python 本体）と "msvc"（Windows の
    Visual C++ ランタイム）。どれにも当てはまらないファイルがあれば止める。
    """
    site = Path(md.distribution("setuptools").locate_file("")).resolve()
    base = Path(sys.base_prefix).resolve()
    windows = Path("C:/Windows").resolve()
    index = _dist_index()
    dists: dict[str, md.Distribution] = {}
    kinds: set[str] = set()
    unknown: list[str] = []
    for toc in ("PYZ-00.toc", "PKG-00.toc", "COLLECT-00.toc"):
        for _name, src, _typ in _toc_entries(BUILD / toc):
            if not src or src == "-":
                continue  # 名前空間パッケージ（ファイルを持たない）
            p = Path(src).resolve()
            if p.is_relative_to(ROOT):
                continue  # OBSナビ自身と、ビルドで作ったもの
            if p.is_relative_to(site):
                key = p.relative_to(site).as_posix().lower()
                dist = index.get(key)
                if dist is None:
                    unknown.append(src)
                    continue
                dists[_dist_key(dist)] = dist
            elif p.is_relative_to(base):
                kinds.add("python")
            elif p.is_relative_to(windows) and p.name.lower().startswith(
                    ("msvcp", "vcruntime")):
                kinds.add("msvc")
            else:
                unknown.append(src)
    # exe の起動部分（ブートローダー）は目録に載らないことがあるが、
    # 必ず入っている
    boot = md.distribution("pyinstaller")
    dists.setdefault(_dist_key(boot), boot)
    if unknown:
        raise ReleaseError(
            "持ち主の分からないファイルが exe に入っています（ライセンスを"
            "確かめてから build_release.py に分類を足してください）: "
            + "、".join(sorted(set(unknown))[:10]))
    return dists, kinds


def _license_label(dist: md.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    lic = (meta.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 80 and lic != "UNKNOWN":
        return lic
    classifiers = [c.split("::")[-1].strip()
                   for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        return "、".join(classifiers)
    return lic.splitlines()[0] if lic else "不明"


def _license_files(dist: md.Distribution) -> list[Path]:
    """部品のライセンス文書。dist-info の中を先に、無ければ RECORD 全体から。"""
    files = [f for f in dist.files or []
             if LICENSE_NAME_RE.match(Path(str(f)).name)
             and Path(str(f)).suffix.lower() in LICENSE_SUFFIXES]
    # ★自分の dist-info だけを見る。setuptools の RECORD には、抱えている
    #   部品の dist-info（setuptools/_vendor/…/LICENSE）まで載っている
    own = [f for f in files if f.parts[0].endswith(".dist-info")]
    chosen = own or [f for f in files
                     if "_vendor/" not in str(f).replace("\\", "/")]
    return [Path(dist.locate_file(f)) for f in chosen]


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in
                     text.replace("\r\n", "\n").strip().splitlines())


def third_party_notices() -> str:
    dists, kinds = bundled_components()
    gpl = _norm((ROOT / "LICENSE.txt").read_text(encoding="utf-8"))
    entries: list[tuple[str, str, str, list[tuple[str, str]]]] = []
    for dist in sorted(dists.values(),
                       key=lambda d: (d.metadata["Name"].lower(),
                                      _is_vendored(d))):
        texts = []
        for path in _license_files(dist):
            body = _norm(path.read_text(encoding="utf-8", errors="replace"))
            if body == gpl:
                body = "（全文は LICENSE.txt と同じ GNU GPL 第3版です）"
            if body not in (t for _f, t in texts):
                texts.append((path.name, body))
        if not texts:
            raise ReleaseError(
                f"{dist.metadata['Name']} のライセンス文書が見つかりません")
        label = _license_label(dist)
        if _is_vendored(dist):
            label += "。setuptools に同梱のもの"
        entries.append((dist.metadata["Name"], dist.version, label, texts))
    if "python" in kinds:
        py_license = Path(sys.base_prefix) / "LICENSE.txt"
        entries.append((
            "Python", sys.version.split()[0],
            "Python Software Foundation License Version 2 ほか"
            "（同梱の libffi・bzip2・OpenSSL・Zstandard などを含む）",
            [(py_license.name, _norm(py_license.read_text(encoding="utf-8")))]))

    lines = [
        f"OBSナビ {VERSION} に同梱している部品とライセンス",
        f"(Components bundled with OBS Navi {VERSION} and their licenses)",
        "",
        "OBSナビ本体は GNU GPL 第3版で配布しています（全文は LICENSE.txt）。",
        "OBSNavi.exe と _internal フォルダには、次の部品が入っています。",
        "この一覧は、実行ファイルを作ったときの記録（PyInstaller の目録）から",
        "作りました。部品ごとのライセンスの全文を、後ろに原文（英語）のまま",
        "載せています。",
        "",
        "OBS Navi itself is distributed under the GNU GPL version 3 (full text",
        "in LICENSE.txt). The program file and the _internal folder contain the",
        "components below. This list was made from the PyInstaller build",
        "records. The full license text of each component follows, in the",
        "original English.",
        "",
        f"部品は{len(entries)}件です。 ({len(entries)} components.)",
    ]
    lines += [f"{i}. {n} {v}（{lab}）"
              for i, (n, v, lab, _t) in enumerate(entries, 1)]
    lines += [
        "",
        "補足",
        "・accessible_output2 の lib フォルダにある DLL は、各スクリーン"
        "リーダーと連携するためのもので、accessible_output2 の配布物に"
        "含まれているものをそのまま同梱しています。PCTKUSR.dll と "
        "PCTKUSR64.dll は PC-Talker、nvdaControllerClient32.dll と "
        "nvdaControllerClient64.dll は NVDA、SAAPI32.dll は System Access、"
        "ZDSRAPI.dll と ZDSRAPI_x64.dll は ZDSR、dolapi.dll は Dolphin の"
        "ものです。",
    ]
    if "msvc" in kinds:
        lines.append(
            "・MSVCP140.dll などの Microsoft Visual C++ ランタイムは、"
            "Microsoft が再頒布を認めているファイルです。")
    for i, (n, v, lab, texts) in enumerate(entries, 1):
        for fname, body in texts:
            lines += ["", "=" * 72, f"{i}. {n} {v}", f"License: {lab}",
                      f"（ライセンス文書: {fname}）", "=" * 72, "", body]
    lines += ["", "以上です。"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------
# 4. 並べる
# ------------------------------------------------------------
def write_text_for_windows(path: Path, text: str) -> None:
    """配布する txt の書き方: UTF-8（BOM 付き）・改行は CRLF。

    ★BOM を付けるのは、日本語の古いエディタが BOM の無い UTF-8 を
    Shift_JIS と取り違えて文字化けするのを避けるため。メモ帳は
    どちらでも読める。
    """
    text = text.replace("\r\n", "\n")
    path.write_text(text, encoding="utf-8-sig", newline="\r\n")


def html_to_text(src: Path) -> str:
    parser = DocumentToText()
    parser.feed(src.read_text(encoding="utf-8"))
    return parser.render()


def fill(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    left = re.findall(r"\{[A-Z_]+\}", text)
    if left:
        raise ReleaseError(f"{template.name} に埋められない印があります: {left}")
    return text


def dependency_values() -> dict[str, str]:
    """ソースの説明に書く、動かすのに要る部品とその版（書き写さない）。"""
    names = ("wxPython", "obsws-python", "websocket-client",
             "accessible_output2")
    pins = [f"{n}=={md.version(n)}" for n in names]
    lines = [f"・{n} {md.version(n)}" for n in names]
    lines.append(f"・PyInstaller {md.version('pyinstaller')}"
                 "（実行ファイルを作るときだけ）")
    return {
        "PYTHON_VERSION": sys.version.split()[0],
        "REQUIREMENTS": "\n".join(lines),
        "PIP_INSTALL": "python -m pip install " + " ".join(pins),
        "PYINSTALLER_PIN": f"pyinstaller=={md.version('pyinstaller')}",
    }


def stage_release(commit: str) -> Path:
    step("4. 配布物を並べる")
    stage = RELEASE / NAME
    if stage.exists():
        shutil.rmtree(stage)
    RELEASE.mkdir(exist_ok=True)
    # exe 一式。★利用者の設定（exe の隣にできる）は持ち出さない
    shutil.copytree(DIST, stage, ignore=shutil.ignore_patterns(
        "obs_navi_config.json", "*.tmp"))
    for src, name in DOC_PAGES:
        shutil.copy2(DOCS / src, stage / f"{name}.html")
        text = html_to_text(DOCS / src)
        write_text_for_windows(stage / f"{name}.txt", text)
        print(f"  {name}.txt  {len(text)}文字")
    for src, name in README_FIRST:
        write_text_for_windows(
            stage / name, fill(DOCS / src, {"VERSION": VERSION}))
    shutil.copy2(ROOT / "LICENSE.txt", stage / "LICENSE.txt")
    notices = third_party_notices()
    write_text_for_windows(stage / "THIRD-PARTY-NOTICES.txt", notices)
    count = re.search(r"部品は(\d+)件です", notices).group(1)
    print(f"  THIRD-PARTY-NOTICES.txt  部品{count}件")
    src_dir = stage / SOURCE_DIR
    files = source_files()
    for rel in files:
        dest = src_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    values = {"VERSION": VERSION, "COMMIT": commit, **dependency_values()}
    write_text_for_windows(src_dir / SOURCE_ABOUT,
                           fill(DOCS / "source_readme.txt", values))
    # 英語版。★コミットの名前の「（書きかけの変更あり）」は英語にする
    values_en = dict(values, COMMIT=commit.replace(
        "（書きかけの変更あり）", " (with uncommitted changes)"))
    values_en["REQUIREMENTS"] = values["REQUIREMENTS"].replace(
        "・", "- ").replace("（実行ファイルを作るときだけ）",
                             " (only for building the program file)")
    write_text_for_windows(src_dir / SOURCE_ABOUT_EN,
                           fill(DOCS / "source_readme.en.txt", values_en))
    print(f"  ソースコード: {len(files)}ファイル（コミット {commit}）")
    return stage


# ------------------------------------------------------------
# 5. zip
# ------------------------------------------------------------
def make_zip(stage: Path) -> Path:
    step("5. zip にして、中身を確かめる")
    zip_path = RELEASE / f"{NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                zf.write(p, f"{NAME}/{p.relative_to(stage).as_posix()}")
    verify_zip(zip_path)
    return zip_path


def verify_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise ReleaseError(f"zip が壊れています: {bad}")
        infos = zf.infolist()
        names = [i.filename for i in infos]
        prefix = f"{NAME}/"
        if any(not n.startswith(prefix) for n in names):
            raise ReleaseError("最上位のフォルダの外にファイルがあります")
        tops_files = {n[len(prefix):] for n in names
                      if "/" not in n[len(prefix):]}
        tops_dirs = {n[len(prefix):].split("/")[0] for n in names
                     if "/" in n[len(prefix):]}
        if tops_files != TOP_FILES or tops_dirs != TOP_DIRS:
            raise ReleaseError(
                f"直下の並びが、はじめにお読みくださいの説明と違います: "
                f"ファイル {sorted(tops_files)} / フォルダ {sorted(tops_dirs)}")
        hits = [n for n in names for f in FORBIDDEN if f in "/" + n]
        if hits:
            raise ReleaseError(f"入れてはいけないものがあります: {hits[:5]}")
        dll_dir = f"{prefix}_internal/accessible_output2/lib/"
        have = {n[len(dll_dir):] for n in names if n.startswith(dll_dir)}
        if not EXPECTED_DLLS <= have:
            raise ReleaseError(
                f"zip に読み上げ用の DLL が足りません: {EXPECTED_DLLS - have}")
        # ★名前はすべて英字（ASCII）にする。日本語の名前は、展開する道具や
        #   環境によって文字化けする（UTF-8 の印 0x800 を付けても、読まない
        #   道具がある）
        non_ascii = [n for n in names if not n.isascii()]
        if non_ascii:
            raise ReleaseError(f"英字でない名前があります: {non_ascii[:3]}")
        exe_info = zf.getinfo(f"{prefix}{EXE.name}")
        if exe_info.CRC != zlib.crc32(EXE.read_bytes()):
            raise ReleaseError("zip の中の exe が dist の exe と違います")
        for n in names:
            if not (n.endswith(".txt") and "/" not in n[len(prefix):]):
                continue
            raw = zf.read(n)
            if n.endswith("LICENSE.txt"):
                continue  # 英語の原文そのまま（ASCII）
            if not raw.startswith(b"\xef\xbb\xbf"):
                raise ReleaseError(f"BOM がありません: {n}")
            if re.search(rb"(?<!\r)\n", raw):
                raise ReleaseError(f"改行が CRLF になっていません: {n}")
        size = zip_path.stat().st_size / 1024 / 1024
        print(f"  {len(names)}ファイル、{size:.1f}MB。壊れていない")
        print(f"  直下: ファイル{len(tops_files)}つ、フォルダ{len(tops_dirs)}つ")
        print("  名前はすべて英字")
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        print(f"  SHA-256: {digest}")


def main(argv: list[str]) -> int:
    allow_dirty = "--allow-dirty" in argv
    started = time.monotonic()
    try:
        check_exe()
        check_docs()
        commit = check_git(allow_dirty)
        stage = stage_release(commit)
        zip_path = make_zip(stage)
    except ReleaseError as exc:
        print(f"\n[失敗] {exc}")
        return 1
    print(f"\nできました: {zip_path}（{time.monotonic() - started:.0f}秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
