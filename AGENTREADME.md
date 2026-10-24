# AGENTREADME：让 Agent 在本机部署 Telegram-Flow

这份文档写给 coding agent（Codex、Claude Code、Cursor 等）。用户只需要对 agent 说：

> 按照 Telegram-Flow 仓库里的 AGENTREADME.md，在我电脑上部署并接入我的 Telegram。

agent 照下面的步骤顺序执行，每一步先确认“成功判据”再继续。整个过程只有 5 处需要用户本人提供信息，见[需要用户提供的内容](#需要用户提供的内容)；其余步骤由 agent 自动完成。

面向人的介绍、功能说明和使用前须知见 [README.md](README.md)；修改代码前读 [AGENTS.md](AGENTS.md)。

## 规则

部署全程遵守以下规则，优先级高于后面任何步骤。

1. **只在用户这台电脑上运行。** 不要部署到其他服务器、云主机或远程 Docker 上下文。
2. **不泄露凭据。** `data/` 目录、访问口令、`api_hash`、验证码和两步验证密码都不能出现在对话、日志摘要、截图或 Git 提交里。启动脚本的输出含访问口令，一律重定向到 `data/start.log`（`data/` 已被 Git 和镜像构建排除）。不要用 `cat` 显示这个文件。
3. **不擅自改动用户的 Telegram 账号。** 本流程只读取账号已加入的频道和群组。除非用户明确要求，不要调用 `/api/join`、`/api/leave`，也不要在页面里点「加入」。
4. **遇到 Telegram 限流就等待。** 看到 `FloodWait`、HTTP 429 或 `retry_after` 大于 0 时，等待提示的秒数后再继续，不要并发或频繁重试。
5. **每步验证。** 同一步连续失败 3 次后停止，把命令、错误信息（去掉凭据）和已尝试的办法报告给用户。

## 流程总览

| 步骤 | 做什么 | 成功判据 |
| --- | --- | --- |
| 1 | 检查 Docker | `docker compose version` 和 `docker info` 都成功 |
| 2 | 获取代码 | 项目目录里有 `compose.yaml` |
| 3 | 构建镜像 | `docker image inspect local/tg-feed:0.1.0` 成功 |
| 4 | 收集 API 凭据 | 用户提供了 `api_id` 和 `api_hash` |
| 5 | 登录 Telegram | 输出 `已登录：`，且 `data/telegram.session` 非空 |
| 6 | 启动服务 | `admin status` 显示 `configured` 和 `ready` 都为 `true` |
| 7 | 选择来源并同步 | `admin wait` 退出码为 0 |
| 8 | 打开页面并交付 | 浏览器打开本机页面，用户能看到内容 |

下文命令中，`sh` 代码块用于 macOS 和 Linux 终端，`powershell` 代码块用于 Windows PowerShell。除第 1 步外，所有命令都在项目根目录执行。

## 需要用户提供的内容

| 时机 | 内容 | 说明 |
| --- | --- | --- |
| 第 1 步（如缺 Docker） | 是否同意安装 Docker Desktop | 安装软件前必须征得同意 |
| 第 4 步 | `api_id`、`api_hash` | 用户登录 [my.telegram.org](https://my.telegram.org) → API development tools 创建；agent 不能代为登录这个网站 |
| 第 5 步 | 手机号 | 国际格式，例如 `+8613800000000` |
| 第 5 步 | 登录验证码 | Telegram App 里收到的 5 位数字，几分钟内有效 |
| 第 5 步 | 两步验证密码 | 仅在账号开启了两步验证时需要 |
| 第 7 步 | 选择哪些来源 | 从 agent 列出的频道和群组里挑选 |

收到验证码和密码后直接写入登录程序，不要保存到文件或回显给用户。

## 第 1 步：检查 Docker

```sh
docker compose version
docker info --format '{{.ServerVersion}}'
```

**成功判据**：两条命令都有版本号输出。

**失败处理**：

- 找不到 `docker` 命令：先征得用户同意，再安装。macOS 用 `brew install --cask docker`，Windows 用 `winget install Docker.DockerDesktop`，Linux 按 [Docker Engine 官方文档](https://docs.docker.com/engine/install/) 安装 Engine 和 Compose 插件。Docker Desktop 首次启动需要用户在界面上点同意，安装后请用户打开一次。
- `docker info` 报无法连接守护进程：Docker 没启动。macOS 运行 `open -a Docker`，Windows 运行 `Start-Process "Docker Desktop"`，Linux 运行 `sudo systemctl start docker`。每 10 秒重试一次，最多等 2 分钟。
- Linux 报权限不足：请用户把自己加入 `docker` 组，或者在命令前加 `sudo`。

## 第 2 步：获取代码

如果当前目录已经有 `compose.yaml` 和 `telegram_flow/`，说明代码已经在了，跳过这一步。否则：

```sh
git clone https://github.com/YangNuoCheng/Telegram-Flow.git
cd Telegram-Flow
```

**成功判据**：项目目录里有 `compose.yaml`、`Dockerfile`、`login.py`。

**失败处理**：clone 超时或连接被重置时，检查网络和代理设置后重试；也可以在仓库页面下载 ZIP 解压，再进入解压后的目录继续。

## 第 3 步：构建镜像

```sh
docker compose build
docker image inspect local/tg-feed:0.1.0 --format '{{.Architecture}}'
```

**成功判据**：第二条命令输出 `arm64` 或 `amd64`。

**失败处理**：下载依赖超时就重试一次；仍然失败时，检查网络和代理设置（`HTTP_PROXY` / `HTTPS_PROXY`）后再试。

## 第 4 步：收集 API 凭据

先检查是否已经登录过：

```sh
test -s data/config.json && test -s data/telegram.session && echo already-logged-in
```

```powershell
if ((Test-Path data/config.json) -and (Test-Path data/telegram.session)) { 'already-logged-in' }
```

输出 `already-logged-in` 时，直接跳到第 6 步。

否则请用户完成以下操作，然后把结果告诉你：

1. 用浏览器打开 <https://my.telegram.org>，用手机号登录。
2. 进入 **API development tools**，随便填写应用名称和简称，创建应用。
3. 复制 `App api_id`（一串数字）和 `App api_hash`（32 位十六进制字符）。

**成功判据**：`api_id` 全部是数字，`api_hash` 是 32 位十六进制字符。不要把 `api_hash` 复述给用户。

## 第 5 步：登录 Telegram

登录程序是交互式的，依次出现下面的提示。如果 `data/config.json` 已经存在（例如之前登录到一半），前两个提示会被跳过。

| 提示 | 输入 |
| --- | --- |
| `api_id: ` | 第 4 步的 `api_id` |
| `api_hash（输入不回显）: ` | 第 4 步的 `api_hash` |
| `Please enter your phone (or bot token): ` | 用户的手机号 |
| `Please enter the code you received: ` | 这时才请用户提供验证码 |
| `Please enter your password: ` | 只在开启了两步验证时出现 |

运行登录程序：

```sh
docker compose run --rm --no-deps tg-feed python login.py
```

如果 agent 能操作交互式终端（PTY），就在对应提示出现后写入答案。验证码在输入手机号后才会发送，这时再向用户要。如果 agent 不能操作交互式终端，就把上面这条命令交给用户，请用户在自己的终端里运行，完成后告诉你。

**成功判据**：输出以 `已登录：` 开头，并且下面的检查输出 `ok`：

```sh
test -s data/telegram.session && echo ok
```

```powershell
if ((Get-Item data/telegram.session).Length -gt 0) { 'ok' }
```

**失败处理**：

| 错误 | 处理 |
| --- | --- |
| `PhoneNumberInvalidError` | 手机号要带 `+` 和国家码，重新运行 |
| `PhoneCodeInvalidError` / `PhoneCodeExpiredError` | 重新运行，请用户提供最新收到的验证码 |
| `PasswordHashInvalidError` | 两步验证密码错误，请用户重新输入 |
| `ApiIdInvalidError` | 凭据有误：删除 `data/config.json`，回到第 4 步 |
| `FloodWaitError` | 按提示的秒数等待后再试，告诉用户需要等多久 |

## 第 6 步：启动服务

```sh
./start.sh > data/start.log 2>&1
docker compose exec -T tg-feed python -m telegram_flow.admin status
```

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 *> data\start.log
docker compose exec -T tg-feed python -m telegram_flow.admin status
```

**成功判据**：启动命令退出码为 0；`status` 输出里 `configured` 和 `ready` 都是 `true`。服务刚启动时 `ready` 可能是 `false`，每 5 秒查一次，最多等 1 分钟。

**失败处理**：

- 端口 8978 被占用：用 `lsof -i :8978`（macOS/Linux）或 `Get-NetTCPConnection -LocalPort 8978`（Windows）查出占用端口的程序，请用户决定是关掉它，还是改 `compose.yaml` 里的端口。
- `configured` 为 `false`：还没有登录，回到第 4 步。
- `ready` 一直是 `false`：运行 `docker compose logs --tail 80 tg-feed` 查看日志。如果日志提示会话失效，先运行 `./stop.sh` 或 `.\stop.ps1`，再回到第 5 步重新登录。

## 第 7 步：选择来源并同步

列出账号已加入的频道和群组：

```sh
docker compose exec -T tg-feed python -m telegram_flow.admin channels
```

输出是一个 JSON 数组，每项包含 `id`、`title`、`kind`、`selected`。把标题列表整理给用户，请用户选择要看的来源。如果用户只说了兴趣方向，就按标题推荐几个候选，请用户确认后再选中。

选中来源（这一步会整体替换之前的选择）并等待首次同步：

```sh
docker compose exec -T tg-feed python -m telegram_flow.admin select <id1> <id2> <id3>
docker compose exec -T tg-feed python -m telegram_flow.admin wait --timeout 900
```

**成功判据**：`select` 返回的 `selected` 等于选中的个数；`wait` 退出码为 0，最后一行的 `cards` 大于 0。

**失败处理**：

- `wait` 超时，并且 `retry_after` 大于 0：Telegram 在限流。告诉用户需要等待的时间，等待后重新运行 `wait`。
- `wait` 超时，并且 `cards` 一直是 0：选中的来源里可能没有图片或视频，请用户换几个来源。
- 用户想看的频道不在列表里：请用户先在 Telegram App 里加入这个频道，再重新运行 `channels`。只有用户明确要求时，才能代为加入。

## 第 8 步：打开页面并交付

用默认浏览器打开本机链接。下面的命令直接从日志里取出链接并打开，不会把口令显示出来：

```sh
url=$(grep -o 'http://127\.0\.0\.1:8978/?k=[A-Za-z0-9_-]*' data/start.log | head -n 1)
open "$url" 2>/dev/null || xdg-open "$url"
```

```powershell
$url = (Select-String -Path data\start.log -Pattern 'http://127\.0\.0\.1:8978/\?k=[\w-]+').Matches[0].Value
Start-Process $url
```

然后告诉用户：

- 页面已经在浏览器里打开。上下滑动切换内容，双击表示喜欢，「没兴趣」用来隐藏。
- 手机和平板要连接和电脑相同的 Wi-Fi，在电脑页面点「手机」扫码。
- 停止服务用 `./stop.sh` 或 `.\stop.ps1`，再次启动用 `./start.sh` 或 `.\start.ps1`，数据会保留。
- 偏好学习只看文字、标签和来源，不识别画面内容；所有设备共用一份记录。详见 README 的[使用前须知](README.md#使用前须知)。

**最终验收**：

- [ ] `admin status` 显示 `ready: true`、`channels` 大于 0、`cards` 大于 0
- [ ] 本机浏览器能看到内容流
- [ ] `git status --short` 里没有 `data/` 下的文件
- [ ] 对话里没有出现访问口令、`api_hash`、验证码或密码

## 之后的维护

| 任务 | 命令 |
| --- | --- |
| 更新到最新代码 | `git pull`，然后重新运行第 6 步 |
| 查看状态 | `docker compose exec -T tg-feed python -m telegram_flow.admin status` |
| 更换来源 | 重新运行第 7 步 |
| 查看日志 | `docker compose logs --tail 80 tg-feed` |
| 换到另一台电脑 | 先停止服务，再连同 `data/` 一起复制整个项目目录，在新电脑上从第 1 步开始，第 4、5 步会自动跳过 |
| 彻底退出登录 | 在 Telegram「设置 → 设备」里结束这个会话，再删除 `data/telegram.session` |
