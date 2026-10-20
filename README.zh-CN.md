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
| 不含游戏的 IPA（`DM_NO_ROMFS=1`） | — | **743 MB，可安装** |
| 拷到手机 | 数小时 | 一个含 127 个文件的文件夹 |

路径查找是对排序后的文件表做二分查找；目录枚举只遍历一段连续的子项区间。索引用 `mmap` 映射，
分片按需打开，读取直接在分片上 `pread`，所以页缓存照常生效。

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

### 2. 把 RomFS 打包成归档

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

### 3. 构建不含 RomFS 的 IPA

```bash
DM_NO_ROMFS=1 GAME=<title id> W=<工作目录> PATCHED=<改写目录> \
  ROMFS=<RomFS 目录> MSL_IOS=<shader 目录> \
  dm/ios/tools/build_ipa.sh <输出.ipa>
```

不设 `DM_NO_ROMFS=1` 时，脚本行为与上游完全一致（RomFS 进包）。

### 4. 把归档拷到手机

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
| `dm/ios/tools/build_ipa.sh` | `DM_NO_ROMFS=1` |

挂载点按**目录**识别，而不是按名字：各游戏的挂载名不同（多数是 `rom`，《王国之泪》是 `content`）。

## 验证情况

- **《王国之泪》**（0100F2C0115B6000，v1.0.0 + 更新 1.4.3）：304,243 个文件打成 127 个文件；
  304,243 个文件全部与源目录逐字节比对通过（`verify: OK`）；游戏从归档正常运行于 macOS
  （30 fps，1,905 帧）。
- C 读取层遍历全部 304,243 个文件、2,667 个目录，耗时 7.6 秒。

**在 iPhone 上，《王国之泪》目前会停在进入大地图时。** 常驻内存达到约 3.34 GB，而 12 GB 设备给单个
App 的 jetsam 预算就是这么多（实测剩余余量 33 MB），开放世界需要更多。把渲染缩放降到 0.5 没有改变
结果，说明瓶颈在 guest 堆而不是 GPU。上游测试列表里的游戏（4–6 GB）离这个预算还远。

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
