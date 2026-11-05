"""Gather the licence files of every bundled third-party package into ./licenses/ (shipped with the app).

Run inside the build environment (build.bat does this).  Build-only tools are skipped.
"""
import importlib.metadata as md
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "licenses")
SKIP = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
        "pywin32-ctypes", "pytest", "pluggy", "iniconfig", "packaging", "colorama", "_pytest"}
PAT = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
rows = []
for dist in sorted(md.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
    name = dist.metadata["Name"] or "unknown"
    if name.lower() in SKIP:
        continue
    lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
    lic = lic.splitlines()[0][:80] if lic else ""
    if not lic:
        cls = [c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = ", ".join(cls)
    copied = 0
    for f in dist.files or []:
        base = os.path.basename(str(f))
        if PAT.search(base) and not base.endswith((".py", ".pyc")):
            src = dist.locate_file(f)
            if os.path.isfile(src):
                dst = os.path.join(OUT, name)
                os.makedirs(dst, exist_ok=True)
                shutil.copy2(src, os.path.join(dst, base))
                copied += 1
    rows.append(f"{name:28s} {dist.version:14s} {lic}{'' if copied else '   (no licence file in package metadata)'}")
with open(os.path.join(OUT, "PACKAGES.txt"), "w", encoding="utf-8") as fh:
    fh.write("Third-party Python packages bundled with this application\n\n" + "\n".join(rows) + "\n")
print(f"Collected licences for {len(rows)} packages into {OUT}")
