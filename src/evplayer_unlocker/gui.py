"""Small Tk front end. Worker results cross into Tk only through a queue."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from . import __version__

class App:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        root.title(f"EVPlayer Unlocker {__version__}")
        root.geometry("760x540")
        root.minsize(640, 480)
        outer = ttk.Frame(root, padding=18); outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="EVPlayer 视频导出", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(outer, text="先在 EVPlayer 3.4.9.1 中正常播放同一课程，再选择视频导出。", wraplength=690).pack(anchor="w", pady=(8, 14))
        row = ttk.Frame(outer); row.pack(fill="x")
        self.buttons = []
        for label, action in [("检查安装包", self.installer), ("选择视频", self.select_files), ("选择文件夹", self.select_folder)]:
            button = ttk.Button(row, text=label, command=action); button.pack(side="left", padx=(0, 8)); self.buttons.append(button)
        self.selection = tk.StringVar(value="尚未选择视频")
        ttk.Label(outer, textvariable=self.selection, wraplength=690).pack(anchor="w", pady=12)
        self.output = tk.StringVar()
        self.ffmpeg = tk.StringVar()
        for label, value, action in [("输出文件夹", self.output, self.select_output), ("FFmpeg（可选）", self.ffmpeg, self.select_ffmpeg)]:
            frame = ttk.Frame(outer); frame.pack(fill="x", pady=4)
            ttk.Label(frame, text=label, width=16).pack(side="left")
            entry = ttk.Entry(frame, textvariable=value); entry.pack(side="left", fill="x", expand=True)
            button = ttk.Button(frame, text="选择", command=action); button.pack(side="right", padx=(8, 0)); self.buttons.extend([entry, button])
        ttk.Label(outer, text="原文件保留，不覆盖同名结果。选择 FFmpeg 后会额外完整验证音视频。", wraplength=690).pack(anchor="w", pady=(8, 8))
        self.bar = ttk.Progressbar(outer, maximum=100); self.bar.pack(fill="x", pady=(0, 10))
        self.log = ScrolledText(outer, height=9, state="disabled", font=("Microsoft YaHei UI", 9)); self.log.pack(fill="both", expand=True)
        row = ttk.Frame(outer); row.pack(fill="x", pady=(12, 0))
        self.start_button = ttk.Button(row, text="开始导出", command=self.start); self.start_button.pack(side="left"); self.buttons.append(self.start_button)
        self.cancel_button = ttk.Button(row, text="停止", command=self.stop.set, state="disabled"); self.cancel_button.pack(side="left", padx=8)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.drain)

    def select_files(self):
        names = filedialog.askopenfilenames(title="选择 EV4A 视频", filetypes=[("EV4A 视频", "*.ev4a")])
        if names:
            self.files = list(names); self.selection.set(f"已选择 {len(names)} 个视频")
            if not self.output.get(): self.output.set(str(Path(names[0]).parent/"MP4导出"))

    def select_folder(self):
        name = filedialog.askdirectory(title="选择课程文件夹")
        if name:
            self.files = [name]; self.selection.set(name)
            if not self.output.get(): self.output.set(str(Path(name).parent/(Path(name).name+"_MP4")))

    def select_output(self):
        name = filedialog.askdirectory(title="选择输出文件夹")
        if name: self.output.set(name)

    def select_ffmpeg(self):
        name = filedialog.askopenfilename(title="选择 ffmpeg.exe", filetypes=[("FFmpeg", "ffmpeg*.exe")])
        if name: self.ffmpeg.set(name)

    def launch(self, action):
        self.busy = True; self.stop.clear()
        for button in self.buttons: button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        def work():
            try: action()
            except Exception as error: self.events.put(("log", "失败："+str(error)))
            finally: self.events.put(("done", None))
        threading.Thread(target=work, daemon=True).start()

    def installer(self):
        name = filedialog.askopenfilename(title="选择 EVPlayer Windows 安装包", filetypes=[("Windows 安装包", "*.exe")])
        if name:
            def action():
                from .inspect import inspect_installer
                result = inspect_installer(name)
                self.events.put(("log", "安装包检查通过：EVPlayer "+result["version"]+"。没有运行安装程序。"))
            self.launch(action)

    def start(self):
        if not self.files or not self.output.get().strip():
            messagebox.showinfo("请选择文件", "请先选择视频和输出文件夹。", parent=self.root); return
        inputs = list(self.files); destination = self.output.get(); ffmpeg = self.ffmpeg.get().strip() or None
        def action():
            from .runner import export_batch
            results = export_batch(inputs, destination, ffmpeg=ffmpeg, notify=lambda msg:self.events.put(("log",msg)), progress=lambda done,total:self.events.put(("progress",100*done/max(1,total))), cancelled=self.stop.is_set)
            passed = sum(r["success"] for r in results)
            self.events.put(("log", f"{'已停止' if self.stop.is_set() else '处理结束'}：成功 {passed} 个，失败 {len(results)-passed} 个。"))
        self.launch(action)

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal"); self.log.insert("end", value+"\n"); self.log.see("end"); self.log.configure(state="disabled")
                elif kind == "progress": self.bar["value"] = value
                elif kind == "done":
                    self.busy = False
                    for button in self.buttons: button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
        except queue.Empty: pass
        self.root.after(100, self.drain)

    def close(self):
        if self.busy:
            self.stop.set()
            self.events.put(("log", "正在停止，请等待当前操作结束后再关闭。"))
        else: self.root.destroy()

def main():
    root = tk.Tk(); App(root); root.mainloop()
