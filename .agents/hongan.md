# 红岸（HongAn）补丁

本仓库在上游 FlClash 之上加红岸面板支持。为了 `git merge upstream/main` 一直可做，红岸逻辑必须留在少数自有文件里；
对上游文件的修改只允许是下面列出的路由行。

## 红岸代码在哪

| 文件 | 内容 |
|---|---|
| `lib/common/hongan.dart` | 面板 API（登录、订阅、节点表）、账号模型、Clash 配置生成、账号持久化 `honganAccounts`、`createHonganProfile` / `refreshHonganProfile` |
| `lib/views/profiles/hongan.dart` | 账号导入对话框 |
| `test/common/hongan_test.dart` | 节点解析与配置生成的测试 |

## 允许改的上游文件

| 文件 | 改动 |
|---|---|
| `lib/bootstrap.dart` | 启动时 `await honganAccounts.load();` |
| `lib/common/common.dart` | `export 'hongan.dart';` |
| `lib/common/constant.dart` | `repository` 指向本仓库（应用内更新检查） |
| `lib/providers/actions/profiles.dart` | `updateProfile` 把红岸 profile 路由到 `_syncHonganProfile`；`deleteProfile` 清账号；`addHonganProfile`、`_syncHonganProfile`、`_finishProfileUpdate` |
| `lib/views/profiles/add.dart` | 菜单项与 `_toHongan` |
| `lib/views/profiles/profiles.dart` | 三处判断：放行红岸 profile 刷新、显示用量、显示刷新菜单项 |
| `test/widgets/profile_focus_test.dart` | 用量显示用例 |

加新逻辑时先放 `lib/common/hongan.dart`；只有需要 `ref`、provider 或导航时才碰上面这些文件，并保持一跳。

## 不要做的事

- 不要在 `Preferences` 里加红岸字段。账号表由 `honganAccounts` 自己读写 `SharedPreferences`，
  `lib/common/preferences.dart` 必须与上游逐字一致。
- 不要裁 `build.yaml` 的发布矩阵。`test/tool/release_contract_test.dart` 把它当发布契约，站点脚本、release notes
  模板和应用内更新器都按它核对文件名；要动先读那个测试。
- 不要把红岸代码、密钥或面板地址提交到官方 `chen08209/FlClash`。

## 版本与发布

- `.upstream-version` 记录当前上游版本，`pubspec.yaml` 的 app version 必须与它一致（`tool/fork_version.sh` 对齐）。
- tag 形如 `vX.Y.Z-honganBeta`、`vX.Y.Z-honganBeta.0.0.N[+M]`，CI 用 `tool/check_fork_version.sh` 校验。
- CI 相对上游的差异都带 `# fork:` 注释，`grep -rn "# fork:" .github/workflows/` 可全部列出；同步上游时只需解决这些点。
