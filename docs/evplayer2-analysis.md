# EVPlayer2 5.0.4 x64：架构分析与实验适配

分析日期：2026-10-10。关联 [issue #1](https://github.com/wjtianze/evplayer-unlocker/issues/1)。

## 结论与当前交付

已从厂商官网下载并静态解包 EVPlayer2 5.0.4 Windows 64 位安装包，解开主程序的 UPX 压缩，定位核心 DLL 内的多套解密器，并实现 EV5/EV6/EV7 的实验导出脚本。三者共用一个 AES-256 读取实现，与旧项目的 V4A 分块派生密钥算法不同。

**这不是已经过真实课程验收的通用解密器。** 已验证原生 AES、调度表及读取函数，与合成 MP4 导出；尚未验证实际 Windows 进程读取、真实课程封装和授权播放后的完整导出。当前运行环境为 Linux，issue 没有提供真实样本，且填写“原 EVPlayer 不能正常播放”。其含义可能是用错了播放器，也可能是授权或文件问题，现有证据不能区分。

脚本依赖已正常播放的 EVPlayer2 提供有效解密上下文。下载公共安装包本身不能证明能得到某个课程的有效参数。若对应视频在 EVPlayer2 中也不能播放，目前脚本无法完成导出。

## 官方来源与构建指纹

- [官方产品页](https://www.ieway.cn/evplayer2.html)：本次访问列出 Windows 64 位和 32 位 5.0.4；官方描述包含账号登录、后台授权、首次播放设备绑定。
- [本次下载的 Windows 64 位安装包](https://ctpublic.ieway.cn/public/download/EVPlayer2_v5.0.4.exe)。
- 安装包格式：Inno Setup 5.5.7 Unicode；实际解包显示产品名称 `EVPlayer2 5.0.4`。
- 分析全程没有安装或在宿主系统启动 EVPlayer2；原生密码运算在 Unicorn 中执行，没有连接厂商服务器。

| 文件 | SHA-256 |
| --- | --- |
| EVPlayer2_v5.0.4.exe（安装包） | `51a574283817484045e3f4d16086b637b4db19a2a3ecfdc8603579d55725f441` |
| EVPlayer2.exe（解包后的原始主程序） | `ba7722a37c9fcb56fca7b9f117db7faa27a1194aefe93986a04c81ed17ecaac7` |
| PlayerLibRender56_vs.dll | `9997bfab88148ce1c90c031d353d9d15611f2f6733a7956cec76221971a9897a` |
| MetaLib.dll | `199f7522b870df705d7807604453edc3c43d303b761fdd95be4fa452b4f876b1` |
| Bridge.dll | `930981c46e5f0173268d84e35ef6c63940002900787329fd74897b50810acf81` |

安装器自身是 32 位 PE，不代表它所安装的程序是 32 位。此安装包中的主程序及上述三个 DLL 均为 AMD64 / PE32+。实验脚本只接受上述播放核心指纹，同版本号的其它构建也会拒绝。

## 组件关系

| 层次 | 直接观察到的证据 | 作用或判断 |
| --- | --- | --- |
| 主程序 EVPlayer2.exe | UPX0/UPX1 段；解压后有 Qt 依赖、课程数据类、播放地址获取和授权相关字符串 | 用户界面、课程列表、服务端交互；具体授权协议未完整逆向 |
| PlayerLibRender56_vs.dll | Qt、音视频和网络库导入；`ev::EVPlayer` 导出；FFmpeg 4.2.9 字符串；解密器 RTTI | 媒体读取、解密、解码及呈现核心 |
| MetaLib.dll | `ml::ReadMeta::readfile`、`unPacketCer` 导出和 `MetaReader` 类型 | 元数据及证书处理辅助组件；没有证明所有格式都走此 DLL |
| Bridge.dll | 配置、实例注册、命名管道及授权相关导出 | 组件桥接、配置和通信设施 |
| 运行依赖 | Qt5Core/Gui/Widgets/Network/Multimedia、SDL2、nghttp2 等 | 桌面界面、音视频和网络支撑 |

解压后的主程序含 EV5、EV6、EVS 播放地址获取失败日志，以及 EVS 下载密钥和签名地址相关路由字符串。这是程序包含相应路径的静态证据，不代表已验证网络协议、密钥生命周期或服务端实现。本实验导出脚本不调用这些网络接口。

核心 DLL 含以下解密器 RTTI。发现类型仅证明二进制中存在相应实现，不保证任一扩展名对应它，也不保证能处理所有文件。

| 类名 | 虚函数表 RVA | 本次适配 |
| --- | --- | --- |
| Decryptor_EV4 | `0x802168` | 未适配 |
| Decryptor_V4A | `0x8022c0` | 此 64 位构建未适配 |
| Decryptor_EV5 | `0x801108` | 实验适配 |
| Decryptor_EV6 | `0x801190` | 实验适配 |
| Decryptor_EV7 | `0x801200` | 实验适配 |
| Decryptor_EVS | `0x802d80` | 未适配 |
| Decryptor_V8A | `0x801420` | 未适配 |
| Decryptor_V3A | `0x802cd0` | 未适配 |

RVA 是相对于已加载核心 DLL 的偏移，脚本加上实际模块基址处理地址随机化；没有将静态首选加载地址写死为运行时地址。完整 RTTI 和虚函数表结果见 [player2-decryptor-tables.json](verification/player2-decryptor-tables.json)。

## EV5/EV6/EV7 的密码运算

### 原生函数证据

| 功能 | RVA | 观察结果 |
| --- | --- | --- |
| EV5 初始化 | `0x1a770` | 从传入数据处理后取得参数，调用 AES 初始化，分配两个 256 KiB 缓冲区 |
| EV6/EV7 初始化 | `0x1b020` → `0x1a5d0` | 使用传入参数调用 AES 初始化，同样分配缓冲区 |
| 三者共用读取函数 | `0x1acf0` | 读入密文，按 16 字节对齐，调用 AES，复制解密输出，并处理残留数据 |
| AES 初始化 | `0x20c90` | 适配路径传入 256 位及解密标记 1 |
| AES 调用包装 | `0x20c70` | 从上下文读取轮数和函数指针后跳转 |
| AES 解密实现 | `0x20110` | 本次无 IV 的调用路径与 AES-ECB 一致；用原生执行验证 |

旧工具使用 V4A 的 master/operations 按块派生不同密钥。本次 EV5/6/7 的读取路径直接使用已经初始化的固定 AES 上下文，没有观察到每个 256 KiB 块重新派生密钥。256 KiB 是读缓冲区上限，AES 块大小仍为 16 字节。

### 密钥还原的关键细节

不能直接把上下文开头 32 字节当作 AES-256 原始密钥。原生解密初始化保留第一个 16 字节，随后对内部轮密钥执行逆列混合；原始密钥的后 16 字节也经过此变换。

脚本保留前 16 字节，对后 16 字节执行正向列混合，还原 32 字节原始密钥；再重新生成全部 240 字节解密调度表，与原对象逐字节比较。只有整个调度表一致，才接受该对象。该过程已与官方 DLL 原生初始化结果对照。

对象布局证据及实现使用的偏移：

| 相对对象偏移 | 字段 |
| --- | --- |
| `0x000` | 64 位虚函数表指针 |
| `0x008` | AES 上下文起点；前 240 字节为调度表 |
| `0x118` | AES 轮数，适配路径为 14 |
| `0x120` | 原生 AES 解密函数指针 |
| `0x128`、`0x130` | 输入和输出缓冲区指针 |
| `0x138` | 跳过的非对齐字节数 |
| `0x364` | 残留字节数 |
| 对象大小 `0x368` | 从原生析构路径及字段访问得到 |

脚本核对核心文件指纹，再只读扫描指定 EVPlayer2 的可读私有内存。匹配虚函数表、轮数、函数指针、缓冲区指针及完整调度表，并要求关键部分在连续两次读取间稳定。参数不写入报告或日志。

## 使用方法

条件：64 位 Windows，64 位 Python 3.11+；EVPlayer2 5.0.4 的上述 64 位构建；对应视频已经正常授权播放。先解压此研究分支源码，在源码根目录执行：

```powershell
python -m pip install -e .
python scripts\evplayer2-decrypt.py "D:\课程\示例.ev5" --out-dir "D:\导出"
```

文件夹批处理、多个播放器实例和可选完整音视频解码验证：

```powershell
python -m evplayer_unlocker.cli export-player2 "D:\课程" --out-dir "D:\导出" --pid 1234 --ffmpeg "C:\Tools\ffmpeg.exe"
```

若 Windows 明确拒绝进程读取，可用与播放器相同的权限运行工具。图形界面尚未接入实验适配。未选择 FFmpeg 时仅验证 MP4 顶层结构，不表示已经验证全片声音和画面。

安装包检查不需要启动播放器：

```powershell
python scripts\fetch-runtime.py
python -m evplayer_unlocker.cli inspect-player2-installer "C:\Downloads\EVPlayer2_v5.0.4.exe"
```

## 可复现验证

### 原生 DLL 对照

安装研究用依赖，提供自己从官方安装包解出的核心 DLL：

```powershell
python -m pip install pefile==2024.8.26 unicorn==2.1.4
python scripts\verify-player2-native.py "C:\分析\PlayerLibRender56_vs.dll"
```

验证脚本把核心 DLL 映射到 Unicorn 中，执行未修改的 AES 初始化和解密指令，仅模拟 `memcpy` 和栈保护辅助函数；读取函数测试另模拟一个从位置零读合成密文的流对象。未安装 DLL，不执行 DLL 入口，不启动播放器，不调用服务器接口。

- AES-128/192/256 各 5 组，共 15 组公开合成向量，原生解密结果与 PyCryptodome 一致。
- 5 组 AES-256 的完整 240 字节调度表及恢复密钥均与原生结果一致。
- 直接执行 EV5/6/7 共用读取函数，对 33,024 字节合成数据分 9 次读取，逐字节还原一致。
- 这没有覆盖原生读取函数的所有 seek、残留、错误及并发路径，也没有验证 Windows 进程扫描。

保存的原生验证结果见 [player2-native.json](verification/player2-native.json)。

### Python 回归及合成音视频

```powershell
python -m unittest discover -s tests -v
```

25 项回归测试通过，涵盖旧版功能及新增的调度表还原、错误对象拒绝、64 位地址随机化、EV6/EV7 对象识别、大小写扩展名、多块固定密钥导出和原文件保留。

另用 FFmpeg 创建包含测试图和正弦音轨的两秒普通 MP4，以公开测试密钥进行 AES-ECB 加密后，用新增路径还原：输出与原 MP4 逐字节一致，并通过完整音视频解码。见 [player2-synthetic-roundtrip.json](verification/player2-synthetic-roundtrip.json)。这仅证明合成封装的还原正确，不能作为真实 EVPlayer2 课程验证。

## 未解决项与样本需求

1. 未在真实 Windows EVPlayer2 进程上验收扫描器。
2. 未确认真实课程密文是否总从物理文件位置零开始、是否有额外容器头，以及尾部元数据和补齐规则。本实现仅接受能以当前参数还原出 `ftyp` 开头且形成完整顶层 MP4 结构的候选文件；文件尾沿用旧工具的有限清理策略，并非已解析 EV5 专用尾部格式。
3. 未适配 EVS、64 位 V4A、V8A、非 MP4 内层、32 位 EVPlayer2 或其它核心指纹。
4. 若未正常播放，现有方案不能凭公共安装包取得有效课程参数；它不是授权、激活或到期处理工具。
5. issue #1 尚无样本、精确版本及错误信息，因此不应关闭该 issue 或宣称修复完成。

下一步需要精确播放器版本和位数、实际扩展名、能否在 **EVPlayer2** 中正常播放、具体错误，以及一段允许用于测试的短视频或自制加密样本。无需提供账号密码、激活码、私有播放参数或完整进程内存。

## 第三方及分发范围

使用 Innoextract 1.9 解包、UPX 5.2.1 解压主程序，pefile/Capstone 读取和反汇编 PE，Unicorn 做原生运算对照，PyCryptodome 实现独立密码运算，FFmpeg 检查合成音视频。仓库仅包含研究代码、测试、元数据和报告，不包含厂商安装包、专有 DLL、课程、私有授权数据或第三方工具二进制。
