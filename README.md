# honganclash — 让红岸（HongAn）在 Linux 上可用

> 把红岸那个**只有 Windows** 的特制客户端里真正不可替代的一环 ——「登录面板、拿账号 uuid 与明文节点表」——
> 做进开源客户端 FlClash，于是 Linux（以及 macOS / Windows / Android）都能用红岸的账号与节点。

本仓库是 **FlClash 源码 + 红岸支持补丁**：可以直接 `flutter run -d linux` 起界面，然后像上游一样用订阅、节点、规则、TUN、系统代理。

- 上游：<https://github.com/chen08209/FlClash>（`main` 分支，v0.9.2 快照 `7fd417f`，2026-11-02）
- 本仓库相对上游的全部代码改动：**9 个文件，+741 行，-3 行**（含测试；另加若干说明与工具文件，见下表）
- 许可：**GPL-3.0**（继承上游，`LICENSE` 原文未改）

---

## 1. 本仓库额外添加 / 修改的文件（重点）

### 1.1 代码改动（红岸支持本身）

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `lib/common/hongan.dart` | **新增** (+432) | 面板 API：`login()` / `subscription()` / `servers()`；`buildHonganConfig()` 把明文节点表生成本地 mihomo 配置 |
| `lib/views/profiles/hongan.dart` | **新增** (+137) | 「红岸账号导入」弹窗：邮箱/密码、加载态、错误提示 |
| `lib/views/profiles/add.dart` | 修改 (+17) | 订阅页新增入口项；登录后交给 `addHonganProfile()` |
| `lib/providers/actions/profiles.dart` | 修改 (+40) | 生成 file profile，写入 `SubscriptionInfo`（用量/到期） |
| `lib/views/profiles/profiles.dart` | 修改 (+3) | file profile 也显示流量用量 |
| `lib/common/common.dart` | 修改 (+1) | `export 'hongan.dart';` |
| `test/common/hongan_test.dart` | **新增** (+95) | 节点解析 / 配置生成测试 |
| `test/widgets/profile_focus_test.dart` | 修改 (+16) | file profile 流量显示测试 |

这些改动的等价 `git diff` 单独放在 `patch/hongan-flclash.patch`，方便把它移植到**更新的上游版本**上。

### 1.2 说明 / 工具文件（不参与编译）

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `README.md` | **新增** | 本文件 |
| `README_UPSTREAM.md` | 改名 | 上游 FlClash 的原始 README（内容一字未改，仅改名，避免与本文件冲突） |
| `HONGAN_ARCHITECTURE.md` | **新增** | 逆向分析：红岸 Windows 客户端到底是怎么拿到 Clash 配置的（组件、链路、内核 RPC、加密与内存取证、复现方法） |
| `HONGAN_BUILD_LINUX.md` | **新增** | Linux 构建 / 子模块坑 / 使用 / 排错 |
| `patch/hongan-flclash.patch` | **新增** | 上表 1.1 的 `git diff`（26804 B，842 行，LF） |
| `tools/hongan_fetch.py` | **新增** | 纯 Python 标准库脚本：`/user/server/fetch` 明文节点表 / 免密读客户端凭据 / **uuid+模板** 兜底，`--discover`/`--verify` 用 mihomo 实测 |
| `.gitignore` | 修改 | 追加一栏：**不要把抓下来的节点/订阅文件提交上来**（里面有你的账号凭据） |
| `.gitmodules` | 修改 | 子模块 `core/Clash.Meta` 的 URL 由 SSH 改成 HTTPS（否则没配 GitHub key 的 Linux 机器拉不动） |

> 说明文件放在根目录，避开上游 `docs/` 的构建目录。

### 1.3 未改动、保持上游原样的关键文件

`LICENSE`（GPL-3.0 原文）、`lib/core/`（内核控制）、`lib/providers/`、`lib/models/`、`core/`（Go 核心构建脚本）、
`services/helper/`（Rust Helper）、`pubspec.yaml`、l10n 生成物。**没有**新增 provider / model / 数据库字段，
所以**不需要**重跑 `build_runner` 代码生成；也没有改 l10n，不会碰到生成文件。

---

## 2. 它是怎么工作的

红岸的面板是 V2Board 系账号体系。**订阅地址本身已经不是可用的 YAML**：它对 UA 有白名单，
放行后返回的也是红岸加密的 base64。补丁改走面板的**明文节点表**，在本地生成配置：

```
POST http://hn.luoyaccc.com/api/v1/passport/auth/login   {"email","password"}
        → data.token（订阅 token）  data.auth_data（JWT）
GET  /api/v1/user/getSubscribe          （Authorization = 裸 JWT）
        → data.uuid（节点密码） / u / d / transfer_enable / expired_at / subscribe_url
GET  /api/v1/user/info                  （quota / uuid 的兜底）
GET  /api/v1/user/server/fetch          （Authorization = 裸 JWT）
        → [ { name, host, port, server_name, insecure, is_online, type: anytls }, ... ]
本地 buildHonganConfig() → mihomo YAML（proxies + groups + rules + dns）
        → 保存为 file profile，并把 u/d/transfer_enable 写进 SubscriptionInfo
```

四个实测踩坑点，补丁里已经写死：

1. `Authorization` 必须是**裸 JWT**，加 `Bearer ` 前缀会被面板 403；
2. 面板 API 用 `Mozilla/5.0 (dart:io) SuperAccelerator`；订阅接口另有一个白名单
   `NetFlow/v2.2.8 clash-verge Platform/windows`，其他 UA 一律 444；
3. 订阅接口即使放行也返回**加密数据**，不要拿它当 YAML；节点明文走 `/user/server/fetch`；
4. 面板报错是 **403 / 444**，要自己判状态码，才能把「未登录或登陆已过期」这类信息显示出来。

更完整的机制（内核是 mihomo fork、配置在磁盘上是加密的、明文只在内存/管道中出现、内核通过 socket 上的 JSON-RPC 收配置）
见 **[HONGAN_ARCHITECTURE.md](HONGAN_ARCHITECTURE.md)**。

---

## 3. 快速开始（Linux）

完整版（依赖、排错、验证）见 **[HONGAN_BUILD_LINUX.md](HONGAN_BUILD_LINUX.md)**，这里只给最短路径：

```bash
# 1) 依赖：Flutter 3.47.x（上游 CI 钉 3.47.6）、Go、Rust/cargo，以及 Linux 桌面依赖
#    sudo apt install clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev

# 2) 克隆（含子模块；本仓库已把子模块 URL 改成 HTTPS）
git clone --recursive https://github.com/DengLiuXing/honganclash.git
cd honganclash

# 3) 运行
flutter pub get
flutter run -d linux            # 建议第一次加 --dart-define=SAFE_MODE=true，先不改系统 TUN/代理

# 4) 打包
dart setup.dart linux
```

> `core/Clash.Meta/` 是子模块，分支是 `FlClash`。若 `git submodule update --init --recursive` 拉不到，用：
> `git config --global url."https://github.com/".insteadOf "git@github.com:"` 之后再重试。

> 不想在本机装 Flutter / Go / Rust？可以直接在 GitHub Actions 里构建，见
> [HONGAN_BUILD_LINUX.md](HONGAN_BUILD_LINUX.md) 第 3 节。

> 更新检查已指向本仓库的 release，发布 Linux / Windows / macOS 桌面产物（Android 暂未包含）；
> 仓库还没有 release 时不会提示更新。

### 用法

启动 FlClash → **配置（Profiles）** 页 → 右下 `+` → **红岸账号导入** → 填红岸面板的邮箱与密码 → 「登录并导入」→
列表出现 `红岸云` file profile；节点、分组、规则由本地生成，卡片显示登录时的已用/总量。

file profile 不会自动更新；重新登录一次即可刷新节点与用量。之后就是普通 FlClash 用法：
选节点、切模式（规则/全局/直连）、开系统代理或 TUN。

---

## 4. 安全与隐私（必读）

- **不要把你抓下来的节点/订阅文件提交到任何仓库**。`hongan_nodes.yaml`、`hongan_subscription_raw.yaml`
  以及 `tools/hongan_fetch.py` 的输出里含有你的账号凭据：**节点密码就是面板账号的 uuid**，
  订阅 URL 里带着**订阅 token**。本仓库的 `.gitignore` 已经把这些文件名挡在外面。
- 红岸面板 API 是**明文 HTTP**（`http://hn.luoyaccc.com`），账号、密码、JWT 都会明文过网，
  请只在可信网络下使用；有能力的话给它套一层 TLS。
- 红岸官方 Windows 客户端会把**密码明文**写进 `shared_preferences.json`（字段 `flutter.password`）。
  本补丁**不保存密码**，只在一次登录中使用。
- 运行 FlClash 会改动你的**系统代理**；开 TUN 还会创建虚拟网卡。第一次请用 `SAFE_MODE=true`。
- 账号、订阅、计费仍然完全由红岸的面板控制；本项目只是把「客户端如何与面板交互」重新实现了一遍，
  **不包含任何红岸的服务端代码、密钥或证书**，也不绕过任何计费。可用性与封号风险由使用者自行承担。

---

## 5. 已知限制

1. **上游快照是 v0.9.2（`7fd417f`）**：本仓库的代码改动已 rebase/重放到该快照上；
   `flutter pub get`、`flutter analyze --no-fatal-infos` 和红岸相关 `flutter test` 已通过。
2. **订阅接口不是 YAML 源**：它只认官方 UA 且返回加密数据；节点明文来自 `/user/server/fetch`。
   如果这个接口也不可达，导入会报错；兜底是导入一份已有的完整 YAML，或使用 `tools/hongan_fetch.py`
   的 `uuid + 模板`/`--discover` 路径。
3. 红岸节点是 `anytls`，需要 mihomo/Meta ≥ 1.19 或 sing-box ≥ 1.12；FlClash 自带内核满足。
4. `红岸云` 是 **file profile**：不会自动更新，规则/分组由 `buildHonganConfig()` 生成，用量是登录时的快照；
   重新登录一次可刷新。

---

## 6. 许可与署名

- 本项目基于 **[FlClash](https://github.com/chen08209/FlClash)**（作者 chen08209 及贡献者），采用 **GPL-3.0**；
  `LICENSE` 是上游原文，未做任何修改。
- 本仓库**新增**的红岸支持代码与文档同样以 **GPL-3.0** 发布；再分发请保留署名与许可。
- 红岸（HongAn）是其权利人的产品名/商标，本项目与其无隶属或背书关系，仅为互操作性实现。
