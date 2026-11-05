# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec.  Run via build.bat (or: pyinstaller packaging/mathdraw.spec --noconfirm)
# Produces a one-folder build in dist/<APP_NAME>/ (one-folder keeps the Qt LGPL libraries
# replaceable by the user, which is part of LGPL compliance — don't switch to --onefile).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from mathdraw import branding as B  # noqa: E402

# Windows file properties (Explorer > Properties > Details)
ver = tuple(int(x) for x in (B.VERSION.split(".") + ["0", "0", "0"])[:4])
version_file = os.path.join(ROOT, "build", "version_info.txt")
os.makedirs(os.path.dirname(version_file), exist_ok=True)
with open(version_file, "w", encoding="utf-8") as fh:
    fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={ver}, prodvers={ver}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', {B.PUBLISHER!r}),
    StringStruct('FileDescription', {B.APP_NAME!r}),
    StringStruct('FileVersion', {B.VERSION!r}),
    StringStruct('InternalName', {B.APP_ID!r}),
    StringStruct('LegalCopyright', {'© ' + B.COPYRIGHT_YEAR + ' ' + B.PUBLISHER!r}),
    StringStruct('OriginalFilename', {B.APP_NAME + '.exe'!r}),
    StringStruct('ProductName', {B.APP_NAME!r}),
    StringStruct('ProductVersion', {B.VERSION!r})])]),
  VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")

model = os.path.join(ROOT, "mathdraw", "assets", "hand_landmarker.task")
if not os.path.exists(model):
    raise SystemExit("Hand model missing: run  python tools/fetch_model.py  first (build.bat does this).")

datas = [(os.path.join(ROOT, "mathdraw", "assets"), "mathdraw/assets")]
pub = os.path.join(ROOT, "mathdraw", "license_pubkey.txt")
if os.path.exists(pub):
    datas.append((pub, "mathdraw"))
for doc in ("EULA.txt", "PRIVACY.txt", "THIRD_PARTY_NOTICES.txt"):
    datas.append((os.path.join(ROOT, doc), "."))
if os.path.isdir(os.path.join(ROOT, "licenses")):
    datas.append((os.path.join(ROOT, "licenses"), "licenses"))
datas += collect_data_files("mediapipe", excludes=["**/*.py", "**/*.pyc", "**/testdata/**"])
binaries = collect_dynamic_libs("mediapipe")
hiddenimports = collect_submodules("mediapipe.tasks.python", filter=lambda m: ".genai" not in m) + [
    "scipy.integrate", "scipy.optimize", "contourpy",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
]
excludes = ["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "jupyter", "notebook", "pytest", "_pytest",
            "pandas", "lxml", "gi", "mediapipe.tasks.python.genai", "torch", "jax", "tensorflow",
            "PySide6.QtVirtualKeyboard",
            "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_qtagg",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"]

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=B.APP_NAME,
    icon=os.path.join(ROOT, "mathdraw", "assets", "icon.ico"),
    version=version_file,
    console=False,  # windowed app
    upx=False,  # UPX-packed exes trigger antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name=B.APP_NAME, upx=False)
