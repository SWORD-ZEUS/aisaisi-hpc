# 本地辅助工具

`scripts/aisaisi_slurm.py` 使用 Python 标准库，生成单节点、单任务的 Slurm（集群作业调度系统）脚本；远端操作只使用已有 SSH（Secure Shell，安全外壳连接）别名。没有直接 SSH 时，用[平台客户端](cli.md)提交生成的脚本。

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" --help
```

## 生成普通作业

下面是语法示例，资源和路径须换成当前已确认、已授权的值；`render` 只生成文件，不运行科学计算。

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" render \
  --partition HPC --name case01 \
  --workdir /absolute/case01 --output ./case01.slurm \
  --nodes 1 --cpus-per-task 4 --gpus-per-node 0 \
  --mem 16G --time 02:00:00 --entry /absolute/case01/run.sh
```

`--entry` 是用户既有的 Bash（外壳命令解释器）入口脚本。生成器不更改程序或训练参数，也不选择资源。`--module` 指定已确认的软件模块，普通作业可重复指定。GPU（图形处理器）请求用 `--gpus-per-node`，写入 `--gres=gpu:N`。

`--gres` 接受一项通用资源（generic resources，GRES），格式为 `名称:数量` 或 `名称:类型:数量`，数量为正整数。使用它时须同时设置 `--gpus-per-node 0`。`--nodelist` 只接受一个当前已确认的节点名，不支持列表或范围。

## 生成 LogicMD 作业

以下 `slcau:slc512:1` 和 `logic-md/1.1.4.tcl` 仅表示已有实现支持的字段写法，不证明当前账号可用或具有配额。先在当前平台确认后再使用。

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" render \
  --partition MHPC --name md01 \
  --workdir /absolute/md01 --output ./md01.slurm \
  --nodes 1 --cpus-per-task 1 --gpus-per-node 0 \
  --gres slcau:slc512:1 --mem 3G --time 00:15:00 \
  --module logic-md/1.1.4.tcl --ctl /absolute/md01/md.ctl
```

续算增加 `--checkpoint` 并提供原版本可用的绝对路径，见 [LogicMD 说明](logicmd.md)。`MHPC` 拒绝普通 GPU 申请和其他程序入口，要求显式指定 LogicMD 模块。

输出文件已存在时停止，保留原文件。日志文件名包含作业编号；LogicMD 输出写入工作目录下新建的 `logic-md-$SLURM_JOB_ID`，已存在则停止。普通入口脚本须自行避免覆盖固定结果文件。生成器不支持作业数组（job array，一次提交多个相同结构的任务）或多节点启动；这些任务使用原生脚本。

## 已有 SSH 连接

以下 `existing-alias`、编号和路径都是示例，须替换为实际对象：

```bash
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" resources --host existing-alias
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" jobs --host existing-alias
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" job --host existing-alias 12345
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" logs --host existing-alias 12345 --lines 100
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" history --host existing-alias --start 2026-01-01 --job 12345
python3 "$HOME/.agents/skills/aisaisi-hpc/scripts/aisaisi_slurm.py" submit \
  --host existing-alias --workdir /absolute/case01 --script /absolute/case01/case01.slurm
```

`jobs`、`history` 默认限定连接账号；`logs` 从详细记录取得日志路径，每个文件默认末尾100行、上限1000行。日志已从控制器移除时，结合历史与项目记录定位。日期按远端环境和调度系统定义解释。

提交只调用一次 `sbatch --parsable`，结果不明先查记录，不自动重发。已授权取消明确作业时用 `cancel --host existing-alias 12345`；不支持按用户、分区或编号范围批量取消。数组主编号可能影响全部元素，须符合已授权范围。

远端默认等待30秒，可用 `--timeout` 调整。SSH 使用 `BatchMode=yes`（禁止交互式认证），保留主机验证行为。工具不配置登录，也不上传输入或判断科学参数是否正确。
