#!/usr/bin/env python3
"""爱赛思命令行客户端：正常登录、项目/实例/作业查询和终端命令。

查询和提交均使用当前用户明确指定的会话与项目，不内置账号配置。

HTTP（超文本传输协议）查询使用标准库；终端使用 Node.js 原生 WebSocket
（双向通信协议），通过标准输入传入认证数据。不读取浏览器存储、不调用 FindUser、
不创建或续期实例。
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import sys
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class CliError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def origin_value(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("站点必须是没有账号或密码的 HTTPS（加密超文本传输协议）地址")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("站点地址不能带路径、查询参数或片段")
    return value.rstrip("/")


def positive(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须为正整数") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def nonnegative(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须为非负整数") from error
    if number < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return number


def absolute_remote_path(value):
    if not value.startswith("/") or any(char in value for char in "\x00\r\n"):
        raise argparse.ArgumentTypeError("需要远端绝对路径，且不能包含换行或空字符")
    return value


def to_snake(value):
    """按公开主程序逐个大写字母加下划线，保持其实际转换规则。"""
    if isinstance(value, list):
        return [to_snake(item) for item in value]
    if isinstance(value, dict):
        return {re.sub(r"([A-Z])", r"_\1", key).lower(): to_snake(item) for key, item in value.items()}
    return value


def redact(value):
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: "[已隐藏]" if re.search(r"token|password|passwd|secret|private.?key|authorization|cookie|verify.?code", key, re.I)
                else redact(item) for key, item in value.items()}
    return value


def http_json(args, path, *, token=None, params=None, body=None, project=None):
    # 仅请求显式站点；禁止重定向，避免认证头转发到其他站点。
    headers = {"Accept-Language": "zh-CN", "X-IAM-TICK": str(int(time.time() * 1000)),
               "X-Referer-Path": "/auth/login" if path == "/dapi/v1/iam/login" else "/workflow/calculate/taskList",
               "Content-Type": "application/json;charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if project is not None:
        headers["X-GW-CUR-PID"] = str(project)
    url = args.origin + path
    if params:
        url += "?" + urlencode(to_snake(params))
    payload = None if body is None else json.dumps(to_snake(body), ensure_ascii=False).encode("utf-8")
    request = Request(url, data=payload, headers=headers, method="GET" if body is None else "POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=args.timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except HTTPError as error:
        raise CliError(f"接口返回 HTTP（超文本传输协议）状态 {error.code}；未自动重试或重新登录") from None
    except (URLError, TimeoutError, OSError):
        raise CliError("接口连接失败或超时；未打印认证信息，未自动重试") from None
    if len(raw) > 8 * 1024 * 1024:
        raise CliError("接口响应超过 8 MiB（兆字节），请缩小查询范围")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CliError("接口未返回可解析的 JSON（JavaScript 对象表示法）") from None
    if not isinstance(envelope, dict) or envelope.get("code") != 0 or "data" not in envelope:
        # 错误消息可能包含服务端回显，保留业务代码但不打印完整响应。
        code = envelope.get("code") if isinstance(envelope, dict) else "未知"
        raise CliError(f"接口未报告成功，业务代码={code}；完整响应未打印")
    return envelope["data"]


def load_token(args):
    if args.session:
        try:
            content = json.loads(Path(args.session).expanduser().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise CliError("无法读取显式指定的会话文件；未搜索其他凭据位置") from None
        if not isinstance(content, dict):
            raise CliError("显式会话文件内容格式不正确")
        if content.get("origin") != args.origin:
            raise CliError("会话文件所属站点与本次显式站点不同")
        token = content.get("access_token")
    elif args.token_env:
        token = os.environ.get(args.token_env)
    else:
        raise CliError("需要 --session 显式会话文件，或 --token-env 显式环境变量名；不会读取浏览器认证信息")
    if not isinstance(token, str) or not token or any(char in token for char in "\r\n\x00"):
        raise CliError("显式会话来源没有可用的访问令牌（access token）")
    return token


def login(args):
    if not sys.stdin.isatty():
        raise CliError("请在本地交互终端登录；当前输入不是终端，已停止以避免密码或验证码显示")
    if args.token_env:
        raise CliError("正常登录不接受 --token-env；该选项仅用于已有令牌的查询或终端连接")
    if args.username:
        if args.request_code:
            raise CliError("--request-code 只适用于手机登录，不会为账号密码登录发送验证码")
        body = {"username": args.username, "password": getpass.getpass("密码（输入不显示）：")}
    else:
        phone = args.phone or input("平时登录的手机号：").strip()
        if not phone:
            raise CliError("手机号不能为空")
        if args.request_code:
            http_json(args, "/dapi/v1/iam/sendVerifyCode", body={"phone": phone, "purpose": "login"})
            print("已按显式 --request-code 发送一次登录验证码；不会自动重复发送。")
        body = {"phone": phone, "verifyCode": getpass.getpass("已有手机验证码（输入不显示）：")}
    try:
        result = http_json(args, "/dapi/v1/iam/login", body=body)
    finally:
        body.clear()
    if isinstance(result, dict) and result.get("is_first_login", result.get("isFirstLogin")) is True:
        raise CliError("平台报告首次登录；请在网页完成正常流程，客户端未创建账号、接受条款或保存访问令牌")
    token = result.get("access_token", result.get("accessToken")) if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise CliError("登录响应没有访问令牌；认证响应未打印")
    if args.session:
        target = Path(args.session).expanduser()
        # 不创建默认凭据目录，也不覆盖任何已有文件。
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"origin": args.origin, "access_token": token, "created_at": int(time.time())}, handle)
                handle.write("\n")
        except FileExistsError:
            raise CliError("登录成功，但显式会话文件已存在，未覆盖；令牌未打印") from None
        except OSError:
            raise CliError("登录成功，但无法保存显式会话文件；令牌未打印") from None
        print("正常登录成功；访问令牌仅保存到显式指定的会话文件，权限为仅当前用户可读写。")
    else:
        print("正常登录成功；未指定 --session，未保存或打印访问令牌。当前进程结束后令牌不再可用。")
    return 0


def query(args):
    token = load_token(args)
    if args.command == "projects":
        path = "/dapi/v1/res/projects" if args.resources else "/dapi/v1/bff/users/projects"
        data = http_json(args, path, token=token)
    else:
        if args.project is None:
            raise CliError("需要显式 --project 项目编号；先用 projects 核实当前账号的项目映射")
        if args.command == "instances":
            data = http_json(args, "/hpc-portal/pod/v1/ListDeploy", token=token, project=args.project)
        else:
            params = {"offset": args.offset, "limit": args.limit}
            for option, field in (("state", "state"), ("start", "timeStart"), ("end", "timeEnd")):
                value = getattr(args, option)
                if value is not None:
                    params[field] = value
            data = http_json(args, "/hpc-portal/job/v1/ListJob", token=token, params=params, project=args.project)
    print(json.dumps(redact(data), ensure_ascii=False, indent=2))
    return 0


def remote_command(args):
    if args.command == "exec":
        return args.shell_command
    if args.command == "job":
        return shlex.join(["scontrol", "show", "job", args.job_id])
    if args.command == "resources":
        return "sinfo --long"
    if args.command == "submit":
        directory = shlex.quote(args.workdir)
        script = shlex.quote(args.script)
        return (
            f"if [ ! -d {directory} ] || [ ! -r {directory} ] || [ ! -x {directory} ]; then "
            "printf '工作目录不存在或不可访问\\n' >&2; exit 2; fi; "
            f"if [ ! -f {script} ] || [ ! -r {script} ]; then "
            "printf '作业脚本不存在或不可读\\n' >&2; exit 2; fi; "
            + shlex.join(["bash", "-n", "--", args.script]) + " && "
            + shlex.join(["sbatch", "--parsable", "--chdir=" + args.workdir, args.script])
        )
    raise CliError("未识别的终端命令")


def exec_command(args):
    if args.project is None:
        raise CliError("终端连接需要显式 --project 项目编号；不会自动选择项目或创建实例")
    token = load_token(args)
    command = remote_command(args)
    payload = {"origin": args.origin, "token": token, "project": args.project,
               "command": command, "cols": getattr(args, "cols", 160),
               "rows": getattr(args, "rows", 48), "timeout": args.timeout}
    transport = Path(__file__).with_name("aisaisi_ws.mjs")
    try:
        result = subprocess.run(["node", str(transport)], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=args.timeout + 5, check=False)
    except FileNotFoundError:
        raise CliError("找不到 Node.js；终端传输需要具有原生 WebSocket（双向通信协议）的 Node.js 运行环境") from None
    except (subprocess.TimeoutExpired, OSError):
        raise CliError("终端传输等待失败或超时；远端命令可能继续，未自动重试") from None
    try:
        reply = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise CliError("终端传输未返回可解析结果；认证数据及异常原文未打印") from None
    if not reply.get("ok"):
        raise CliError(str(reply.get("error", "终端命令状态未确认")).replace(token, "[已隐藏]"))
    sys.stdout.write(str(reply.get("stdout", "")).replace(token, "[已隐藏]"))
    sys.stdout.flush()
    status = int(reply["exit_code"])
    if args.command == "submit":
        if status:
            print("提交命令返回失败，未自动重试。", file=sys.stderr)
        else:
            print("提交命令返回成功；请按返回作业编号查询排队或运行状态，这不表示计算程序已完成。", file=sys.stderr)
    return status



def parser():
    result = argparse.ArgumentParser(description="爱赛思 HTTP（超文本传输协议）/WebSocket（双向通信协议）命令行客户端；不使用浏览器令牌，不创建实例或权限。")
    result.add_argument("--origin", type=origin_value, default="https://ai4s.yicloud.com", help="显式站点，默认生产站点")
    credentials = result.add_mutually_exclusive_group()
    credentials.add_argument("--session", help="显式会话文件；登录时只创建新文件，其余命令仅从此文件读取")
    credentials.add_argument("--token-env", help="显式提供已有访问令牌的环境变量名；不自动搜索变量")
    result.add_argument("--project", type=positive, help="显式账号项目编号；先用 projects 查询，不自动选择项目")
    result.add_argument("--timeout", type=positive, default=30, help="等待秒数，默认 30；不自动重试")
    commands = result.add_subparsers(dest="command", required=True)
    login_parser = commands.add_parser("login", help="正常账号登录；密码或已有验证码仅通过不显示的输入读取")
    identity = login_parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--username", help="正常登录账号")
    identity.add_argument("--phone", nargs="?", const="", help="手机号；省略值时交互输入，默认使用已有验证码")
    login_parser.add_argument("--request-code", action="store_true", help="仅手机登录：显式发送一次验证码，不自动重复发送")
    projects = commands.add_parser("projects", help="查询账号项目映射")
    projects.add_argument("--resources", action="store_true", help="查询底层资源项目映射；默认查询工作台项目")
    commands.add_parser("instances", help="查询当前项目既有终端和图形桌面实例")
    jobs = commands.add_parser("jobs", help="查询当前项目可见的作业；不调用管理员全局作业接口")
    jobs.add_argument("--offset", type=nonnegative, default=0, help="从零开始的查询位置")
    jobs.add_argument("--limit", type=positive, default=10, help="本次条目数，默认 10")
    jobs.add_argument("--state", choices=["0", "1", "3", "4", "5", "7", "100"], help="平台状态值，保持原始定义")
    jobs.add_argument("--start", help="开始时间，例如 2026-10-12 00:00:00；按平台时区解释")
    jobs.add_argument("--end", help="结束时间，例如 2026-10-12 23:59:59；按平台时区解释")
    single = commands.add_parser("job", help="通过既有终端查询单个 Slurm（集群作业调度系统）作业详情")
    def job_value(value):
        if not re.fullmatch(r"[1-9][0-9]*(?:_[0-9]+)?", value):
            raise argparse.ArgumentTypeError("仅接受单个作业编号或明确的数组元素")
        return value
    single.add_argument("job_id", type=job_value, help="明确的作业编号，例如 12345 或 12345_2")
    commands.add_parser("resources", help="通过既有终端执行 sinfo，查看当前分区和节点；不自动选择资源")
    submission = commands.add_parser("submit", help="通过既有终端检查远端目录、脚本和Bash语法，再仅调用一次sbatch提交；不上传、不重试")
    submission.add_argument("--workdir", type=absolute_remote_path, required=True, help="本次已准备完成的远端独立工作目录绝对路径")
    submission.add_argument("--script", type=absolute_remote_path, required=True, help="远端已有Slurm（集群作业调度系统）脚本绝对路径")
    terminal = commands.add_parser("exec", help="通过已存在终端的 WebSocket（双向通信协议）执行显式命令，返回命令退出状态")
    terminal.add_argument("--command", dest="shell_command", required=True, help="本次已经授权的明确 Bash（命令解释器）命令")
    terminal.add_argument("--cols", type=positive, default=160, help="终端列数，默认 160")
    terminal.add_argument("--rows", type=positive, default=48, help="终端行数，默认 48")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "login":
            return login(args)
        if args.command in {"exec", "job", "resources", "submit"}:
            return exec_command(args)
        return query(args)
    except (CliError, KeyboardInterrupt, EOFError) as error:
        message = str(error) if isinstance(error, CliError) else "输入已取消，未自动重试"
        print("错误：" + message, file=sys.stderr)
        if args.command == "submit":
            print("未自动重发提交；若连接在提交期间中断，先查询作业记录确认结果，避免重复提交。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
