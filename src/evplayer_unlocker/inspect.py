from pathlib import Path
import os
import subprocess
import sys
import tempfile
from .core import ExportError
from .windows import check_engine, ENGINE_NAME

def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))

def inspect_installer(path, extractor=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise ExportError("请选择 EVPlayer 的 Windows 安装包。")
    executable = Path(extractor) if extractor else resource_root()/"runtime/innoextract/innoextract.exe"
    if not executable.is_file():
        raise ExportError("缺少 innoextract；请完整解压发行包，或从源码执行 scripts/fetch-runtime.py。")
    with tempfile.TemporaryDirectory(prefix="evplayer-installer-") as temporary:
        args = [str(executable.resolve()), "--extract", "--silent", "--include", str(Path("app")/ENGINE_NAME), "--output-dir", temporary, str(path)]
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            raise ExportError("安装包解析失败：不是支持的 Inno Setup 安装包，或文件不完整。")
        candidate = Path(temporary)/"app"/ENGINE_NAME
        if not candidate.is_file():
            raise ExportError("安装包缺少预期的播放器组件。")
        report = check_engine(candidate)
        report["installer_executed"] = False
        return report

def inspect_video(path):
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(64)
    return {"name": path.name, "bytes": path.stat().st_size,
            "ordinary_mp4_header": header[4:8] == b"ftyp",
            "ev4a_extension": path.suffix.lower() == ".ev4a",
            "note": "扩展名不能证明兼容性；导出前还需用当前播放参数验证文件头。"}
