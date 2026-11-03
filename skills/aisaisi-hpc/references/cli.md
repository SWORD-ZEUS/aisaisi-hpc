# 本地命令行客户端

`scripts/aisaisi_cli.py` 使用 HTTP（超文本传输协议）接口查询项目、实例和作业，通过 WebSocket（双向实时通信协议）执行远端命令。网络查询使用 Python 标准库，终端传输使用同目录的 `aisaisi_ws.mjs` 和 Node.js 24。客户端复用项目已有的 WebSSH（浏览器中的命令行终端）实例，不自动创建、续期或释放实例。

## 登录与会话

先在仓库之外准备私有会话目录；以下示例使用 `~/.local/state/aisaisi-hpc`。已有有效会话时直接复用。全局参数放在子命令前。

```bash
mkdir -p "$HOME/.local/state/aisaisi-hpc"
chmod 700 "$HOME/.local/state/aisaisi-hpc"
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" login --phone
```

密码、手机号和验证码在本地交互终端输入。账号密码登录改用 `login --username` 并提供真实用户名。手机登录默认使用已有验证码；用户明确需要发送时加 `--request-code`，只发送一次。首次登录需在网页完成的流程由使用者处理，客户端不代为注册或接受条款。

访问令牌（access token，用于证明已登录的凭据）写入显式会话文件，文件权限为 `0600`（仅当前用户可读写），不会覆盖已有文件。重新登录需要新的文件路径，确认后续命令使用新会话；失效文件由用户按其本地管理方式处理。会话不存密码，不读取浏览器 Cookie（浏览器保存的会话数据）。

也可通过 `--token-env AISAISI_TOKEN` 读取用户明确提供的环境变量；不要打印变量或把令牌填入命令行参数。`--origin` 默认为 `https://ai4s.yicloud.com`，只接受不带账号、路径和查询参数的 HTTPS（加密超文本传输协议）站点地址。会话所属站点须与本次站点一致。

## 选择项目并查询

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" projects
```

确认查询结果中的数值 `id`，不要用项目显示名代替。下列 `PROJECT_ID` 和 `JOB_ID` 为说明用的占位符，执行前替换为实际数值；不直接运行未替换的命令。

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID instances
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID jobs
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID job JOB_ID
```

`jobs` 默认读取10条，可用 `--offset`、`--limit`、`--state`、`--start`、`--end` 缩小范围。接口返回账号当前有权限查看的项目内容，不保证所有可见作业都由本人提交。作业操作须确认具体对象和授权；状态码保持平台定义。

`job` 经终端执行 `scontrol show job`，`resources` 经终端执行 `sinfo --long`。这两项需要可用的既有终端；查询作业列表不需要直接 SSH（安全外壳连接）端口。

## 远端命令与提交

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID \
  exec --command 'pwd'

python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID \
  submit --workdir /absolute/current-run --script /absolute/current-run/job.slurm
```

路径和项目编号换成当前实际值。终端合并返回标准输出和标准错误，通过独立完成标记读取命令退出码。等待超时或连接断开时，远端程序可能仍继续；客户端不会自动重发。

提交前检查远端工作目录和脚本可访问、Bash（外壳命令解释器）语法可解析，再调用一次 `sbatch --parsable --chdir=...`。收到作业编号表示已提交，随后按需查看队列、日志和输出。结果不明先按名称、时间和目录查作业。复杂命令使用已保存的远端脚本，避免把多个输入文件编码进很长的终端命令。

## 上传文件

`scripts/aisaisi_upload.py` 默认加载同目录的 `aisaisi_cli.py`，也支持用 `--cli` 指定其他位置。先在终端中准备本次独立目录，并确认文件页面路径与计算节点绝对路径的对应关系；两者不能直接等同。

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_upload.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID \
  --remote-dir /current-independent-directory --list

python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_upload.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" --project PROJECT_ID \
  --remote-dir /current-independent-directory --timeout 60 \
  /local/input.mdp /local/job.slurm
```

上传前读取目标目录，存在同名文件时拒绝上传；上传后核对文件名和字节数，不计算文件摘要。接口没有已确认的“仅创建”原子操作保证，目录查询与上传之间仍可能被其他进程写入，应避免共用输出目录。每次上传上限为256 MiB（兆二进制字节）；大文件使用平台文件页面或已有传输入口。

`--list` 只查询目录，不能同时指定文件。客户端不自动创建目标目录，上传超时或响应不明后先查询目录，不重复上传。

## 接口范围

实现依据平台前端使用的接口协议；接口可能随平台更新变化，详见[来源与适用范围](sources.md)。网络请求不跟随重定向，认证信息不放进命令行参数或输出中。任意远端命令仍可能打印用户文件，输出内容需按实际命令管理。

未封装项目加入、账号注册、权限修改、实例创建、文件下载或管理员接口。模板作业的接口不等于任意原生脚本提交接口，原生脚本通过终端执行 `sbatch`。
