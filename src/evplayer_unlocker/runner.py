from pathlib import Path
import json
import os
import subprocess
import tempfile
from .core import ExportError, Cancelled, choose_session, convert
from .windows import sessions, low_priority

def collect(inputs):
    files = []
    for name in inputs:
        path = Path(name).resolve()
        if not path.exists():
            raise ExportError("输入路径不存在。")
        candidates = sorted(path.rglob("*.ev4a")) if path.is_dir() else [path]
        files.extend(p for p in candidates if p.is_file() and not p.is_symlink() and p.suffix.lower() == ".ev4a")
    files = list(dict.fromkeys(files))
    if not files:
        raise ExportError("没有找到 .ev4a 文件。")
    return files

def verify(path, ffmpeg, cancelled):
    with tempfile.TemporaryFile() as log:
        args = [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-threads", "2", "-xerror", "-err_detect", "explode", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-enc_time_base:v", "-1", "-fps_mode:v", "passthrough", "-threads", "2", "-f", "null", "-"]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            while True:
                try:
                    code = process.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancelled():
                        raise Cancelled("验证已取消；已转换的文件仍保留。")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        log.seek(0)
        errors = log.read(65536)
        if code != 0 or errors.strip():
            raise ExportError("完整解码验证未通过；请检查文件，勿将其视为已验证结果。")
    return True

def export_batch(inputs, output, pid=None, ffmpeg=None, notify=lambda message: None,
                 progress=lambda done, total: None, cancelled=lambda: False):
    files = collect(inputs)
    output = Path(output).resolve()
    if output.exists() and not output.is_dir():
        raise ExportError("输出位置必须是文件夹。")
    if ffmpeg is not None and not Path(ffmpeg).is_file():
        raise ExportError("指定的 FFmpeg 不存在。")
    low_priority()
    notify("正在检查已授权播放的 EVPlayer……")
    keys = sessions(pid, cancelled)
    common = Path(os.path.commonpath([str(p.parent) for p in files]))
    results = []
    for index, source in enumerate(files, 1):
        if cancelled():
            break
        destination = output/source.relative_to(common).with_suffix(".mp4")
        notify(f"[{index}/{len(files)}] {source.name}")
        try:
            key = choose_session(source, keys)
            result = convert(source, destination, key, progress, cancelled)
            result["output"] = str(destination.relative_to(output))
            result["full_decode_verified"] = False
            if ffmpeg:
                notify("正在完整验证画面和音轨……")
                result["full_decode_verified"] = verify(destination, ffmpeg, cancelled)
            result["success"] = True
            notify("完成（完整解码已验证）" if ffmpeg else "完成（MP4 结构已验证）")
        except Cancelled:
            notify("已停止，原文件和已完成结果保留。")
            break
        except (ExportError, OSError) as error:
            result = {"name": source.name, "success": False, "error": str(error)}
            notify("失败：" + str(error))
        results.append(result)
    if results:
        output.mkdir(parents=True, exist_ok=True)
        # Never overwrite a previous run's report.
        report = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="转换记录-", suffix=".json", dir=output, delete=False)
        with report:
            json.dump({"expected": len(files), "processed": len(results), "files": results}, report, ensure_ascii=False, indent=2)
    return results
