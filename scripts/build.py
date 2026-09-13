"""Build a self-contained Windows GUI + CLI archive from public sources."""
from pathlib import Path
import ctypes
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
if os.name != "nt":
    raise SystemExit("Build the Windows package on Windows x64.")
k = ctypes.WinDLL("kernel32")
k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
k.SetPriorityClass(ctypes.c_void_p(-1), 0x40)
runtime = ROOT/"runtime/innoextract"
if not (runtime/"innoextract.exe").exists():
    subprocess.run([sys.executable, str(ROOT/"scripts/fetch-runtime.py")], check=True)
dist = ROOT/"dist"
for name, windowed in [("EVPlayerUnlockerCLI", False), ("EVPlayer Unlocker", True)]:
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", name,
            "--paths", str(ROOT/"src"), "--distpath", str(dist), "--workpath", str(ROOT/"build"/name),
            "--specpath", str(ROOT/"build"), "--add-data", str(runtime)+";runtime/innoextract",
            "--windowed" if windowed else "--console", str(ROOT/"scripts/entry.py")]
    subprocess.run(args, check=True, cwd=ROOT)
package = dist/f"evplayer-unlocker-v{VERSION}-windows-x64"
if package.exists():
    raise SystemExit("Package directory already exists; choose a fresh build directory.")
shutil.copytree(dist/"EVPlayerUnlockerCLI", package)
shutil.copy2(dist/"EVPlayer Unlocker"/"EVPlayer Unlocker.exe", package)
shutil.copy2(ROOT/"README.md", package)
shutil.copy2(ROOT/"LICENSE", package)
shutil.copytree(ROOT/"docs", package/"docs")
licenses = package/"licenses"; licenses.mkdir()
python_license = Path(sys.base_prefix)/"LICENSE.txt"
if not python_license.exists():
    raise RuntimeError("Python license missing")
shutil.copy2(python_license, licenses/"Python-LICENSE.txt")
for distribution in ["pycryptodome", "pyinstaller"]:
    metadata = importlib.metadata.distribution(distribution)
    copied = 0
    for member in metadata.files or []:
        if member.name.lower().startswith(("license", "copying")):
            source = Path(metadata.locate_file(member))
            if source.is_file():
                shutil.copy2(source, licenses/(distribution+"-"+source.name)); copied += 1
    if not copied:
        raise RuntimeError("Missing third-party license: "+distribution)
for source in (Path(sys.base_prefix)/"tcl").rglob("license.terms"):
    shutil.copy2(source, licenses/(source.parent.name+"-license.terms"))
shutil.copytree(runtime/"LICENSE", licenses/"innoextract") if (runtime/"LICENSE").is_dir() else None
# All runtime licenses remain available in _internal/runtime/innoextract/ as well.
build_info = {"version": VERSION, "python": sys.version.split()[0],
              "dependencies": {name: importlib.metadata.version(name) for name in ["pycryptodome", "pyinstaller"]},
              "player_components_included": False, "course_data_included": False}
(package/"build-info.json").write_text(json.dumps(build_info, indent=2), encoding="utf-8")
(package/"使用说明.txt").write_text("双击 EVPlayer Unlocker.exe 打开界面。\n请先在 EVPlayer 3.4.9.1 正常播放同一课程。\n如遇拒绝访问，请右键以管理员身份运行。\n安装包检查为可选功能，不会运行安装程序。\n详细说明见 README.md。\n", encoding="utf-8-sig")
subprocess.run([str(package/"EVPlayerUnlockerCLI.exe"), "self-test"], check=True)
for file in package.rglob("*"):
    if file.is_file() and (file.suffix.lower() in {".ev4a", ".mp4", ".partial"} or file.name.lower() in {"playerlibrender56_vs.dll", "evplayer.exe", "windows.exe"}):
        raise RuntimeError("Unexpected private or proprietary payload: "+file.name)
archive = Path(shutil.make_archive(str(package), "zip", root_dir=dist, base_dir=package.name))
with archive.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
(dist/"SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
print(json.dumps({"archive": str(archive), "sha256": digest}, ensure_ascii=True))
