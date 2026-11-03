# Slurm 作业提交与观察

Slurm 是集群作业调度系统。下列命令在平台终端或已有远端连接中运行；以当前集群帮助和用户权限为准。

## 资源与环境

首次选择资源或环境发生变化时，集中读取本次需要的信息：

```bash
sinfo -o '%P %a %l %D %t %c %m %G'
scontrol show partition HPC
module avail
```

各列依次为分区、可用性、时限、节点数、节点状态、每节点 CPU（中央处理器）数量、内存和通用资源（generic resources，GRES）。资源可见不等于当前账号有权申请，实际选择须符合已有授权和当前平台规则。

`HPC` 用于普通计算；平台手册将 `MHPC` 定义为 LogicMD 专用分区。公共工具曾使用 `/shared_tools`；只读取当前存在且本次需要的文件。软件模块（environment module，用命令选择已安装软件版本）以 `module avail`、`module show` 和适用的成功记录为准，不默认安装或修改全局环境。

## 提交

使用本次独立工作目录，确认程序向该目录写结果。资源申请说明节点数、任务数、每任务 CPU、每节点 GPU（图形处理器）、内存和最长时间。单节点生成器见[工具用法](helper.md)，多节点计算须使用适合程序的原生脚本及实际并行启动方式。

`#SBATCH` 行不展开外壳变量，应填写具体值；第一条可执行命令之后不再放调度指令。`--exclusive`（独占节点资源）通常申请节点全部 CPU 和通用资源，普通作业按实际需求申请，内存仍需单独指定。[Slurm Workload Manager - sbatch](https://slurm.schedmd.com/sbatch.html)

```bash
sbatch --parsable --chdir=/absolute/current-run /absolute/current-run/job.slurm
```

路径替换为本次实际目录。`--parsable` 返回作业编号，可能附带分号分隔的集群名；收到编号表示已提交。超时、断连或返回不明时，先按名称、时间和目录查已有作业，不自动重发。

程序线程、并行进程和设备使用应与申请一致。在授权范围内并行处理独立样本，不擅自修改模型、数值精度或数据划分，不为寻找理论最优参数重复实验。

## 查询、历史与日志

`JOB_ID` 是需要替换的实际编号，只查询本账号或用户指定的对象：

```bash
squeue -u "$USER" -o '%.18i %.24j %.12P %.12T %.12M %.8D %R'
scontrol show job JOB_ID
sacct -j JOB_ID --format=JobID,JobName,State,ExitCode,Elapsed,AllocCPUS,ReqMem,MaxRSS
```

分别读取队列、详细记录和历史。详细记录中的 `WorkDir` 是工作目录，`StdOut`、`StdErr` 是标准输出与标准错误路径。按实际路径有限读取日志，如 `tail -n 100 -- /actual/log/path`。[Slurm Workload Manager - scontrol](https://slurm.schedmd.com/scontrol.html)

| 状态 | 可报告的事实 | 下一步 |
| --- | --- | --- |
| `PENDING`（排队） | 作业已提交，尚未获准运行 | 看排队原因，不自动取消重提 |
| `RUNNING`（运行中） | 调度系统已分配资源并开始作业 | 查看日志确定用户程序进展 |
| `COMPLETED`（调度完成） | 调度系统记录作业完成 | 核对退出码、程序完成记录和所需输出 |
| `FAILED`（失败） | 作业失败 | 处理日志中的直接错误 |
| `OUT_OF_MEMORY`（内存不足）或 `TIMEOUT`（超时） | 达到相应限制 | 在授权范围内调整受影响部分 |
| `CANCELLED`（已取消） | 作业被取消 | 保留已有输出及续算文件 |

作业离开队列后查历史和日志。历史服务不可用或无权限时说明覆盖范围，再根据程序输出判断。质量检查使用任务需要的指标，如实际步数、轨迹时间范围、成功样本数或训练完成记录；不因状态查询另建计算环境。

## 取消

按用户已有授权执行 `scancel JOB_ID`，或完成网页对应作业行的终止操作；不用按用户或分区取消全部作业的命令替代明确编号。取消后查看实际状态，保留输出。
