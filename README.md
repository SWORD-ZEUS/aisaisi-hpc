# aisaisi-hpc

用于 Codex 等支持 `SKILL.md` 的智能体的爱赛思高性能计算技能。高性能计算（high-performance computing，HPC）指使用计算集群运行任务。本项目是非官方工具，面向[爱赛思科研工作台](https://ai4s.yicloud.com/workflow/task)，与 Inspire/启智平台分别使用。

提供正常登录、项目和作业查询、文件上传、远端命令执行、Slurm（集群作业调度系统）作业脚本生成与提交，以及 LogicMD 分子动力学（molecular dynamics，MD）的操作说明。

每位使用者通过自己的平台账号登录，选择自己有权限的项目。仓库不附带平台账号、会话文件、项目配置或计算资源；队友仍需由项目管理员加入相应平台项目。

## 安装

仓库地址：<https://github.com/SWORD-ZEUS/aisaisi-hpc>。

如果本机有 Codex 自带的技能安装器，可直接运行：

```bash
python3 "$HOME/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo SWORD-ZEUS/aisaisi-hpc --path skills/aisaisi-hpc \
  --dest "$HOME/.agents/skills"
```

将本目录下载或克隆到本机，在仓库根目录运行以下命令。目标目录统一使用 `~/.agents/skills`，便于 Codex 和读取该目录的其他智能体共用。

```bash
mkdir -p "$HOME/.agents/skills"
python3 - <<'PY'
from pathlib import Path
import shutil

source = Path('skills/aisaisi-hpc')
target = Path.home() / '.agents/skills/aisaisi-hpc'
if not (source / 'SKILL.md').is_file():
    raise SystemExit('请在仓库根目录运行安装命令')
if target.exists() or target.is_symlink():
    raise SystemExit(f'已有技能未覆盖：{target}；请先备份个人配置，再手动更新')
shutil.copytree(source, target)
print(f'已安装：{target}')
PY
```

安装后新开一次智能体会话，用 `$aisaisi-hpc` 调用。

## 环境

- Python 3.10 或更新版本；运行脚本使用标准库，无需安装 Python 软件包。
- 执行远端终端命令时需要 Node.js 24；脚本使用其原生 WebSocket（双向实时通信协议）。只通过网络接口查询项目、实例和作业时无需 Node.js。
- 提交和远端资源查询需要当前项目有可用的 WebSSH（浏览器中的命令行终端）实例；客户端不会自动创建实例。
- 通过直接 SSH（Secure Shell，安全外壳连接）操作时，需已有可用的连接配置。网页终端可用不代表平台提供直接 SSH 端口。

发布准备时的本地检查环境为 Python 3.14.7、Node.js 24.13.0。其他版本与队友账号尚需在各自环境确认。

## 第一次使用

会话文件包含访问令牌（access token，用于证明已登录的凭据），放在仓库之外，仅保存在使用者自己的机器。密码和验证码只在本地交互终端输入，不发送到聊天中。

```bash
mkdir -p "$HOME/.local/state/aisaisi-hpc"
chmod 700 "$HOME/.local/state/aisaisi-hpc"

python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" login --phone

python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" projects
```

`login --phone` 默认使用已有验证码；需要发送一次验证码时加 `--request-code`。账号密码登录使用 `login --username` 并填写实际用户名。已有有效会话直接复用；会话失效时按错误处理，不重复发送验证码或覆盖已有会话。

从项目查询结果中确认数值编号，把下列 `PROJECT_ID` 替换为该编号，再查询作业：

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_cli.py" \
  --session "$HOME/.local/state/aisaisi-hpc/session.json" \
  --project PROJECT_ID jobs
```

客户端不会自动选择同名项目，也不把一个人的目录或配额套用到其他账号。

可以对智能体说：

> 使用 $aisaisi-hpc，读取我指定的本机会话，列出我有权限的项目，再查看我选定项目中的作业和排队原因。

需要计算时给出项目、输入和程序路径、输出目录，以及 CPU（中央处理器）、GPU（图形处理器）、内存和时限的上限。智能体完成一次必要检查后按已有授权提交；不会为查询状态另建实验。

## 使用说明

- [技能入口与执行规则](skills/aisaisi-hpc/SKILL.md)
- [命令行登录、查询、上传和提交](skills/aisaisi-hpc/references/cli.md)
- [Slurm 作业、历史和日志](skills/aisaisi-hpc/references/slurm.md)
- [脚本生成器及已有 SSH 连接](skills/aisaisi-hpc/references/helper.md)
- [浏览器、实例与文件](skills/aisaisi-hpc/references/access-and-files.md)
- [LogicMD、续算与轨迹处理](skills/aisaisi-hpc/references/logicmd.md)
- [来源、接口与验证范围](skills/aisaisi-hpc/references/sources.md)

上传脚本默认加载同目录的客户端，技能可安装在其他位置。上传前检查同名文件，上传后核对文件名和字节数。该检查不能防止其他进程在同一时刻写入同名文件，应为每次任务使用独立目录。

## 本地检查与反馈

```bash
python3 -m unittest discover -s tests -v
node --check skills/aisaisi-hpc/scripts/aisaisi_ws.mjs
```

本地检查使用虚构数据，不登录平台、不上传文件、不提交计算。它们覆盖安装位置变化、文件覆盖保护和部分资源参数约束，不代表队友的账号、平台当前接口或科学结果已经验证。

反馈问题时提供使用版本、运行命令和去掉私人信息的错误。删除密码、验证码、访问令牌、完整终端连接地址、个人路径和未公开输入；不要上传会话文件、浏览器存储或原始平台响应。平台接口变化时，依据对应页面和真实错误修复；不会自动重复提交结果不明的任务。

## 许可证与第三方材料

本项目代码与自行编写的说明采用 [MIT License](LICENSE)。平台服务、LogicMD、平台脚本和第三方手册的权利分别归其权利人；本仓库不附带平台手册 PDF、平台程序或实验数据。手册的正式标题及获取入口见[来源说明](skills/aisaisi-hpc/references/sources.md)。
