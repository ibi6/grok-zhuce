# Grok Auto Register 稳定性加固设计

## 目标

在不改变注册策略、不提高并发上限、不缩短人工验证等待的前提下，修复当前版本中已验证的并发写入、代理出口、Outlook OAuth 持久化、CPA 超时清理和日志泄密问题。

本次采用“稳定性优先”的 B 方案，覆盖确定性缺陷和必要测试，不进行大规模 GUI/CLI 架构重写。

## 范围

### 包含

1. 本地 grok2api Token 池使用跨进程文件锁和原子替换，避免并发写坏或丢失 Token。
2. 相对 Token 文件路径以项目目录为基准解析，支持 `token.json` 这种文件名。
3. 注册浏览器应用 `proxy` 配置；接口代理失败时不再静默直连。
4. Outlook OAuth 返回轮换后的 refresh token 时，原子写回原 TXT 或 CSV 凭证文件。
5. CPA 导出增加取消信号；超时后先请求取消并等待清理，禁止后台线程与下一轮浏览器操作并行。
6. GUI 和 CLI 日志不再输出完整邮箱 JWT、refresh token、access token 或密码。
7. `config.json` 使用原子保存；示例配置删除重复键并补齐实际公开配置项。
8. 补充 `paramiko` 运行依赖，使源码环境能够使用 CPA 服务器上传功能。
9. 为以上行为增加自动化测试。

### 不包含

1. 自动处理或绕过 Turnstile、人机验证。
2. 轮换代理、代理池或提高平台注册并发。
3. 大规模重构 3000 多行注册主流程。
4. 改变 CPA chat entitlement 的判定标准。
5. 自动清理服务器中已有的无权限 CPA 文件。

## 设计

### 1. 安全文件写入层

新增小型文件辅助函数，负责：

- 将相对路径解析到项目目录。
- 创建父目录，但正确处理只有文件名、父目录为空的情况。
- 使用同目录临时文件写入、刷新并通过 `os.replace()` 原子替换。
- 对 Token 池的完整“读取—合并—写入”过程使用 `filelock.FileLock`，锁文件放在目标文件旁边。

账号结果文件和纯 Token 追加文件继续采用追加模式，但并发模式下使用对应文件锁，避免多进程写入交叉。

### 2. 代理语义

`proxy` 表示注册主流程统一代理：临时邮箱 HTTP 请求和 Chromium 注册浏览器都使用它。`cpa_proxy` 仍然优先用于账号初始化、CPA OAuth 和 chat 探测。

Chromium 通过 DrissionPage 的代理配置接收 `proxy`。如果代理不可用，请求应明确失败并记录脱敏后的代理地址，不再自动回退直连。这样可以保证用户看到的配置与真实出口一致。

带用户名和密码的 Chromium 代理不在本次扩展范围内；日志只显示 `user:***@host:port`。

### 3. Outlook refresh token 持久化

`OutlookAccountPool` 保存凭证文件路径和格式信息。token exchange 返回新 refresh token 时：

1. 更新当前账号对象。
2. 在凭证文件锁内重新读取最新文件。
3. 只替换匹配邮箱的 refresh token。
4. 按原 TXT/CSV 格式原子写回。
5. 更新文件缓存标识，避免同一进程随后重新加载旧状态。

写回失败不隐藏：验证码流程继续使用当前 access token，但账号状态记录持久化失败，并在日志中给出不含 Token 的错误提示。

重复邮箱会在导入时被拒绝，避免池中租用账号与按邮箱查找账号不一致。

### 4. CPA 超时和取消

CPA 导出线程使用独立 `threading.Event`。传入 CPA mint 流程的取消回调同时检查用户停止状态和超时事件。

达到 `cpa_mint_timeout_sec` 后：

1. 设置取消事件。
2. 给予短暂清理窗口并再次 join。
3. 在后台线程真正结束前，不启动下一账号。
4. 如果浏览器调用无法及时响应取消，则关闭当前浏览器使页面操作退出，再完成线程回收。

CPA 结果只有在 chat probe 成功后才允许复制到热加载目录或上传服务器。失败凭证保留 `disabled` 标记用于诊断。

### 5. 日志与错误处理

统一增加凭证脱敏函数，覆盖：

- 邮箱服务 JWT。
- OAuth access/refresh token。
- 密码和 API Key。
- 带认证信息的代理 URL。

GUI、CLI、失败日志和异常预览统一使用该函数。账号输出文件仍按用户现有格式保存完整凭证，因为它是功能产物；界面会继续提示文件敏感。

### 6. 配置和依赖

`config.json` 通过原子替换保存，避免程序退出或磁盘异常留下半截 JSON。读取失败时保留原文件并输出明确错误，不静默覆盖。

`config.example.json` 补充 `concurrency`、浏览器模式和当前 CPA 开关，删除重复 `cpa_proxy`。`requirements.txt` 添加服务器上传实际使用的 `paramiko`。

## 测试

新增或扩展测试覆盖：

1. 20 个并发写入后 Token JSON 仍合法且 Token 不丢失。
2. `token.json` 相对路径能够正常写入项目目录。
3. 浏览器选项包含配置代理。
4. HTTP 代理失败不会再次直连请求。
5. Outlook TXT 和 CSV 都能持久化轮换后的 refresh token，且不改动其他账号。
6. 重复 Outlook 邮箱被拒绝。
7. CPA 超时触发取消并等待线程结束。
8. 日志中不出现原始 Token。
9. 配置原子保存后可重新解析。

完成后运行：

```powershell
python -m pytest -q
python -m compileall -q grok_register_ttk.py modern_ui.py outlook_mail.py cpa_export.py cpa_xai tests
pyinstaller --clean --noconfirm grok_register_ttk.spec
```

并对新 EXE 做启动冒烟测试。

## 验收标准

1. 原有 27 项测试继续通过，新测试全部通过。
2. 并发 Token 池压力测试不再出现 JSON 损坏或 Token 丢失。
3. Outlook refresh token 在进程重启后仍使用最新值。
4. 配置代理时，浏览器和接口均不发生静默直连。
5. CPA 超时后没有遗留导出线程继续操作浏览器。
6. GUI/CLI 日志不包含完整敏感凭证。
7. PyInstaller 构建成功，EXE 能启动。
