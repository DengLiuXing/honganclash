# 在 Linux 上构建与使用 honganclash

> 本文覆盖：依赖工具链、**子模块那个坑**、构建、运行、验证、以及常见故障。
> 仓库内容说明见 [`README.md`](README.md)；机制背景见 [`HONGAN_ARCHITECTURE.md`](HONGAN_ARCHITECTURE.md)。

---

## 1. 工具链

FlClash 的构建会自己编译 Go 内核与 Rust Helper，所以除了 Flutter 还要 Go 与 Rust：

| 组件 | 要求 | 用途 |
| --- | --- | --- |
| Flutter | **3.47.x**（上游 CI 钉 `3.47.6`；`pubspec.yaml` 的 Dart 下限来自编辑器插件 `code_forge` 10.14.0 = Dart 3.13.2，所以**不能低于 Flutter 3.47.2**） | 界面与主程序 |
| Go | 见 `core/go.mod` | 编译 `core/Clash.Meta` 内核 |
| Rust / `cargo` / `rustc` | 稳定版即可 | 编译 Rust Helper 与 `plugins/rust_api` |
| Linux 桌面依赖 | `clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev` | Flutter Linux 桌面 |

```bash
# Debian/Ubuntu 例
sudo apt update
sudo apt install -y clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev
# Flutter 建议用官方 tarball 或 fvm 装到 3.47.x
```

---

## 2. 取源码：**子模块那个坑**

`core/Clash.Meta/` 是一个 **git submodule**（分支 `FlClash`）。上游 `.gitmodules` 里写的是 **SSH** 地址
（`git@github.com:chen08209/Clash.Meta.git`），没有配 GitHub SSH key 的机器会直接拉不动。
本仓库已把它改成 HTTPS，正常按下面这样克隆即可：

```bash
git clone --recursive https://github.com/DengLiuXing/honganclash.git
cd honganclash
```

如果已经克隆过（或当初没加 `--recursive`），补一下：

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

仍然失败时（例如别的脚本把 URL 换回了 SSH），二选一：

```bash
# 方案 A：全局把 SSH 映射到 HTTPS
git config --global url."https://github.com/".insteadOf "git@github.com:"
git submodule update --init --recursive

# 方案 B：直接手动放进去（注意分支是 FlClash，不是 main）
git clone --depth 1 -b FlClash https://github.com/chen08209/Clash.Meta.git core/Clash.Meta
```

> 从 GitHub 网页下载的 **tarball 里没有子模块内容**，`core/Clash.Meta/` 会是个空目录 —— 必须用 `git clone`。

---

## 3. 构建

```bash
flutter pub get

# 开发运行（首次会自动编译 Go 内核 + Rust Helper，耗时较长）
flutter run -d linux

# 建议第一次用“安全模式”，先不动系统的 TUN / 系统代理 / 登录项
flutter run -d linux --dart-define=SAFE_MODE=true

# 生成正式产物
dart setup.dart linux
```

构建 Hook 的日志在 `.dart_tool/setup_build_cache/hook.log`；强制重建内核/Helper：

```bash
rm -rf .dart_tool/setup_build_cache
```

### 与 CI 一致的检查

```bash
dart format --output=none --set-exit-if-changed lib test tool plugins setup.dart
flutter analyze --no-fatal-infos
flutter test
```

> ⚠️ 本补丁**没有在这些检查下跑过**（生成补丁的机器上没有 Dart/Flutter 工具链）。
> 所有用到的 API 都逐条对照过上游源码，包括把 dio 的真实源码下载下来逐个核对请求头常量
> （结论：`Headers.acceptHeader` / `Headers.jsonContentType` 存在，而 `Headers.userAgentHeader` /
> `Headers.authorizationHeader` **不存在**，所以那两个头用的是 `dart:io` 的 `HttpHeaders.*`，与
> `lib/common/request.dart` 的写法一致）。首次 `flutter analyze` 若报错，按报错改即可，改动面很小。

---

## 4. 使用

1. 启动 FlClash → **订阅（Profiles）** 页 → 右下 `+`；
2. 选 **红岸账号导入**；
3. 填红岸面板的**邮箱 + 密码** → 「登录并导入」；
4. 成功后订阅列表出现 `红岸云`，节点/分组/规则/流量都来自面板，并按面板设置自动更新（红岸默认 24 小时）。

之后就是普通 FlClash 用法：选节点、切模式（规则/全局/直连）、开系统代理或 TUN。

### 兜底：不登录也能用

面板的**订阅后端**可能不可达（见下）。如果你手上已有一份 Clash/mihomo YAML（例如已经导出过的红岸订阅），
直接用「从文件导入」即可，本补丁不影响上游任何导入方式。

### 另一种取配置的方式（无图形界面）

`tools/hongan_fetch.py` 只用 Python 标准库：登录面板 → 取订阅地址 → 下载配置 → 生成一份可直接用的 YAML。

```bash
python3 tools/hongan_fetch.py --email <你的邮箱> --password '<你的密码>' --out-dir ./out
python3 tools/hongan_fetch.py --jwt '<现成 JWT>' --out-dir ./out
python3 tools/hongan_fetch.py --from-file old.yaml --out-dir ./out    # 离线重建
```

> 它的输出含你的**订阅 token 与节点密码**，不要提交到仓库（`.gitignore` 已挡）。

---

## 5. 常见故障

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `git submodule update` 报权限/连不上 | 上游 `.gitmodules` 是 SSH 地址 | 见第 2 节方案 A / B |
| 构建时 Go / cargo 相关失败 | 缺 Go 或 Rust 工具链 | 装上 `go`、`rustup`（含 `cargo`/`rustc`）后 `rm -rf .dart_tool/setup_build_cache` 重来 |
| `flutter run -d linux` 起不来（缺 GTK） | 少了桌面依赖 | 装 `clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev` |
| 点「登录并导入」后弹错、列表没新增 | 面板订阅后端不可达（下载失败），或账号已过期 | 先确认面板能正常登录；订阅后端故障时属服务端问题，改用文件导入兜底 |
| 登录报「未登录或登陆已过期」 | JWT 过期（面板 403） | 重新点一次导入（每次都重新登录换新 JWT） |
| 节点能选但连不上 | 内核不支持 `anytls`，或节点端口/密码已轮换 | 用 mihomo/Meta ≥ 1.19（或 sing-box ≥ 1.12）；重新导入拿最新节点 |
| 想回到没改系统代理的状态 | FlClash 改了系统代理/TUN | 客户端里关掉系统代理与 TUN；下次先用 `SAFE_MODE=true` |
| 只想验证补丁编不编得过 | —— | `flutter analyze --no-fatal-infos` 不报错即可，再 `flutter run -d linux` 看界面 |

---

## 6. 运行期行为提醒

FlClash 是**接管系统**的客户端：它会设置系统代理，开 TUN 时会创建虚拟网卡，可能注册登录启动项，
并由特权 Helper 管理内核进程。首次在主力机上试跑，建议：

```bash
flutter run -d linux --dart-define=SAFE_MODE=true
```

另外：同一个 Helper 只能管一个内核实例，**运行开发版会停掉已安装的 FlClash 正在跑的内核**。

---

## 7. 许可提醒

本仓库整体是 **GPL-3.0**（继承上游 FlClash）。你基于它再分发（包括只发二进制）时，
需要一并提供对应源码与许可，并保留上游署名。
