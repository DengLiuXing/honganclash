# honganclash — 让红岸（HongAn）在 Linux 上可用

> 把红岸那个**只有 Windows** 的特制客户端里唯一真正不可替代的一环 ——「登录面板换订阅地址」—— 做进开源客户端 FlClash，
> 于是 Linux（以及 macOS / Windows / Android）都能用红岸的账号与节点。

本仓库是 **FlClash 源码 + 红岸支持补丁**：可以直接 `flutter run -d linux` 起界面，然后像上游一样用订阅、节点、规则、TUN、系统代理。

- 上游：<https://github.com/chen08209/FlClash>（`main` 分支快照）
- 本仓库相对上游的全部代码改动：**4 个文件，+388 行，0 删除**（另加若干说明与工具文件，见下表）
- 许可：**GPL-3.0**（继承上游，`LICENSE` 原文未改）

---

## 1. 本仓库额外添加 / 修改的文件（重点）

### 1.1 代码改动（红岸支持本身）

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `lib/common/hongan.dart` | **新增** (+230) | 红岸面板 API 客户端：`login()` → `subscription()`，异常类型 `HonganApiException`，全局单例 `honganApi` |
| `lib/views/profiles/hongan.dart` | **新增** (+137) | 「红岸账号导入」弹窗：邮箱/密码、加载态、错误提示 |
| `lib/views/profiles/add.dart` | 修改 (+20) | 订阅页新增入口项；登录成功后调用上游原生 `addProfileFromLink(subscribeUrl)` |
| `lib/common/common.dart` | 修改 (+1) | `export 'hongan.dart';` |

这些改动的等价 `git diff` 单独放在 `patch/hongan-flclash.patch`，方便把它移植到**更新的上游版本**上。

### 1.2 说明 / 工具文件（不参与编译）

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `README.md` | **新增** | 本文件 |
| `README_UPSTREAM.md` | 改名 | 上游 FlClash 的原始 README（内容一字未改，仅改名，避免与本文件冲突） |
| `HONGAN_ARCHITECTURE.md` | **新增** | 逆向分析：红岸 Windows 客户端到底是怎么拿到 Clash 配置的（组件、链路、内核 RPC、加密与内存取证、复现方法） |
| `HONGAN_BUILD_LINUX.md` | **新增** | Linux 构建 / 子模块坑 / 使用 / 排错 |
| `patch/hongan-flclash.patch` | **新增** | 上表 1.1 的 `git diff`（13180 B，LF，0 CR） |
| `tools/hongan_fetch.py` | **新增** | 纯 Python 标准库脚本：面板订阅 / 免密读客户端凭据 / **uuid+模板本地生成** 三级兜底，`--verify` 用 mihomo 实测 |
| `.gitignore` | 修改 | 追加一栏：**不要把抓下来的节点/订阅文件提交上来**（里面有你的账号凭据） |
| `.gitmodules` | 修改 | 子模块 `core/Clash.Meta` 的 URL 由 SSH 改成 HTTPS（否则没配 GitHub key 的 Linux 机器拉不动） |

> 上游 `.gitignore` 第 49 行忽略了 `docs/`，所以本仓库的说明文件全部放在根目录。

### 1.3 未改动、保持上游原样的关键文件

`LICENSE`（GPL-3.0 原文）、`lib/core/`（内核控制）、`lib/providers/`、`lib/models/`、`core/`（Go 核心构建脚本）、
`services/helper/`（Rust Helper）、`pubspec.yaml`、l10n 生成物。**没有**新增 provider / model / 数据库字段，
所以**不需要**重跑 `build_runner` 代码生成；也没有改 l10n，不会碰到生成文件。

---

## 2. 它是怎么工作的

红岸的面板是 V2board 系账号体系，**订阅地址是登录后按账号签发**的：

```
POST http://hn.luoyaccc.com/api/v1/passport/auth/login   {"email","password"}
        → data.token（订阅 token）  data.auth_data（JWT）
GET  /api/v1/user/getSubscribe          （Authorization = 裸 JWT）
        → data.subscribe_url = http://<订阅主机>:<端口>/api/v2/acct-mgmt?token=<订阅token>
GET  <subscribe_url>                    → 标准 Clash / mihomo YAML（+ subscription-userinfo 头）
        → 交给 FlClash 原生订阅流程（下载、校验、落盘、定时更新）
```

三个实测踩坑点，补丁里已经写死：

1. `Authorization` 必须是**裸 JWT**，加 `Bearer ` 前缀会被面板 403；
2. `User-Agent` 要用 `Dart/3.9 (dart:io)`（面板对 UA 有区分）；
3. 面板报错是 **403 / 444 + JSON body**，所以要自己判状态码，才能把「未登录或登陆已过期」这类信息显示出来。

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

> 更新检查已指向本仓库的 release，并且只发布 Linux 产物；仓库还没有 release 时不会提示更新。

### 用法

启动 FlClash → **订阅** 页 → 右下 `+` → **红岸账号导入** → 填红岸面板的邮箱与密码 → 「登录并导入」→
列表出现订阅 `红岸云`；之后节点、分组、规则、定时更新（面板默认 24h）、流量都走上游原生能力。

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

1. **`flutter analyze` / `flutter test` 还没跑过**：生成补丁的机器上没有 Dart/Flutter 工具链。`Desktop linux`
   构建已经在 GitHub Actions 通过；`Dart` job 目前卡在 `dart format`，修好格式后才会跑分析/测试。
   每一处 API 都逐条对照过上游源码（包括把 dio 的真实源码下载下来核对请求头常量），但首次运行仍可能有问题。
2. **红岸的订阅后端可能不可达**：面板 API 通常是好的，但订阅主机（形如 `http://47.100.65.251:16384/...`）
   在某些网络下 TCP 不通或返回 502，此时导入会在「下载订阅」这一步失败并弹出错误提示（不会崩）。
   兜底办法：直接导入一份已经拿到的 Clash 配置（YAML）即可，FlClash 本身就支持文件导入。
3. 订阅返回的是标准 mihomo YAML；红岸的节点用 `anytls`，需要能解析它的内核（mihomo/Meta ≥ 1.19 或 sing-box ≥ 1.12）。
4. 面板下发的**规则列表**在订阅 YAML 的 `rules:` 里，随订阅更新；离线配置请自备规则集。

---

## 6. 许可与署名

- 本项目基于 **[FlClash](https://github.com/chen08209/FlClash)**（作者 chen08209 及贡献者），采用 **GPL-3.0**；
  `LICENSE` 是上游原文，未做任何修改。
- 本仓库**新增**的红岸支持代码与文档同样以 **GPL-3.0** 发布；再分发请保留署名与许可。
- 红岸（HongAn）是其权利人的产品名/商标，本项目与其无隶属或背书关系，仅为互操作性实现。
