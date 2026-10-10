# EVPlayer Unlocker

**EVPlayer 加密视频导出工具**

把已获授权、能够在 EVPlayer 中正常播放的 `.ev4a` 视频导出为普通 MP4，用自己习惯的播放器观看和离线学习。直接还原音视频数据，不通过录屏，也不重新压制。

[下载 Windows 版](https://github.com/wjtianze/evplayer-unlocker/releases/latest) · [反馈问题](https://github.com/wjtianze/evplayer-unlocker/issues)

## 怎么用

1. 下载 Releases 中的 Windows 压缩包，完整解压。
2. 使用自己的 EVPlayer **3.4.9.1** 正常打开并播放同一课程的一段视频，保持播放器运行。
3. 双击 **EVPlayer Unlocker.exe**。如果提示 Windows 拒绝读取播放器，请关闭工具，右键选择“以管理员身份运行”。
4. 点击“选择视频”或“选择文件夹”，设置输出文件夹，再点击“开始导出”。支持多选和递归批量处理。
5. 生成的 MP4 保留原有名称与目录关系，原文件保留，同名结果不会被覆盖。

压缩包包含运行环境和安装包解析器，无需另外安装 Python 或解包软件。转换在后台以低优先级运行，可以停止；工具不会操作原播放器的窗口。

### 安装包检查

点击“检查安装包”，选择自己取得的 EVPlayer Windows 安装包，例如 `Windows.exe`。工具会解析 Inno Setup 安装包、提取所需组件到临时目录，并检查 SHA-256 指纹。检查结束后删除临时组件，不运行安装程序。

这一步用于确认安装包是否属于已适配版本。已经安装并正常播放的用户可以直接导出。

**安装包本身不提供课程的播放授权。** 本工具仍需要原播放器已正常授权播放时的参数，不能只凭安装包和未获授权的视频完成转换，也不负责激活、续期或登录。

### 转换验证

每个输出都检查 MP4 容器结构。可在界面中选择自己安装的 `ffmpeg.exe`，额外从头到尾验证画面和音轨；未选择 FFmpeg 时，程序会明确标注“MP4 结构已验证”，不会声称完成了全片解码检查。

本项目不捆绑 FFmpeg。可从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html) 获取 Windows 构建。完整验证已在 FFmpeg 7.1 上测试。

## 支持哪些文件？

目前仅适配 **Windows x64 上运行的 EVPlayer 3.4.9.1 特定构建、V4A 模式 110、内部为 MP4 的文件**。匹配以组件 SHA-256 为准，同样的版本号不一定代表相同构建。

### EVPlayer2 实验适配（命令行）

此研究分支新增 **EVPlayer2 5.0.4 Windows 64 位特定构建的 EV5/EV6/EV7 实验导出**，使用独立命令，图形界面仍使用原有适配。

已完成官方 DLL 的原生 AES、完整密钥调度表、EV5/6/EV7 读取函数的仿真对照，以及合成 MP4 的逐字节还原与完整音视频解码。**尚未用真实 EVPlayer2 课程验证 Windows 进程读取、文件封装及最终导出，不能视为已解决 issue #1。** EVS、V4A、V8A 与其它构建暂不支持；视频须在 EVPlayer2 中已正常授权播放。

从源码运行（64 位 Windows，64 位 Python 3.11+）：

```powershell
python -m pip install -e .
python scripts\evplayer2-decrypt.py "D:\课程\示例.ev5" --out-dir "D:\导出"
python -m evplayer_unlocker.cli export-player2 "D:\课程" --out-dir "D:\导出" --ffmpeg "C:\Tools\ffmpeg.exe"
```

可选安装包检查：先运行 `python scripts\fetch-runtime.py`，再运行 `python -m evplayer_unlocker.cli inspect-player2-installer "C:\Downloads\EVPlayer2_v5.0.4.exe"`。检查只解包和核对指纹，不启动安装程序。

详见[EVPlayer2 架构、逆向证据及验证边界](docs/evplayer2-analysis.md)。实验参数仅保存在进程内存；不修改播放器，不自动登录或申请授权。未知构建、无有效参数及不匹配的文件头均停止处理。

开发期间用一组 34 个已授权视频验证了导出算法，总时长约 16 小时 12 分钟，全部通过完整音视频解码检查。这不是对所有 EV4A 文件的兼容承诺。

上述稳定适配尚不支持其他 EVPlayer 版本、EV4/EV5/EV6/EVS、非 MP4 内部格式及不同加密模式；EVPlayer2 的 EV5/EV6/EV7 仅通过前述独立实验命令处理。不同课程的播放参数可能不同：如果提示不匹配，请在原播放器中播放对应课程后重试。详见[兼容性与验证范围](docs/compatibility.md)。

## 隐私与原文件

播放参数只保存在本工具进程的内存中，不输出到日志、配置文件或转换记录，不上传到网络。本工具仅对指定 EVPlayer 进程进行只读检查，不注入代码、不修改播放器或防截屏设置。

仓库与发行包均不包含课程视频、激活码、播放参数、EVPlayer 安装包或专有播放器组件。请仅处理你有权导出的内容，并遵守适用的授权约定。

## 命令行与源码

Windows 发行包包含单独的命令行入口：

```powershell
.\EVPlayerUnlockerCLI.exe inspect-installer "C:\Downloads\Windows.exe"
.\EVPlayerUnlockerCLI.exe inspect "D:\课程\课程1.ev4a"
.\EVPlayerUnlockerCLI.exe export "D:\课程" --out-dir "D:\课程_MP4"
.\EVPlayerUnlockerCLI.exe export "D:\课程\课程1.ev4a" --out-dir "D:\导出" --ffmpeg "C:\Tools\ffmpeg.exe"
.\EVPlayerUnlockerCLI.exe self-test
```

从源码运行需要 64 位 Python 3.11 或更新版本；读取播放器需要 Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts\fetch-runtime.py
.\.venv\Scripts\python.exe -m evplayer_unlocker.cli
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

构建 Windows 发行包：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts\build.py
```

`fetch-runtime.py` 从 innoextract 官方 Release 下载固定版本并验证 SHA-256。构建输出位于 `dist/`。

## 反馈与适配

请在 Issues 提供工具版本、Windows 版本、EVPlayer 版本、错误提示，以及该文件能否在原播放器中正常播放。不要上传课程全文、激活码、播放参数或进程内存。未知构建会停止处理，避免错误导出。

## 许可

项目源码采用 MIT 许可证。发行包附有 Python、PyCryptodome、innoextract 及其依赖的许可说明。EVPlayer 属于其原权利人；本项目与其没有隶属或背书关系。
