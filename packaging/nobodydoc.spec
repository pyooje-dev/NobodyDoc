# -*- mode: python ; coding: utf-8 -*-
# Fabrication : pyinstaller packaging/nobodydoc.spec
# NOBODYDOC_ONEFILE=1 produit un seul NobodyDoc.exe ; sinon un dossier portable.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
ONEFILE = os.environ.get("NOBODYDOC_ONEFILE") == "1"

datas = [(str(ROOT / "nobodydoc" / "gui" / "resources"), "nobodydoc/gui/resources")]
binaries = []
hiddenimports = []
for package in ("spacy", "fr_core_news_md", "thinc", "spacy_legacy", "spacy_loggers", "srsly",
                "catalogue", "confection", "blis", "cymem", "preshed", "murmurhash", "wasabi",
                "extract_msg", "olefile", "compressed_rtf", "RTFDE", "red_black_dict_mod"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += [m for m in h if ".tests" not in m]
for package in ("spacy", "fr_core_news_md", "thinc"):
    datas += copy_metadata(package)

excludes = [
    "tkinter", "matplotlib", "IPython", "notebook", "pytest", "torch", "tensorflow",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtNetwork",
]

a = Analysis(
    [str(ROOT / "packaging" / "NobodyDoc.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["nobodydoc.selftest"],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / "nobodydoc.ico")
version = str(ROOT / "packaging" / "version_info.txt")

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NobodyDoc", console=False,
              icon=icon, version=version if os.path.exists(version) else None, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NobodyDoc", console=False,
              icon=icon, version=version if os.path.exists(version) else None, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="NobodyDoc", upx=False)
