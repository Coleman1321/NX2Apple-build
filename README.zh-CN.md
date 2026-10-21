# nxnative + RomFS 归档

在 iPhone 和 iPad 上原生运行你自己的 Switch 游戏 —— 并让那些资源文件太大（或太多）的游戏也能装上。

本仓库是 **[nxnative](https://github.com/seedds/nxnative) 加了一个新子系统：RomFS 归档**。运行游戏的一切
—— NSO 重写器、Horizon 宿主层、NVN-on-Metal、各游戏的 profile —— 都是上游的工作。新增的是把一棵
RomFS 目录树打包成约 100 个文件、并让 App 直接读取的能力，这让大体积游戏可以安装，也让游戏文件一次即可拷完。

[English](README.md) | 简体中文

---

## 问题

《王国之泪》这样的 RomFS 是 **304,243 个文件 / 15.9 GiB**。这会带来两个故障：

- **IPA 装不上。** 一个 16.6 GB、含 372,660 个条目的包在 iOS 上直接失败，报
  `PackageExtractionFailed (Could not extract archive)`。安装守护进程的解压器放弃了 ——
  单个目录里有 75,941 个文件，ZIP64 中央目录的偏移从 17.8 GB 开始。
- **把目录树拷进手机要几小时。** 「文件」App 和 Finder 都是每个文件一次往返。30 万个小文件
  还会额外产生约 1 GB 的文件系统块开销。

把目录树打成约 100 个分片文件可以同时解决两者：包保持很小，游戏文件作为一个大文件夹一次拷完。

## 做法

一种 **ROMFSARC** 归档：一个索引文件加 N 个分片文件。

```
romfs.idx        28 MB   头部、名称池、文件表、目录表
romfs.00 ... .125        126 个分片，每片 200 MiB，源文件字节原样
```

在《王国之泪》（v1.0.0 + 1.4.3）上的实测：

| | 原始 RomFS | ROMFSARC |
|---|---|---|
| 文件数 | 304,243 | **127** |
| 最大的目录 | 75,941 个条目 | 126 个分片，均不超过 200 MiB |
| 含游戏的 IPA | 16.6 GB（装不上） | — |
| 瘦身 IPA（默认，不含 RomFS） | — | **743 MB，可安装** |
| 拷到手机 | 数小时 | 一个含 127 个文件的文件夹 |

路径查找是对排序后的文件表做二分查找；目录枚举只遍历一段连续的子项区间。索引用 `mmap` 映射，
分片按需打开，读取直接在分片上 `pread`，所以页缓存照常生效。

## 图形界面

`frontend/` 是一个 macOS App，用窗口代替终端完成下面第 2–5 步，给不想读构建日志的人用：四项输入
分开选（本体、更新包、DLC、`prod.keys`）、依赖面板自动检测并一键安装缺失项、直接显示脚本自己的
阶段列表和实时百分比、最后自动产出归档分片。

<details>
<summary>界面截图（点开）</summary>

<img src="frontend/screenshots/main-window.png" width="620" alt="NS Port Builder">

</details>

```bash
cd frontend && swift run          # 或直接双击 frontend/NS Port Builder.app
```

它调用的就是命令行那套脚本，下面的说明全部适用；细节见
[frontend/README.md](frontend/README.md)。打包好的 App 和英中双语发布说明（含已验证游戏清单）在
[Releases 页面](https://github.com/LNPANDY/nxnative-romfs-archive/releases)，仓库内也存了一份：
[docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)。

## 使用方法

### 1. 构建 App（与上游相同）

归档功能不改变正常构建流程。按上游的 [README](https://github.com/seedds/nxnative) 安装 Xcode、
Homebrew 工具和 Python 包，然后打 IPA。

```bash
git clone https://github.com/<you>/nxnative-romfs-archive.git
cd nxnative-romfs-archive
brew install xcodegen zstd spirv-cross
brew install --cask dotnet-sdk
python3 -m pip install lz4 capstone fonttools backports.zstd
```

`backports.zstd` 是《王国之泪》的 zstd 字典需要的；其他游戏用不到。

### 2. 你需要准备的文件

三样东西，仓库里都不带：

| 内容 | 来源 | 用途 |
|---|---|---|
| **`prod.keys`** | 从**你自己的机器**导出（见下） | 解密你的游戏 |
| **游戏的 NSP** | 从你自己的卡带或 eShop 购买记录导出 | 供解包 |
| **Xcode + iOS SDK** | App Store | 构建 App |

`prod.keys` 是主机的密钥集——一个 `名字 = 十六进制值` 格式的文本文件（约 230 条：
`master_key_xx`、`titlekek_xx`、`header_key`、`key_area_key_application_xx`……）。所有 Switch
自制软件工具都读这个格式。它**不和某个游戏绑定**：一份 `prod.keys` 能解你所有的游戏。唯一
要求是文件里包含游戏打包时代（固件世代）对应的密钥——新导出的一份覆盖所有零售游戏。

放在哪里随意，用 `-k` 传路径即可：

```bash
# 任意布局，比如
~/keys/prod.keys
# 或者就放在游戏 NSP 旁边
~/Games/Hades2/prod.keys
```

```bash
python3 scripts/build_ipa_from_nsp.py ~/Games/Hades2 -k ~/keys/prod.keys
```

密钥的导出方式在 Switch 自制软件社区有完整文档（常见做法是在破解机上跑 Lockpick_RCM）；
本仓库不涉及也不携带这一步。两条来自真实导出文件的实用提示：

- **格式错误的行。** 有的导出工具会写出十六进制值长度不对的行（真实案例：33 行长度错误的
  `master_kek_source_*`），解包工具会因此拒绝整个文件。删掉这些行，原文件留个备份。
- **更新包。** 更新 NSP 的 ticket 可能带比本体更新的密钥世代。解包工具直接从每个 NSP 内部的
  common ticket 读 title key，所以实际使用中只要 `prod.keys` 不算太旧，两份都能解开——这里
  实测过本体是世代 15、更新是世代 16，keys 文件只到 15，两个包都正常解出。

### 3. 把 RomFS 打包成归档

```bash
python3 dm/tools/romfs_arc.py pack <RomFS 目录> <输出基路径> --shard-mib 200
```

`<RomFS 目录>` 是 `nx_extract` 解出来的那个目录（里面有 `Pack/`、`Banc/`、`Sound/` 等）。工具会写出
`<基路径>.idx` 和 `<基路径>.00`、`.01`……文件按顶层目录分组切分，每片不超过 `--shard-mib`，
所以一片里装的是一类内容。

拷贝之前先验证：

```bash
python3 dm/tools/romfs_arc.py verify <基路径> <RomFS 目录>   # 逐字节比对每个文件
python3 dm/tools/romfs_arc.py list   <基路径> [路径]          # 列出某个目录
```

### 4. 构建 IPA

主构建脚本**默认打瘦身 IPA**（不含 RomFS；App 从 `Documents/romfs` 读游戏文件），所以第 1 步
已经产出。以后只想重新打包时：

```bash
GAME=<title id> W=<工作目录> PATCHED=<改写目录> \
  ROMFS=<RomFS 目录> MSL_IOS=<shader 目录> \
  dm/ios/tools/build_ipa.sh <输出.ipa>
```

`--full-romfs`（或 `DM_FULL_ROMFS=1`）把 RomFS 打进包里——上游行为，只对小体量游戏有意义。

### 5. 把归档拷到手机

整套放进 App 的 `Documents/romfs/`，保持基名不变：

```
Documents/romfs/romfs.idx
Documents/romfs/romfs.00
...
Documents/romfs/romfs.125
```

App 会先找 `romfs.idx`（`dm/ios/Sources/main.m` 的 `romfs_locate`）。没有索引时会回退到普通目录树，
所以对已有游戏没有任何影响。

索引可以放在以下任一位置，读取层按顺序尝试：

```
<DM_ROMFS>.idx
<DM_ROMFS>/romfs.idx
<DM_ROMFS>/romfs/romfs.idx
```

## 游玩

**触屏操控。** 两种布局（点顶部中央的按钮切换）：2D（左摇杆、A/B/X/Y、肩键、−/+）和 3D
（增加十字键、右摇杆和 L3/R3）。未连接手柄时，触到控件以外的区域会送到游戏的触屏。

**实体手柄**（GameController 框架：Xbox、PlayStation、Switch Pro 和 MFi 手柄都支持）连接后
会完全隐藏触屏控件，断开时恢复；期间所有触摸都送到游戏的触屏。按键按位置映射，与 Switch
手柄一致：下=B、右=A、左=Y、上=X，十字键和右摇杆同样保留。

**不改包调设置：** `Documents/env.txt`，每行一个 `KEY=VALUE`。常用的：

```
DM_LANG=zh-Hans        # 中文（默认 en-US）
DM_FPS_TARGET=30       # 限帧（省电；默认用 profile 的 fps_target）
DM_OPMODE=0            # 掌机模式：720p 渲染而不是底座的 1080p
```

**存档和日志**在「文件」App 里该 App 名字下：`save/` 和 `log.txt`。出问题时把 `log.txt`
发出来（上一次运行的是 `log.prev.txt`）。新场景第一次出现时短促卡顿是正常的：App 会为它
编译一次图形并记住。

## 换其他游戏

归档格式里没有任何与具体游戏绑定的东西：打包工具遍历你给的目录，读取层在那棵树里查路径。换游戏只需要：

1. 用 `nx_extract` 解出新游戏的 NSP（上游脚本会自动做）。
2. 用 `romfs_arc.py` 打包那个游戏的 `RomFS`。
3. 用新的 `GAME=` profile 重新构建 IPA（默认即瘦身包）。
4. 把新归档拷进 `Documents/romfs/`。

三点需要注意：

- **分片数不能超过 256。** 读取层每个分片占一个 fd 槽位（`romfs_arc.h` 的 `MAX_SHARDS`）。
  打包工具现在会拒绝写出超限的索引，并告诉你该用多大的 `--shard-mib`。《王国之泪》按 200 MiB
  需要 126 片；体积约它两倍的游戏需要 256 MiB 一片。
- **DLC 不走归档。** 追加内容仍然打进包里（`DmIOS.app/aoc/<index>/`），按目录挂载。多数 DLC
  体积很小，不影响安装；如果又撞上安装上限，把 DLC 从包里去掉即可，代价是游戏里看不到那几个 DLC。
- **`zip_store` 是每个游戏各自的。** profile 里列出已经是压缩格式、应当直接存储而不做 deflate 的
  扩展名（《王国之泪》是 `.zs`、`.bwav`、`.mc`、`.webm`、`.metallib`）。这只影响装 shader 库和
  表的那个包，与归档无关。

上游测试列表里的游戏（4–6 GB）按 200 MiB 大概需要 20–30 片，远低于上限，内存占用也远低于
《王国之泪》撞上的那个单 App 预算。

## 相对上游的改动

新增 5 个文件，修改 4 个。文件系统层保留原有的路径处理：归档打开时，`host_path_ex` 对归档挂载点上的
条目返回一个合成路径（`@romfsarc:<guest 路径>`），`OpenFile` / `GetEntryType` / `OpenDirectory`
和目录相关调用识别该前缀并转到归档层。归档条目的文件句柄用 bit 63 标记，不会与真实 fd 冲突；
`ReadFile` 会按文件大小截断（分片是平铺容器，不截断的话越界读会读到下一个文件的字节）。

| 文件 | 改动 |
|---|---|
| `dm/host/romfs_arc.h` | 新增 —— 归档格式与读取接口 |
| `dm/host/romfs_arc.c` | 新增 —— mmap 索引、二分查找、按需打开分片 |
| `dm/tools/romfs_arc.py` | 新增 —— pack / verify / list |
| `dm/host/tests/t_romfs_arc.c` | 新增 —— 遍历整份归档、校验每个文件 |
| `docs/ROMFS_ARCHIVE.md` | 新增 —— 格式与设计说明 |
| `dm/host/hle_fs.c` | 挂载并路由归档路径 |
| `dm/host/Makefile` | 编译 `romfs_arc.c` |
| `dm/ios/Sources/main.m` | `romfs_locate` 接受 `romfs.idx` |
| `dm/ios/tools/build_ipa.sh` | 默认瘦身包（`DM_FULL_ROMFS=1` = 上游完整包） |
| `scripts/build_ipa_from_nsp.py` | `--work-dir`（构建目录可离开 NSP 所在文件夹）；自动推导 `DOTNET_ROOT`（framework-dependent 的 `nx_extract` 在裸 shell 里缺它无法启动） |
| `frontend/` | 新增 —— macOS 图形界面前端（见 [图形界面](#图形界面)） |

挂载点按**目录**识别，而不是按名字：各游戏的挂载名不同（多数是 `rom`，《王国之泪》是 `content`）。

## 验证情况

- **《王国之泪》**（0100F2C0115B6000，v1.0.0 + 更新 1.4.3）：304,243 个文件打成 127 个文件；
  304,243 个文件全部与源目录逐字节比对通过（`verify: OK`）；游戏从归档正常运行于 macOS
  （30 fps，1,905 帧）。
- **《哈迪斯 2》**（0100A00019DE0000，本体 + 更新 1.0.137848）：5,258 个文件打成 33 个文件，
  逐字节比对通过，游戏从归档正常运行于 macOS（2,100 帧，1,772 次归档读取）。更新包无需特殊
  处理：`nx_extract` 本来就用 `OpenFileSystemWithPatch` 把更新层叠在本体上，解出的 RomFS
  ——也就是归档——就是合并结果。**在 iPhone 上可玩**（12 GB 设备，AltStore Classic 2.3），
  前提是内存 entitlement 生效——见下。
- C 读取层遍历全部 304,243 个《王国之泪》文件、2,667 个目录，耗时 7.6 秒。

**jetsam 预算是大体积游戏的限制，而它是可以提高的。** 没有
`com.apple.developer.kernel.increased-memory-limit` 时，iPhone 给这个 App 约 3,375 MB（12 GB
设备实测：《王国之泪》进大地图时被杀，常驻 3,342 MB、余量 33 MB；渲染缩放降到 0.5 无改善，
说明瓶颈在 guest 堆而不是 GPU）。App 请求了这个 entitlement，`build_ipa.sh` 把它嵌进占位用的
ad-hoc 签名——无签名的二进制没有可供侧载工具读取 entitlement 的签名，不做这一步请求就会丢失。
**AltStore Classic 2.2+**、**Impactor** 和 **Xcode + Personal Team** 会保留它；**SideStore**
配合免费 Apple ID 需要对 App ID 做一次性修复；**Sideloadly** 不会。步骤和判断方法（log.txt 里
resident + headroom：约 3,375 MB = 未生效，6–8 GB = 已生效）见
[dm/ios/ENTITLEMENTS.md](dm/ios/ENTITLEMENTS.md)。

## 限制

- **只读。** 归档从不写入；存档和临时数据照旧走各自的挂载点。
- **大小写敏感查找。** 名称按源目录树原样存储，所以宿主的 APFS 大小写不敏感别名机制对归档条目
  不适用。
- **符号链接在打包时展开。** 目前支持的游戏 RomFS 里没有符号链接。
- **索引常驻内存。** 《王国之泪》是 28 MB（其中 17.9 MB 是名称）。分片不常驻。
- **不做去重或压缩。** 分片是源字节原样，所以 `verify` 就是直接比对，重复打包的结果是确定的。

## 致谢

所有模拟相关的工作都是别人的。本仓库在其之上增加了归档子系统：

- **[nxnative](https://github.com/seedds/nxnative)**（MIT）—— 本仓库所基于的原生执行工具链：
  NSO 重写器、Horizon 宿主层、NVN-on-Metal、各游戏 profile 和 iOS 外壳。
- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)**（MIT）—— nxnative 由之发展而来的
  原始原生执行方案。
- **Ryujinx**（MIT）—— 把 Maxwell 着色器翻译成 SPIR-V 的翻译器。
- **[Atmosphère](https://github.com/Atmosphere-NX/Atmosphere)** —— Horizon 同步语义的参考实现。
- **[LibHac](https://github.com/Thealexbarney/LibHac)** —— `nx_extract` 用它读取 NSP 并叠加更新。
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** —— SPIR-V 转 Metal Shading Language。
- **yuzu**、**deko3d**、**libvpx**、**stb_vorbis**、**libdeflate** —— 各自贡献见上游致谢列表。

`dm/third_party` 里随附了其他项目及其许可证（[列表](dm/third_party/README.md)）。

## 法律

本仓库不含任何游戏代码、美术、文本、数据表或着色器，也不分发这些内容。你需要自己合法持有的游戏副本
和 `prod.keys`。归档工具只读取你已在自己机器上导出的游戏文件，不上传任何数据。

与任天堂及任何游戏发行商均无关联。
