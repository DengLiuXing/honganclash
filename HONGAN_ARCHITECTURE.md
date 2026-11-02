# 红岸（HongAn）Windows 客户端：Clash 配置到底从哪来

> 本文是对**本机已安装的红岸 Windows 客户端**（`HongAnapp.exe` 及其同目录组件）做的静态 + 运行期观察结论，
> 目的是搞清楚「它怎么拿到 Clash 配置」，从而能在别的平台上复现同一套流程。
> **不含**任何红岸服务端代码、密钥或证书；文中出现的地址、字段名都来自客户端自身的字符串与网络行为。

> **2026-11-02 更正**：红岸订阅接口现在只认官方 UA，返回的是加密 base64，不再直接返回标准 YAML。
> 当前补丁改走 `/api/v1/user/server/fetch` 的明文节点表，在本地生成配置。下文关于 Windows 客户端组件、
> 内存取证与 JSON-RPC 的观察保留作历史对照；订阅链路以 [README 第 2 节](README.md#2-它是怎么工作的) 为准。

---

## 1. 结论（一句话）

客户端先登录红岸面板拿账号专属的订阅地址；订阅接口现在返回**红岸加密的 base64**（且有 UA 白名单），
明文节点表在 `/api/v1/user/server/fetch`。客户端把明文/解密后的配置通过本地 socket 上的 **JSON-RPC**
交给一个 **mihomo（Clash.Meta）内核**去跑。

---

## 2. 组件构成

安装目录（`%LOCALAPPDATA%\Programs\HongAnapp`）：

| 文件 | 大小 | 身份 |
| --- | --- | --- |
| `HongAnapp.exe` | 469 KB | Flutter Windows 启动器（壳，没有实质逻辑） |
| `data\app.so` | 13.6 MB | **Dart AOT 快照**（ELF 容器），界面与业务逻辑都在这里 |
| `HongAnappCore.exe` | 40.1 MB | **Go 写的 mihomo 内核**（见下） |
| `HongAnappHelperService.exe` | 823 KB | Rust 写的 Windows 服务：校验并拉起内核 |
| `proxy_plugin.dll` / `flutter_js_plugin.dll` / `quickjs_c_bridge.dll` / `sqlite3.dll` … | | 系统代理、QuickJS 脚本、SQLite 等 Flutter 插件 |
| `data\flutter_assets\assets\data\{GEOIP.dat,GEOSITE.dat,GEOIP.metadb,ASN.mmdb}` | 43 MB | 地理数据 |

运行期数据目录（`%APPDATA%\HongAnapp\HongAnapp`）：`config.yaml`、`profiles\<id>.yaml`、`database.sqlite`、
`shared_preferences.json`、`cache.db`（内核的 bbolt 缓存）、`HongAnapp.lock`、同上地理数据。

### 内核身份（`HongAnappCore.exe`）

- Go **1.26.0**，module path `core`，`-buildmode=exe`，`-tags with_gvisor`，`CGO_ENABLED=0`，`-ldflags "-w -s"`
- 依赖 `github.com/metacubex/mihomo` 被 **replace 到 `./Clash.Meta`**（自建 fork，`vcs.modified=true`）
- 其它依赖：`metacubex/sing`、`sing-tun`、`sing-quic`、`sing-shadowsocks`、`sing-vmess`、`gvisor`、`quic-go`、`utls`、
  `bbolt`、`miekg/dns`、`yaml.v3` …——教科书式的 mihomo 系
- 构建路径字符串：`D:/a/NetAPP/NetAPP/core/...`；`vcs.revision`、`vcs.time` 都在二进制里

### Helper 的身份

- Rust（`rustc` 哈希可查）、`hyper` + `tokio`，源文件路径 `HongAnappHelperServicesrc\service\windows.rs`
- 内嵌字符串 **`FlClashHelperService failed: `** —— 与上游 FlClash 的 Helper 同源改造而来
- HTTP 路由串 `pingstartstoplogsshutdown` → `/ping` `/start` `/stop` `/logs` `/shutdown`，监听 `127.0.0.1:49890`
- 二进制里**内嵌了内核的 SHA-256**（`bc32d125…35283f8`，与 `HongAnappCore.exe` 完全一致）→ 启动内核前会校验

---

## 3. 五步链路

### ① 登录面板

```
POST http://hn.luoyaccc.com/api/v1/passport/auth/login
Content-Type: application/json
User-Agent: Mozilla/5.0 (dart:io) SuperAccelerator  # 当前补丁的面板 API UA
{"email":"<你的邮箱>","password":"<你的密码>"}

200 → {"data":{"token":"<订阅 token>","is_admin":0,"auth_data":"<JWT>"}}
```

成功后的凭证存进 `shared_preferences.json`（`flutter.auth_token` 是 JWT，长度 157，`tymon/jwt-auth` 格式）。
注意：**`data.token` 才是订阅 token，`data.auth_data` 才是 JWT**，两者用途不同。

### ② 取订阅地址

```
GET http://hn.luoyaccc.com/api/v1/user/getSubscribe
Authorization: <裸 JWT>            ← 加 "Bearer " 会 403

200 → {"data":{...,"subscribe_url":"http://<订阅主机>:<端口>/api/v2/acct-mgmt?token=<订阅 token>",
               "u":<上传>,"d":<下载>,"transfer_enable":<总额>,"plan":{...},"uuid":"<账号 uuid>"}}
```

`database.sqlite` 里的 `profiles` 表把这条记录持久化：`label`（套餐/机场名）、`url`、`auto_update=1`、
`auto_update_duration_millis=86400000`（24 小时）、`subscription_info`（流量 JSON）、`selected_map`。
有意思的是：**面板返回的是原始 IP 形式的订阅地址，而落库时客户端会把它改写成自己域名下的中转形式**
（`hn.luoyaccc.com/api/v2/acct-mgmt?token=…`），两条路径的 token 相同。

### ③ 拉订阅

```
GET <subscribe_url>
→ 红岸加密的 base64（订阅接口只用于确认存活；节点明文改走 /user/server/fetch）
→ 响应头 subscription-userinfo 被解析成流量信息
```

### ④ 落盘（加密）

客户端把订阅原文与本地设置合并：

- 订阅原文 → `profiles\<id>.yaml`
- 合并了 `patchClashConfig` 之后的有效配置 → `config.yaml`
  （实测有效设置的片段：`mixed-port: 7890`、`allow-lan: true`、`mode: rule`、`external-controller: '127.0.0.1:9090'`、
  `dns.enhanced-mode: fake-ip`、`nameserver` 走 DoH、`geox-url` 指向 MetaCubeX 的 meta-rules-dat）
- TUN 设备名是 `HongAnapp`，但默认 `tun.enable: false`

**这两个文件在磁盘上都是密文**：整文件是不含换行的 base64；解码后是高熵字节，
没有 gzip / zlib / zstd / xz / lz4 / bzip2 的任何魔数，不是 LZString，也不是重复 key 的 XOR。
`app.so` 里存在 `ENCRYPTED_SIZE`、`salt` 这类常量，紧邻 `config.yaml` 字面量 → 自定义流密码/带 salt 的方案，密钥在 `app.so` 内。

### ⑤ 交给内核

- Helper 服务（`127.0.0.1:49890` + 命名管道 `\\.\pipe\HongAnapp`）校验内核 SHA-256 后启动 `HongAnappCore.exe`
- 内核**不是** `mihomo -f config.yaml` 那种用法：它唯一的命令行参数是一个 **socket 地址**，
  `main()` 直接调 `startServer(os.Args[1])` 去 **dial** 那个地址（所以内核是 RPC 的**客户端**），启动时**不读配置文件**
- 内核暴露的 RPC 动作（从其 Go 符号表读出）：
  `initClash` / `setupConfig` / `updateConfig` / `validateConfig` / `getConfig` /
  `changeProxy` / `closeConnections` / `startListener` / `stopListener` / `getProxies` / `getConnections` /
  `getTraffic` / `updateGeoData` / `sideLoadExternalProvider` / `startLog` / `stopLog` / `shutdown`
- 内存里能看到 Dart/Go 两边的结构体字段：`InitParams(homeDir: …)`、`SetupParams(selectedMap: …)`、
  `UpdateParams(tun: …)`、`UpdateGeoDataParams(geoType: …, filePath: …)`、`ChangeProxyParams(groupName: …)`、
  `rawConfig` / `realPatchConfig` / `patchClashConfig` / `tunEnable` / `mixedPort`

---

## 4. 明文配置在哪里（以及怎么抓）

**磁盘上没有明文。** 明文配置只在：

- **内核进程的内存里**（订阅原文 + 合并后的有效配置结构体）；
- 以及 App ↔ 内核之间的 **RPC 管道**上短暂出现。

因此复现/取证的做法是运行期内存扫描：

1. 以管理员权限 `OpenProcess` + `ReadProcessMemory` + `VirtualQueryEx` 遍历 `HongAnappCore.exe` 的已提交内存；
2. 用 `proxies:`、`proxy-groups:`、`mixed-port:`、节点 URI（`anytls://`/`ss://`/`vmess://`/`vless://`/…）当特征串；
3. 命中的窗口里通常正好是一整段 YAML 文本。

经验与坑：

- **别把特征串写进你自己的扫描脚本再扫描整个临时目录**——脚本自身的文本会命中，产生假阳性；
- 内核与 App 的内存里**字符串常量池**（Dart AOT / Go 的字符串表）里有大量 `proxies:`、`rules:`、`dns:` 之类的字段名，
  **它们不是配置**；判断依据是附近有没有成段的 YAML 语义（`port:`、`- name:`、`type:`、`server:`）；
- 内存里同一份 YAML 可能被切成多段（Go 的字符串表把 key 与 value 分开存放），所以「有效配置」常常无法整段捞出，
  能整段捞出的是**订阅原文**——而它才是真正需要的东西。

顺带说明：红岸把 `external-controller` 置空（或只监听本地且不开放），所以**不能**通过 mihomo 的 9090 REST API
直接 `GET /configs` 拿运行时配置；指望这条捷径是行不通的。

---

## 5. 为什么这能迁移到别的平台

- 面板交互只有两个 HTTP 请求（登录、取订阅），与平台无关；
- 节点明文来自 `/user/server/fetch`，可生成标准 mihomo YAML；订阅接口本身返回加密数据；
- 内核本身就是 mihomo 的 fork —— 上游 FlClash 用的是同一族的 `chen08209/Clash.Meta`（分支 `FlClash`），
  所以「不换内核、只补登录逻辑」就能在 Linux/macOS 上得到等价体验。

本仓库的补丁正是这么做的：见 [`README.md`](README.md) 与 `patch/hongan-flashclash.patch`。

---

## 6. 合规声明

本文与仓库内的工具仅用于**互操作性研究**与在自有账号上使用自有订阅。
抓取到的节点凭据属于账号持有人，**请勿公开或提交到仓库**（仓库 `.gitignore` 已默认排除这些文件名）。
