import argparse
import json
import sys
from . import __version__
from .core import ExportError

def main():
    parser = argparse.ArgumentParser(description="EVPlayer Unlocker：将已授权播放的 V4A 视频导出为 MP4")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    exp = sub.add_parser("export", help="批量导出视频或文件夹")
    exp.add_argument("inputs", nargs="+")
    exp.add_argument("--out-dir", required=True)
    exp.add_argument("--pid", type=int)
    exp.add_argument("--ffmpeg", help="可选：完整解码验证所用的 ffmpeg.exe")
    ins = sub.add_parser("inspect-installer", help="解析安装包并核对版本，不运行安装程序")
    ins.add_argument("path")
    ins.add_argument("--extractor", help=argparse.SUPPRESS)
    vid = sub.add_parser("inspect", help="查看视频格式候选信息")
    vid.add_argument("path")
    sub.add_parser("self-test", help="运行不需要播放器的合成数据自检")
    args = parser.parse_args()
    try:
        if args.command is None:
            from .gui import main as gui_main
            gui_main()
            return 0
        if args.command == "export":
            from .runner import export_batch
            results = export_batch(args.inputs, args.out_dir, args.pid, args.ffmpeg, notify=lambda msg: print(msg, flush=True))
            return 0 if results and all(r["success"] for r in results) else 1
        if args.command == "inspect-installer":
            from .inspect import inspect_installer
            print(json.dumps(inspect_installer(args.path, args.extractor), ensure_ascii=False, indent=2))
        elif args.command == "inspect":
            from .inspect import inspect_video
            print(json.dumps(inspect_video(args.path), ensure_ascii=False, indent=2))
        elif args.command == "self-test":
            from .selftest import run
            run(); print("Self-test passed")
        return 0
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
    except (ExportError, OSError, ValueError) as error:
        print("失败：" + str(error), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
