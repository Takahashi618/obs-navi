# -*- mode: python ; coding: utf-8 -*-
"""OBSナビ の PyInstaller 設定。

ビルド:
    python -m PyInstaller --noconfirm obs_navi.spec
出力:
    dist\\OBSNavi\\OBSNavi.exe （フォルダ配布。設定ファイルは exe の隣に作られる）

★名前は英字にする（0.20.1、利用者の指示）。配布物のファイル名に日本語が
  あると、展開する道具や環境によって文字化けすることがあるため

なぜ onefile にしないか:
    onefile は起動のたびに一時フォルダへ展開するため、wxPython を含む
    このアプリでは起動が数秒遅くなる。配信の直前に立ち上げる道具なので
    起動の速さを優先し、フォルダ配布（onedir）にしている。

★最重要: accessible_output2 の lib フォルダ
    PC-Talker(PCTKUSR.dll) や NVDA(nvdaControllerClient*.dll) との橋渡しは
    実行時にパスで読み込まれる DLL で行われる。PyInstaller は import を
    たどるだけなのでこれらを自動では拾わず、同梱し忘れると
    「起動はするが一切喋らない」という最悪の壊れ方をする。
    そのため datas に明示的に入れている。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# accessible_output2 のデータ（lib\*.dll を含む）をまるごと同梱する
ao2_datas = collect_data_files("accessible_output2", include_py_files=False)
# 出力方式は動的に import されるためサブモジュールも明示的に集める
ao2_hidden = collect_submodules("accessible_output2")

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=ao2_datas,
    hiddenimports=ao2_hidden + [
        "accessible_output2.outputs.auto",
        "accessible_output2.outputs.nvda",
        "accessible_output2.outputs.pc_talker",
        "accessible_output2.outputs.sapi5",
        "accessible_output2.outputs.jaws",
        "accessible_output2.outputs.system_access",
        "accessible_output2.outputs.window_eyes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 使っていない重量級パッケージを除いて配布サイズを抑える
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest",
        "numpy", "matplotlib", "PIL", "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OBSNavi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # ★console=False（ウィンドウアプリ）。コンソールが出ると
    #   スクリーンリーダーが黒い窓を読み上げてしまい邪魔になる。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OBSNavi",
)
