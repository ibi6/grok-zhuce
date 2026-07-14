# CPA 管理 API 自动上传设计

## 目标

在 CPA xAI 认证文件生成并通过现有可用性探测后，使用 CLIProxyAPI/CPA 官方管理 API 自动上传认证 JSON，使服务器立即热加载新账号。上传失败不得丢失本地认证文件，也不得把已完成注册的账号改判为注册失败。

## 已确认的 CPA 接口

- 上传接口：`POST /v0/management/auth-files?name=<filename.json>`
- 鉴权：`Authorization: Bearer <management key>`
- 请求体：认证文件原始 JSON，`Content-Type: application/json`
- 成功条件：HTTP 200 且响应 JSON 的 `status` 为 `ok`
- 连接测试：`GET /v0/management/auth-files`
- CPA 远程管理必须启用 `remote-management.allow-remote` 并配置 `secret-key`

## 配置

新增配置项：

- `cpa_management_auto_upload`：是否在 CPA 导出成功后自动上传。
- `cpa_management_base_url`：CPA 服务根地址或管理 API 地址。
- `cpa_management_key_encrypted`：Windows DPAPI 加密后的管理密钥。
- `cpa_management_timeout_sec`：单次请求超时，默认 20 秒。
- `cpa_management_retry_count`：瞬时失败重试次数，默认 3 次。

环境变量 `CPA_MANAGEMENT_KEY` 的优先级高于本地加密配置，便于无人值守运行和密钥轮换。`config.json` 不保存明文管理密钥。

## URL 规范化与传输安全

用户可以填写：

- `https://cpa.example.com`
- `https://cpa.example.com/v0/management`
- `https://cpa.example.com/v0/management/auth-files`

客户端统一规范化到 `/v0/management/auth-files`。

远程地址默认必须使用 HTTPS。仅 `127.0.0.1`、`localhost` 和 `::1` 允许 HTTP，便于本机调试。TLS 证书验证始终开启，界面不提供“忽略证书错误”开关。

## 密钥保护

- GUI 中的管理密钥使用密码框显示。
- 勾选保存时，使用 Windows DPAPI 当前用户范围加密，再写入 `config.json`。
- 未勾选保存时，密钥只保留在当前进程内存中。
- 环境变量和解密后的密钥不得写入日志、异常文本或请求 URL。
- 日志只显示脱敏后的 CPA 主机和认证文件名。

## 上传流程

1. CPA 本地认证文件生成成功。
2. 现有 chat 权限探测通过。
3. 检查自动上传开关、管理地址和管理密钥。
4. 校验文件是普通 `.json` 文件、大小不超过 2 MiB，文件名只取 basename。
5. 解析 JSON，拒绝空文件或无效 JSON。
6. 以原始 JSON 为请求体调用管理 API。
7. HTTP 200 且 `status=ok` 时记录上传成功。
8. 本地文件始终保留。

CPA 的管理接口负责 JSON 格式解析、写入认证目录和运行时热加载，客户端不再直接操作服务器文件系统。当前 CPA 接口使用服务端直接写入；客户端以成功响应作为写入完成信号，不额外宣称服务端具备原子替换语义。

## 重试和错误处理

以下情况最多重试配置次数，间隔为 1 秒、2 秒、4 秒：

- 网络连接错误或请求超时。
- HTTP 408、429。
- HTTP 500–599。

以下情况不重试：

- HTTP 400：文件名或 JSON 无效。
- HTTP 401：管理密钥缺失或错误。
- HTTP 403：远程管理未开启、来源被拒绝或 IP 被临时封禁。
- 其他明确的 4xx 配置错误。

最终失败时，结果增加 `management_upload_error`，GUI 日志提示本地文件仍已保存。上传失败不增加注册失败计数。

## GUI

在“CPA 与 Token”页面的 CPA 卡片中增加：

- “自动上传到 CPA 管理 API”开关。
- CPA 管理地址输入框。
- Management Key 密码框。
- “加密保存管理密钥”开关。
- “测试连接”按钮及状态提示。

测试连接在后台线程执行，期间按钮显示“测试中”，完成后恢复。测试仅调用只读列表接口，不上传或删除文件。

## 旧 SFTP 配置兼容

- 当 `cpa_management_auto_upload=true` 时，只使用管理 API，不再执行 SFTP，避免同一文件重复上传。
- 当管理 API 未启用而旧配置包含 `cpa_server_host` 时，保留现有 SFTP 行为，并在日志中提示该方式已进入兼容模式。
- 不在新 GUI 中新增 SFTP 配置入口。

## 模块边界

新增独立模块 `cpa_management.py`，负责：

- URL 规范化与 HTTPS 校验。
- DPAPI 密钥加密和解密。
- 连接测试。
- 文件校验和上传。
- 状态码分类、重试和错误脱敏。

`cpa_export.py` 只在导出成功后调用该模块；`modern_ui.py` 只负责收集配置和显示状态，避免把网络和密钥逻辑堆入 GUI。

## 测试与验收

- 根地址、管理地址和完整上传地址都能正确规范化。
- 远程 HTTP 地址被拒绝，本机 HTTP 地址允许。
- 管理密钥不会出现在日志和异常中。
- 密钥能够通过 DPAPI 加密、解密，错误用户或损坏密文返回安全错误。
- 测试连接使用 GET 和 Bearer 鉴权。
- 上传使用 POST、JSON 请求体和安全文件名。
- 200 成功；401/403/400 不重试；429、5xx 和网络超时按规则重试。
- 上传失败仍保留本地文件，且不影响注册成功统计。
- API 模式启用时不会重复调用旧 SFTP 上传。
- GUI 测试连接异常后按钮能够恢复。
- 全量测试、Python 编译、PyInstaller 构建和 EXE 启动冒烟全部通过。

## 非目标

- 修改 CPA 服务端管理 API。
- 绕过 CPA 的远程管理限制或 TLS 校验。
- 自动创建或修改 CPA 的 management key。
- 自动删除、覆盖回滚或批量清理服务器认证文件。
- 将管理密钥上传到任何第三方服务。
