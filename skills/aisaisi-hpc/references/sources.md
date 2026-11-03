# 来源与适用范围

## 平台材料

平台入口为 <https://ai4s.yicloud.com/workflow/task>。从已加入项目的「高性能计算 → 手册」菜单获取对应版本资料。仓库保留来源名称，不分发平台手册、平台脚本或软件；平台资料的再分发授权未在本项目中确认。

原技能记录的参考材料为：

- 《智爱赛思平台-高性能计算-使用说明》，V1.0。其 §3.1—§3.5 涉及项目访问、作业、文件、实例和手册。原记录指出封面与修订表年份不一致，本项目不推断其实际发布日期。
- 《Alpha Dynamics 平台 Logic MD 使用手册》，v1.1.4，平台文件名为 `Alpha Dynamics平台 Logic MD用户手册_v1.1.4.pdf`。用于确认对应版本的功能、控制文件与运行要求；不代表当前平台仍提供该版本或支持任意恒 pH 方法。

本公开版未重新阅读这两份手册全文；涉及手册的内容来自原技能的来源记录。当前执行以使用者取得的对应版本资料和实际帮助为准，不引用未重新核对的具体页码或体系规模限制。

## 通用命令与运行环境

以下为2026-11-03核对的官方文档，用于解释对应通用能力；平台安装版本的帮助仍为实际执行依据。

- [Slurm Workload Manager - sbatch](https://slurm.schedmd.com/sbatch.html)：批处理脚本、资源请求和提交语义。
- [Slurm Workload Manager - scontrol](https://slurm.schedmd.com/scontrol.html)：作业和调度配置查询。
- [gmx grompp - GROMACS 2025.2 documentation](https://manual.gromacs.org/2025.2/onlinehelp/gmx-grompp.html)：拓扑预处理与警告参数。
- [File formats - GROMACS 2025.2 documentation](https://manual.gromacs.org/2025.2/reference-manual/file-formats.html)：轨迹文件内容与格式。
- [Global objects | Node.js Documentation](https://nodejs.org/api/globals.html#class-websocket)：原生 WebSocket（双向实时通信协议）能力。

## 客户端接口来源

脚本按爱赛思网页前端使用的请求协议编写，不附带前端源码。原技能记录的协议核对日期为2026-10-12；这些是实现所依据的接口，不代表平台承诺长期兼容的公开应用程序接口（Application Programming Interface，API）。

| 用途 | 路径 |
| --- | --- |
| 正常登录 | `/dapi/v1/iam/login` |
| 请求登录验证码 | `/dapi/v1/iam/sendVerifyCode` |
| 工作台项目列表 | `/dapi/v1/bff/users/projects` |
| 底层资源项目列表 | `/dapi/v1/res/projects` |
| 当前项目实例列表 | `/hpc-portal/pod/v1/ListDeploy` |
| 当前项目作业列表 | `/hpc-portal/job/v1/ListJob` |
| 终端 WebSocket | `/hpc-portal/pod/v1/TerminalWs` |
| 目录列表 | `/hpc-portal/file/v1/List` |
| 文件上传 | `/hpc-portal/file/v1/BatchUpload` |

高性能计算请求显式携带 `X-GW-CUR-PID` 项目字段；HTTP（超文本传输协议）认证使用正常登录取得的凭据。终端使用 `resize`、`command` 消息，带认证信息的完整连接地址不输出或保存到交付文件。

## 验证范围

原技能的私人运行记录报告过正常登录、项目映射、实例与作业查询、远端命令、上传和原生提交，以及部分普通计算的完成结果。私人账号、项目、路径和作业记录不随本仓库分发，这些记录也不证明其他账号可用。

本公开版的本地检查覆盖脚本加载和语法、安装位置变化、拒绝覆盖、部分资源参数约束和相对文档链接。未重新登录平台、上传文件或提交计算。LogicMD 模拟完成、续算、轨迹合并、直接 SSH 操作和团队环境可用性没有在本次发布准备中重新验证。

出现接口错误时，检查对应页面和真实错误，修改受影响部分；不以历史记录替代当前权限、配额或作业状态，不为验证客户端而额外提交科学实验。
