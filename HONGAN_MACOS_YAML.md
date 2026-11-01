# 红岸 macOS 客户端：YAML 到底怎么拿

分析对象：`/home/dlx/下载/hongan-macos-universal.pkg`
SHA-256：`245aa4a4b3b9e8a5612b5a5082d50cddb3d8472ab79060642d9d5068950a27f0`
版本：`红岸加速器.app` 2.2.8（CFBundleVersion `2026040812`，bundle id `com.hongan.seppd`）

> 说明：本文的包分析来自普通静态工具（xar/cpio 解包、Mach-O/Dart AOT 字符串、
> Go build info、HTTP 探针），不是 REA Evidence；REA MCP 是后来才接入的，
> 未参与这批结论。无法静态确认的地方标为“未知/待验证”。

> **2026-11-01 更正（基于新抓包与 `hongan_fetch.py` v2）**：第 3 节原先“下载 `subscribe_url` 得到 YAML”
> 的结论已推翻。订阅接口只认官方 UA `NetFlow/v2.2.8 clash-verge Platform/windows`，其他 UA 一律 444；
> 即使放行，返回的也是红岸加密的 base64 块，不是标准 Clash YAML。**明文节点改走面板
> `/api/v1/user/server/fetch`（JWT）**，字段含 `host`/`port`/`server_name`/`insecure`/`is_online`，
> `uuid` 就是节点密码。仓库 `tools/hongan_fetch.py` v2 已按这条链路实现。

## 1. 安装包里有什么（以及没有什么）

`.pkg` 是 xar，内部：

| 成员 | 说明 |
| --- | --- |
| `Distribution` | 安装描述，bundle `com.hongan.seppd`，v2.2.8 |
| `PackageInfo` | 5944 files，安装到 `/Applications/红岸加速器.app` |
| `Payload` | gzip cpio，展开后是 app |
| `com.hongan.seppd.pkg` | 只是 BOM，不是第二个组件包 |

app 内：

- `Contents/MacOS/红岸加速器`：330 KB Flutter 启动器
- `Contents/MacOS/honganCore`：65 MB，Go 1.24.0 + mihomo（`core`，2026-04-08 构建），含 648 处 `anytls`
- `Contents/Frameworks/App.framework/Versions/A/App`：27 MB Dart AOT 快照
- `Contents/Frameworks/...`：Flutter 插件（`flutter_js`、`flutter_inappwebview_macos`、`sqflite`、`shared_preferences_foundation`、`path_provider_foundation`、`tray_manager` 等）
- `flutter_assets/assets/data`：GEOIP/GEOSITE/ASN 地理数据

**没有**：

- 没有任何 `*.yaml` / `*.yml` / `config` / `profiles` / 订阅文件（`find` 全包为 0）
- 没有写死的面板域名：全包搜索 `luoyaccc` 为 0 命中；`hn.` 只出现在核心/Library 字符串里
- 没有 Helper/LaunchDaemon/系统扩展；macOS 版是 `chown root:admin` + `with administrator privileges` 的 admin 模式，直接拉起 `honganCore`

所以：**YAML 不在安装包里**。客户端登录面板后，节点明文从 `/user/server/fetch` 取；
面板的订阅接口本身返回的是加密数据（见第 3 节）。

## 2. 关键差异：macOS 版是“可填服务器地址”的 V2Board 客户端

Dart AOT 里能直接读到的字符串：

```text
api_base_url
服务器地址 / 请输入伺服器地址 / 请输入服务器地址
/welcome back.../ 登录 / 邮箱 / 密码 / 注册 / 找回密码 / 邮箱验证码
/api/v1
/passport/auth/login
/passport/auth/register
/passport/auth/forget
/user/getSubscribe
subscribe_url
auth_data
auth_token
cached_subscribe_info
download_url
transfer_enable
profiles
database.sqlite
config.yaml
ENCRYPTED_SIZE
salt
shared_preferences.json
honganCore.lock
/tmp/honganCoreSocket_
```

还有完整的 V2Board 用户面板功能字符串（订单、工单、邀请码、提现、优惠券等）。
这跟 Windows 版（固定 `hn.luoyaccc.com`、只有登录+导入）不同：**macOS 版把面板地址做成用户输入项**，
所以安装包里不需要（也没有）内置域名。

已知的面板（Windows 版用的）可以填：

```text
http://hn.luoyaccc.com
```

HTTP 可用；HTTPS 证书与域名不匹配（实测 curl 报 `no alternative certificate subject name`）。

## 3. 面板 API 链路（已实测路径存在）

在 `http://hn.luoyaccc.com/api/v1` 上做的无凭据探针：

```text
POST /passport/auth/login   {}                     -> HTTP 422（邮箱/密码不能为空）
GET  /user/getSubscribe     无 Authorization       -> HTTP 403（未登录或登陆已过期）
GET  /user/getSubscribe     Authorization: test     -> HTTP 403
GET  /user/getSubscribe     Authorization: Bearer test -> HTTP 403
```

路径、方法、JSON 字段与仓库里的 `tools/hongan_fetch.py` 一致：

1. `POST {base}/api/v1/passport/auth/login`
   - JSON：`{"email":"...","password":"..."}`
   - 返回：`data.auth_data` = JWT；`data.token` = 订阅 token
2. `GET {base}/api/v1/user/getSubscribe`
   - Header：`Authorization: <原始 JWT>`（已确认；加 `Bearer ` 会 403）
   - 返回：`data.subscribe_url`（可能还有 `download_url`）、`data.uuid`（就是节点密码）
3. `GET <subscribe_url>`
   - **必须**带官方 UA：`NetFlow/v2.2.8 clash-verge Platform/windows`。换任何其他 UA（Clash/Dart/
     浏览器/curl）一律 **HTTP 444**，空 body——这正是早期脚本失败的真正原因，不是后端挂了。
   - 即使 UA 正确，返回的也是**红岸加密的 base64 块**（不是 gzip/zstd，也不是明文 Clash YAML）；
     只有红岸客户端自己能解。所以这个 URL 只能确认“订阅还活着/拿流量”，不能喂给 mihomo/FlClash。
4. `GET {base}/api/v1/user/server/fetch`（`Authorization: <原始 JWT>`）→ **明文节点表**
   - 目前唯一“既有明文、又由面板自己维护”的来源；
   - 每条记录含 `host`、`port`、`server_name`、`insecure`、`is_online`、`type`（anytls）；
   - `getSubscribe` / `user/info` 返回的 `uuid` 就是节点密码，`is_online=0` 的可以过滤掉。

`tools/hongan_fetch.py` v2 已实现：登录/getSubscribe → 优先 `/user/server/fetch` 明文节点表；
失败时用 `uuid + 内置模板` 本地生成，`--discover` 用 mihomo 逐端口实测 anytls，`--verify` 实测一次。
它默认直连并屏蔽系统代理，要走代理用 `--proxy http://127.0.0.1:7890`；`API_BASE` 仍写死
`http://hn.luoyaccc.com/api/v1`，换面板需要改这一行。

## 4. 本机数据目录：YAML 的第二个入口

macOS 非沙盒时，`path_provider_foundation` 的 application support 是：

```text
~/Library/Application Support/com.hongan.seppd/
```

（path_provider 2.6.0 的 macOS 分支会在 `NSApplicationSupportDirectory` 后追加 bundle id；
若 app 被沙盒化，则位于 `~/Library/Containers/com.hongan.seppd/Data/Library/Application Support/com.hongan.seppd/`。
用下面的 `find` 一锤定音。）

目录里预期有：

```text
database.sqlite        # SQLite，未加密
shared_preferences.json # 可能出现（FlClash 风格自定义 prefs）
config.yaml            # 有效配置，加密
profiles/<id>.yaml     # 订阅原文，加密
honganCore.lock
GEOSITE.dat / GEOIP.dat / GEOIP.metadb / ASN.mmdb
```

### 4.1 从 DB 里取订阅 URL（只用于确认订阅/流量，不是明文 YAML）

`profiles` 表沿用 FlClash 结构（AOT 里能看到 `subscription_info`、
`auto_update_duration_millis`、`selected_map`、`overwrite_type`、`last_update_date`、
`current_group_name`，以及 `REFERENCES profiles (id) ON DELETE CASCADE`）：

```bash
APP="$HOME/Library/Application Support/com.hongan.seppd"
sqlite3 "$APP/database.sqlite" \
  "select id,label,url from profiles;"
```

若 `url` 是 `http...`，它确实就是面板订阅地址（带 token）；但**不要拿它当 YAML 源**：
它只认第 3 节那个官方 UA，且返回加密 base64，标准客户端解析不了。  
要明文节点，走 `/user/server/fetch`（第 3 节）或 `tools/hongan_fetch.py` v2。

注意：这个 URL 带订阅 token，等同于账号凭据；`<id>.yaml` 和 `config.yaml` 也是密文，
不要试图直接当 YAML 打开。

### 4.2 服务器地址 / JWT 在 prefs 里

macOS 的 `shared_preferences_foundation` 默认写 NSUserDefaults：

```bash
defaults read com.hongan.seppd 2>/dev/null | grep -iE 'api|token|server|subscribe'
```

若目录里存在 `shared_preferences.json`：

```bash
grep -iE 'api_base_url|auth_token|subscribe|server' \
  "$APP/shared_preferences.json"
```

- `api_base_url`：你填的面板地址
- `auth_token`：JWT（若存在，可直接调 `/user/getSubscribe`，不必再登录）
- 注意 Flutter 的 shared_preferences 会给 key 加 `flutter.` 前缀

### 4.3 备份/导出

AOT 里有 `Export file`、`backup.zip`、`exportFile`。FlClash 系备份通常是把数据目录打 zip；
`database.sqlite` 在 zip 里仍是明文 SQLite，所以即使 `profiles/*.yaml` 是密文，
也可以从备份里的 DB 读 `profiles.url`。是否真的导出明文 YAML 未在 macOS 上验证，标为未知；
优先用第 3 节的 `/user/server/fetch`，或 `tools/hongan_fetch.py` v2。

## 5. 运行期的有效配置（可选，进阶）

`honganCore` 的符号表里有 `main.handleSetupConfig`、`main.updateConfig`、
`main.handleGetConfig`、`main.startServer` 等；配置是 Dart 侧通过
`/tmp/honganCoreSocket_<随机>` 发给内核的，内核不读磁盘上的 `config.yaml`。
因此：

- 面板订阅 = 加密 base64（不是明文 YAML）
- 面板明文节点表 = `/user/server/fetch` 的 `host`/`port`/`server_name`/`insecure`/`is_online`
- app 的 `config.yaml` = 合并了 patch（DNS、mixed-port、分组等）后的有效配置，落盘加密
- 想要有效配置，只能走 app↔core 的 RPC（`getConfig`）或扫 `honganCore` 进程内存；
  Windows 版的 `_sub/memscan` 思路同样适用，但 macOS 需要 root/lldb，且不是拿 YAML 的最短路径

## 6. 推荐操作顺序

1. 先确认面板地址：登录页的「服务器地址」，或 `defaults read`/`shared_preferences.json` 里的 `api_base_url`。
   红岸已知地址：`http://hn.luoyaccc.com`。
2. 有账号密码/JWT：直接用 `tools/hongan_fetch.py` v2。它优先调 `/user/server/fetch` 拿**明文节点表**，
   这是目前最短、最可靠的路径；Windows 还可以 `--from-client` 免密码。
3. 面板 API 不可用：用上一次留下的 `hongan_template.json`（uuid + 端口模板）离线生成，
   或 `--from-file` 导入一份已有的完整 YAML；不要再去下载订阅 URL，它是加密的。
4. 想确认节点是否真活：`--discover`（mihomo 逐端口 anytls 实测）和 `--verify`（整份配置实测 204）。
5. 磁盘上的 `config.yaml`/`profiles/*.yaml` 是密文，别在这上面浪费时间；除非确实需要
   “有效配置”而不是“订阅原文”，才考虑 RPC/内存。

## 7. 未确认项

- `getSubscribe` 的 `Authorization` 已确认是**原始 JWT**（加 `Bearer ` 会 403）。
- 订阅接口的 UA 白名单已确认：`NetFlow/v2.2.8 clash-verge Platform/windows`，其他 UA 444。
- `/user/server/fetch` 在红岸面板上已由 v2 脚本验证；如果 macOS 版指向的是另一个 V2Board 部署，
  该端点是否开放、字段是否一致仍需在该面板上验一次。
- 订阅加密的算法/密钥仍未逆（也不需要）：明文节点表已经够用；`config.yaml`/`profiles/*.yaml`
  仍是密文。
- `profiles.url` 在 macOS 上是否 100% 明文：DB 是 SQLite，Windows 实测明文；但它指向的是加密订阅，
  不是明文 YAML。
- `Export file` 是否解密导出：未验证。

## 8. 凭据提醒

订阅 URL、`auth_token`、`uuid`、YAML 里的节点密码都是账号凭据。不要提交到仓库、不要贴到公开 issue；
仓库 `.gitignore` 已排除 `hongan_*.yaml`、`hongan_template.json`、`hongan_servers.json`、
`_sub_state.json`、`*session.json` 等文件名。
