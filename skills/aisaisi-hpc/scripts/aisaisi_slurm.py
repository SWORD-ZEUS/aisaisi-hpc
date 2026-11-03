#!/usr/bin/env python3
"""生成和操作智爱赛思 Slurm（集群作业调度系统）作业，使用 Python 标准库。"""

import argparse
import datetime as dt
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


class CommandError(Exception):
    """面向使用者的输入或执行错误。"""


class ChineseParser(argparse.ArgumentParser):
    """保留标准参数解析，同时用中文显示帮助和常见错误。"""

    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"
        self.add_argument("-h", "--help", action="help", help="显示帮助并退出")

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：", 1)

    def format_help(self):
        return super().format_help().replace("usage:", "用法：", 1)

    def error(self, message):
        replacements = (
            ("the following arguments are required:", "缺少必填参数："),
            ("unrecognized arguments:", "无法识别的参数："),
            ("expected one argument", "需要一个值"),
            ("invalid int value:", "整数格式无效："),
            ("invalid choice:", "无效取值："),
            ("choose from", "可选值为"),
            ("argument ", "参数 "),
        )
        for original, translated in replacements:
            message = message.replace(original, translated)
        self.print_usage(sys.stderr)
        self.exit(2, f"错误：{message}\n")


def positive_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须为正整数") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def nonnegative_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须为非负整数") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return number


def name_value(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise argparse.ArgumentTypeError("作业名需为 1–80 个英文字母、数字、点、下划线或短横线，并以字母或数字开头")
    return value


def host_value(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise argparse.ArgumentTypeError("--host 需为已经确认的 SSH（安全外壳连接）别名，不接受连接选项、用户地址或命令")
    return value


def node_value(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise argparse.ArgumentTypeError("--nodelist 仅接受一个已经确认的节点名，只能含英文字母、数字、点、短横线或下划线")
    return value


def gres_value(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?:[1-9][0-9]*", value):
        raise argparse.ArgumentTypeError("--gres 仅接受一项已确认的原生资源及正整数数量，例如 slcau:slc512:1；不接受多个请求、换行或命令")
    return value


def absolute_path(value):
    if not value.startswith("/") or any(char in value for char in "\x00\r\n"):
        raise argparse.ArgumentTypeError("需为绝对路径，且不得含换行或空字符")
    return value


def memory_value(value):
    if not re.fullmatch(r"[1-9][0-9]*[KMGT]", value):
        raise argparse.ArgumentTypeError("内存需为正整数并带 K、M、G 或 T 单位，例如 32G；这是整节点内存上限")
    return value


def time_value(value):
    match = re.fullmatch(r"(?:(\d+)-)?(\d{1,3}):([0-5]\d):([0-5]\d)", value)
    if not match:
        raise argparse.ArgumentTypeError("时间需为 HH:MM:SS 或 D-HH:MM:SS，例如 02:00:00 或 1-02:00:00")
    days, hours, minutes, seconds = match.groups()
    if days is not None and int(hours) > 23:
        raise argparse.ArgumentTypeError("使用 D-HH:MM:SS 时，小时须为 00–23")
    if not any(int(part or "0") for part in (days, hours, minutes, seconds)):
        raise argparse.ArgumentTypeError("作业时间必须大于零")
    return value


def module_value(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./+-]*", value):
        raise argparse.ArgumentTypeError("模块名只能含字母、数字、下划线、点、斜线、加号或短横线，不能包含额外命令")
    return value


def job_id(value):
    if not re.fullmatch(r"[1-9][0-9]*(?:_[0-9]+)?", value):
        raise argparse.ArgumentTypeError("仅接受单个数字作业编号或明确的数组元素，例如 12345 或 12345_2；不接受范围、列表或用户级批量操作")
    return value


def date_value(value):
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期需为 YYYY-MM-DD") from exc
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("日期需为 YYYY-MM-DD")
    return value


def shell_command(*parts):
    """每个参数分别按远端 shell（命令解释器）的引用规则保护。"""
    return " ".join(shlex.quote(str(part)) for part in parts)


def run_ssh(args, command):
    # 不读取连接配置或凭据，也不改动默认主机密钥检查。
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, command]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=args.timeout, check=False)
    except FileNotFoundError as exc:
        raise CommandError("找不到 ssh 程序；请先使用已经可用的 SSH（安全外壳连接）环境") from exc
    except subprocess.TimeoutExpired as exc:
        detail = "命令超过等待时间；未自动重试。"
        if args.command == "submit":
            detail += "提交结果尚未确认；先用 jobs/history 查看是否已有作业，再决定下一步，避免重复提交。"
        raise CommandError(detail) from exc


def emit_result(result):
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def render(args):
    if args.gres and args.gpus_per_node:
        raise CommandError("--gres 与非零 --gpus-per-node 不能同时使用；显式指定原生资源时，--gpus-per-node 必须为 0")
    if args.partition == "HPC":
        if not args.entry:
            raise CommandError("HPC 分区必须提供 --entry，即既有 bash（命令解释器）入口脚本的远端绝对路径")
        if args.ctl or args.checkpoint:
            raise CommandError("--ctl 和 --checkpoint 仅适用于 MHPC 分区")
    else:
        if args.gpus_per_node != 0:
            raise CommandError("MHPC 分区运行 LogicMD，不能申请普通 GPU（图形处理器）资源；--gpus-per-node 必须为 0")
        if args.gres and args.gres.split(":", 1)[0].lower() == "gpu":
            raise CommandError("MHPC 分区不接受普通 GPU（图形处理器）资源；--gres 应填写当前已确认的专用资源字段")
        if args.entry:
            raise CommandError("MHPC 分区仅运行 LogicMD，不能指定其他入口脚本")
        if not args.ctl or not args.ctl.endswith(".ctl"):
            raise CommandError("MHPC 分区必须提供以 .ctl 结尾的 --ctl 远端控制文件路径")
        if len(args.module) != 1 or not re.fullmatch(r"logic-md/[0-9][A-Za-z0-9_.+-]*", args.module[0]):
            raise CommandError("MHPC 必须显式提供一个已经确认可用的 LogicMD 模块版本，例如 --module logic-md/1.0.7.tcl；工具不会自行选择版本")

    lines = [
        "#!/bin/bash",
        "# Slurm（集群作业调度系统）提交脚本；本工具仅生成单节点、单任务作业。",
        f"#SBATCH --job-name={args.name}",
        f"#SBATCH --partition={args.partition}",
        f"#SBATCH --nodes={args.nodes}",
        "#SBATCH --ntasks=1",
        f"#SBATCH --cpus-per-task={args.cpus_per_task}",
        f"#SBATCH --mem={args.mem}",
        f"#SBATCH --time={args.time}",
        f"#SBATCH --output={args.name}-%j.out",
        f"#SBATCH --error={args.name}-%j.err",
    ]
    if args.gres:
        lines.append(f"#SBATCH --gres={args.gres}")
    elif args.gpus_per_node:
        lines.append(f"#SBATCH --gres=gpu:{args.gpus_per_node}")
    if args.nodelist:
        lines.append(f"#SBATCH --nodelist={args.nodelist}")
    lines.extend(["", "set -euo pipefail", f"cd -- {shlex.quote(args.workdir)}"])
    for module in args.module:
        lines.append(shell_command("module", "load", module))
    if args.partition == "HPC":
        lines.extend([
            f"entry={shlex.quote(args.entry)}",
            '[[ -f "$entry" && -r "$entry" ]] || { printf \'入口脚本不存在或不可读\\n\' >&2; exit 2; }',
            'bash -- "$entry"',
        ])
    else:
        lines.extend([
            ': "${SLURM_JOB_ID:?缺少 SLURM_JOB_ID（调度系统作业编号）}"',
            '[[ "$SLURM_JOB_ID" =~ ^[0-9]+$ ]] || { printf \'作业编号格式不正确\\n\' >&2; exit 2; }',
            f"ctl={shlex.quote(args.ctl)}",
            '[[ -f "$ctl" && -r "$ctl" ]] || { printf \'控制文件不存在或不可读\\n\' >&2; exit 2; }',
        ])
        if args.checkpoint:
            lines.extend([
                f"checkpoint={shlex.quote(args.checkpoint)}",
                '[[ -e "$checkpoint" && -r "$checkpoint" ]] || { printf \'续算文件不存在或不可读\\n\' >&2; exit 2; }',
            ])
        lines.extend([
            f"output_dir={shlex.quote(args.workdir)}/\"logic-md-${{SLURM_JOB_ID}}\"",
            '# 已存在的目录会使本作业停止，以保留已有结果。',
            'mkdir -- "$output_dir"',
        ])
        invocation = 'logic-md -i "$ctl"'
        if args.checkpoint:
            invocation += ' -cpix "$checkpoint"'
        lines.append(invocation + ' -o "$output_dir"')
    content = "\n".join(lines) + "\n"
    output = Path(args.output).expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise CommandError(f"文件已存在，未覆盖：{output}") from exc
    os.chmod(output, 0o700)
    print(f"已生成：{output}")
    resource = f"原生通用资源申请字段 {args.gres}" if args.gres else f"{args.gpus_per_node} 个 GPU（图形处理器）"
    print(f"资源申请：1 个节点，1 个任务，{args.cpus_per_task} 个 CPU（中央处理器）核心，{resource}，内存 {args.mem}，时间 {args.time}")
    print("仅完成本地脚本生成；尚未上传或提交。资源可用性和输入准备需按当前任务确认。")
    return 0


def submit(args):
    workdir = shlex.quote(args.workdir)
    script = shlex.quote(args.script)
    command = (
        f"if [ ! -d {workdir} ] || [ ! -r {workdir} ] || [ ! -x {workdir} ]; then "
        "printf '工作目录不存在或不可访问\\n' >&2; exit 2; fi; "
        f"if [ ! -f {script} ] || [ ! -r {script} ]; then "
        "printf '作业脚本不存在或不可读\\n' >&2; exit 2; fi; "
        + shell_command("sbatch", "--parsable", "--chdir=" + args.workdir, args.script)
    )
    result = run_ssh(args, command)
    emit_result(result)
    if result.returncode != 0:
        print("提交命令失败，未自动重试；若连接在提交期间中断，先查询作业记录确认是否已经提交。", file=sys.stderr)
        return result.returncode
    if not re.fullmatch(r"[1-9][0-9]*(?:;[^;\r\n]+)?", result.stdout.strip()):
        print("提交命令返回成功，但未识别作业编号；请先查询作业记录，避免重复提交。", file=sys.stderr)
        return 1
    print("已收到调度系统作业编号；这表示已提交，不表示程序已开始或已完成。")
    return 0


def logs(args):
    result = run_ssh(args, shell_command("scontrol", "--oneliner", "show", "job", args.job))
    if result.returncode:
        return emit_result(result)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if len(re.findall(r"(?:^|\s)JobId=", result.stdout)) > 1:
        raise CommandError("调度系统返回多个作业记录；请给出明确的数组元素编号再读取日志")
    fields = {}
    for match in re.finditer(r"(?:^|\s)(StdOut|StdErr)=(.*?)(?=\s+[A-Za-z][A-Za-z0-9_]*=|$)", result.stdout):
        fields[match.group(1)] = match.group(2).strip()
    streams = ["StdOut", "StdErr"] if args.stream == "both" else ["StdOut" if args.stream == "stdout" else "StdErr"]
    unique_paths = []
    for field in streams:
        path = fields.get(field)
        if not path or path in {"(null)", "N/A", "Unknown"}:
            raise CommandError(f"作业记录未提供 {field}（{'标准输出' if field == 'StdOut' else '标准错误输出'}）路径；历史记录可用 history 查询")
        try:
            absolute_path(path)
        except argparse.ArgumentTypeError as exc:
            raise CommandError(f"作业记录的 {field} 路径不是可接受的绝对路径") from exc
        if path not in unique_paths:
            unique_paths.append(path)
    code = 0
    for path in unique_paths:
        print(f"== {path}（末尾 {args.lines} 行） ==", flush=True)
        result = run_ssh(args, shell_command("tail", "-n", args.lines, "--", path))
        current_code = emit_result(result)
        if current_code:
            code = current_code
    return code


def remote_query(args):
    if args.command == "resources":
        command = shell_command("sinfo", "--long")
    elif args.command == "jobs":
        command = 'squeue --user="$(id -un)" --long'
    elif args.command == "job":
        command = shell_command("scontrol", "show", "job", args.job)
    elif args.command == "cancel":
        command = shell_command("scancel", args.job)
    elif args.command == "history":
        parts = ["sacct", "--starttime=" + args.start]
        if args.end:
            if args.end < args.start:
                raise CommandError("历史查询结束日期不得早于开始日期")
            parts.append("--endtime=" + args.end)
        if args.job:
            parts.append("--jobs=" + args.job)
        parts.extend(["--format=JobID,JobName,Partition,AllocCPUS,ReqMem,State,ExitCode,Start,End,Elapsed", "--parsable2"])
        command = shell_command(*parts) + ' --user="$(id -un)"'
    else:
        raise CommandError("未识别的命令")
    result = run_ssh(args, command)
    code = emit_result(result)
    if args.command == "cancel" and code == 0:
        print("已发送取消请求；请用 job/jobs 确认最终状态。")
    return code


def parser():
    root = ChineseParser(description="智爱赛思 Slurm（集群作业调度系统）工具：本地生成脚本，或通过既有 SSH（安全外壳连接）别名操作。不会配置登录、读取凭据或自动重试提交。")
    sub = root.add_subparsers(dest="command", required=True)
    render_parser = sub.add_parser("render", help="本地生成单节点作业脚本；不覆盖文件，不提交计算")
    render_parser.add_argument("--partition", choices=["HPC", "MHPC"], required=True, help="平台分区名称")
    render_parser.add_argument("--name", type=name_value, required=True, help="作业名称；建议每次运行使用明确且不同的名称")
    render_parser.add_argument("--workdir", type=absolute_path, required=True, help="远端工作目录的绝对路径，支持空格")
    render_parser.add_argument("--output", required=True, help="生成脚本的本地路径；存在时拒绝覆盖")
    render_parser.add_argument("--nodes", type=int, choices=[1], required=True, help="节点数；当前工具仅支持 1，固定单任务；多节点请编写原生提交脚本")
    render_parser.add_argument("--nodelist", type=node_value, help="可选：指定一个已确认的节点名；不接受节点列表或范围")
    render_parser.add_argument("--cpus-per-task", type=positive_int, required=True, help="单任务使用的 CPU（中央处理器）核心数")
    render_parser.add_argument("--gpus-per-node", type=nonnegative_int, required=True, help="每节点 GPU（图形处理器）数量；无 GPU 时显式填 0")
    render_parser.add_argument("--gres", type=gres_value, help="可选：一项已确认的原生通用资源（generic resources），例如 slcau:slc512:1；使用时 --gpus-per-node 必须为 0")
    render_parser.add_argument("--mem", type=memory_value, required=True, help="整节点内存，例如 32G")
    render_parser.add_argument("--time", type=time_value, required=True, help="最长运行时间，例如 02:00:00")
    render_parser.add_argument("--module", type=module_value, action="append", default=[], help="已确认存在的环境模块；HPC 可重复指定，MHPC 要求一个 logic-md/<版本>，不会自动选择")
    render_parser.add_argument("--entry", type=absolute_path, help="HPC：既有 bash（命令解释器）入口脚本的远端绝对路径；工具不会改动程序参数")
    render_parser.add_argument("--ctl", type=absolute_path, help="MHPC：LogicMD 控制文件的远端绝对路径，以 .ctl 结尾")
    render_parser.add_argument("--checkpoint", type=absolute_path, help="MHPC：既有续算文件的远端绝对路径；需与原运行使用相同版本，工具不改动控制文件")

    def remote(name, help_text):
        command_parser = sub.add_parser(name, help=help_text)
        command_parser.add_argument("--host", type=host_value, required=True, help="已经由用户确认、可用的 SSH（安全外壳连接）别名")
        command_parser.add_argument("--timeout", type=positive_int, default=30, help="本次远端命令等待秒数，默认 30；超时不自动重试")
        return command_parser

    remote("resources", "查看分区和节点状态；原样返回 sinfo 输出")
    remote("jobs", "查看当前连接用户的排队或运行作业；原样返回 squeue 输出")
    for name, description in (("job", "查看单个作业详情；原样返回 scontrol 输出"), ("cancel", "取消明确指定的单个作业或数组元素，不支持按用户批量取消")):
        command_parser = remote(name, description)
        command_parser.add_argument("job", type=job_id, help="明确的作业编号，例如 12345 或 12345_2")
    history_parser = remote("history", "查看当前连接用户的历史作业；原样返回 sacct 输出")
    history_parser.add_argument("--start", type=date_value, required=True, help="开始日期，YYYY-MM-DD")
    history_parser.add_argument("--end", type=date_value, help="结束日期，YYYY-MM-DD；按调度系统对结束时间的定义查询")
    history_parser.add_argument("--job", type=job_id, help="可选：仅查看指定作业或数组元素")
    submit_parser = remote("submit", "先检查远端路径，再仅调用一次 sbatch 提交；不上传文件，不自动重复提交")
    submit_parser.add_argument("--workdir", type=absolute_path, required=True, help="已准备完成、用于本次运行的远端工作目录绝对路径")
    submit_parser.add_argument("--script", type=absolute_path, required=True, help="已上传的远端提交脚本绝对路径")
    logs_parser = remote("logs", "从 scontrol 记录取得日志路径，读取末尾有限行数")
    logs_parser.add_argument("job", type=job_id, help="明确的作业编号")
    logs_parser.add_argument("--stream", choices=["stdout", "stderr", "both"], default="both", help="stdout：标准输出；stderr：标准错误输出；both：二者，默认")
    logs_parser.add_argument("--lines", type=positive_int, default=100, help="每个日志读取末尾行数，1–1000，默认 100")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "render":
            return render(args)
        if args.command == "submit":
            return submit(args)
        if args.command == "logs":
            if args.lines > 1000:
                raise CommandError("--lines 最多为 1000，避免读取过大日志")
            return logs(args)
        return remote_query(args)
    except CommandError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        location = str(exc.filename) if exc.filename else "当前文件或系统操作"
        print(f"错误：文件或系统操作失败：{location}（系统错误编号 {exc.errno}）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
