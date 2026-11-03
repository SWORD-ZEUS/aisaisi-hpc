#!/usr/bin/env python3
"""通过爱赛思文件接口上传，使用显式指定的命令行登录会话。

POST /hpc-portal/file/v1/BatchUpload：多部分表单中的 files 与 path 字段。
GET /hpc-portal/file/v1/List：path 查询参数，返回 data.items。
不读取浏览器凭据，不跟随重定向，不使用代理，不自动重试。
上传前拒绝已有同名文件；接口没有已确认的“仅创建”原子操作保证，
因此应使用独立任务目录，避免其他进程同时写入同名文件。
"""
import argparse
import importlib.util
import json
import mimetypes
from pathlib import Path
import posixpath
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
import uuid


def load_cli(path):
    spec = importlib.util.spec_from_file_location("aisaisi_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def request(args, cli, token, endpoint, *, params=None, payload=None, content_type=None):
    headers = {"Authorization": "Bearer " + token, "X-GW-CUR-PID": str(args.project),
               "X-IAM-TICK": str(int(time.time() * 1000)), "Accept-Language": "zh-CN",
               "X-Referer-Path": "/workflow/calculate/file"}
    if content_type:
        headers["Content-Type"] = content_type
    url = args.origin + endpoint + ("?" + urlencode(params) if params else "")
    req = Request(url, data=payload, headers=headers,
                  method="POST" if payload is not None else "GET")
    try:
        with build_opener(ProxyHandler({}), cli.NoRedirect()).open(req, timeout=args.timeout) as resp:
            raw = resp.read(8 * 1024 * 1024 + 1)
    except HTTPError as error:
        raise cli.CliError(f"文件接口返回 HTTP（超文本传输协议）状态 {error.code}；未自动重试") from None
    except (URLError, TimeoutError, OSError):
        raise cli.CliError("文件接口连接失败或超时；上传可能已开始，请先查询目标目录，未自动重试") from None
    if len(raw) > 8 * 1024 * 1024:
        raise cli.CliError("文件接口响应超过 8 MiB（兆二进制字节），未输出")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise cli.CliError("文件接口未返回可解析的 JSON（JavaScript 对象表示法），未输出原始响应") from None
    if not isinstance(data, dict) or data.get("code") != 0 or "data" not in data:
        code = data.get("code") if isinstance(data, dict) else "未知"
        raise cli.CliError(f"文件接口未报告成功，业务代码={code}")
    return data["data"]


def list_directory(args, cli, token):
    result = request(args, cli, token, "/hpc-portal/file/v1/List", params={"path": args.remote_dir})
    # 兼容平台空目录响应 items:null,total:0。
    if isinstance(result, dict) and result.get("items") is None and result.get("total") == 0:
        result["items"] = []
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise cli.CliError("目录返回不含 items 列表，未猜测格式或上传")
    return result


def multipart(files, remote_dir):
    boundary = "Ai4SUpload" + uuid.uuid4().hex
    parts = []
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n"
                  f"{remote_dir}\r\n").encode())
    for path in files:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
                      f"filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n").encode())
        parts.extend([path.read_bytes(), b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cli", default=str(Path(__file__).resolve().with_name("aisaisi_cli.py")),
                   help="客户端脚本路径，默认使用本脚本所在目录的 aisaisi_cli.py")
    p.add_argument("--origin", default="https://ai4s.yicloud.com")
    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--session")
    auth.add_argument("--token-env")
    p.add_argument("--project", type=int, required=True)
    p.add_argument("--remote-dir", required=True, help="文件页面中的目标目录路径；首次使用可用 --list 查询")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--list", action="store_true", help="只查询目录，不上传文件")
    p.add_argument("files", nargs="*")
    args = p.parse_args()
    cli = load_cli(args.cli)
    try:
        args.origin = cli.origin_value(args.origin)
        if args.project <= 0 or args.timeout <= 0:
            raise cli.CliError("项目编号与超时必须为正数")
        if not args.remote_dir.startswith("/") or any(c in args.remote_dir for c in "\r\n\0"):
            raise cli.CliError("目标目录需要绝对路径且不包含换行或空字符")
        if posixpath.normpath(args.remote_dir) != args.remote_dir.rstrip("/") and args.remote_dir != "/":
            raise cli.CliError("目标目录不能包含相对路径分量")
        if args.list and args.files:
            raise cli.CliError("--list 不能同时指定上传文件")
        if not args.list and not args.files:
            raise cli.CliError("需要指定上传文件或 --list")
        files = [Path(value).resolve(strict=True) for value in args.files]
        names = [path.name for path in files]
        if len(names) != len(set(names)):
            raise cli.CliError("本次文件存在同名，未上传")
        for path in files:
            if not path.is_file() or any(c in path.name for c in '\r\n\0"\\'):
                raise cli.CliError("输入不是普通文件，或文件名包含不支持的字符")
        if sum(path.stat().st_size for path in files) > 256 * 1024 * 1024:
            raise cli.CliError("本工具每次上传最多 256 MiB（兆二进制字节），请拆分指定文件")
        token = cli.load_token(args)
        before = list_directory(args, cli, token)
        if args.list:
            print(json.dumps(cli.redact(before), ensure_ascii=False, indent=2))
            return 0
        existing = {str(item.get("name", "")) for item in before["items"]}
        collision = existing.intersection(names)
        if collision:
            raise cli.CliError("目标已有同名文件，拒绝覆盖：" + ", ".join(sorted(collision)))
        body, content_type = multipart(files, args.remote_dir)
        result = request(args, cli, token, "/hpc-portal/file/v1/BatchUpload", payload=body,
                         content_type=content_type)
        if not isinstance(result, dict) or not result.get("paths"):
            raise cli.CliError("上传响应没有成功文件路径；结果不明，未自动重试，请查询目标目录")
        after = list_directory(args, cli, token)
        by_name = {str(item.get("name", "")): item for item in after["items"]}
        verified = []
        for path in files:
            item = by_name.get(path.name)
            if item is None or int(item.get("size", -1)) != path.stat().st_size:
                raise cli.CliError("上传已响应，但目录中的文件名或长度未吻合；保留文件，不自动重试")
            verified.append({"name": path.name, "bytes": path.stat().st_size,
                             "path": item.get("path", posixpath.join(args.remote_dir, path.name))})
        print(json.dumps({"status": "uploaded_and_size_checked", "project": args.project,
                          "directory": args.remote_dir, "files": verified}, ensure_ascii=False, indent=2))
        return 0
    except (cli.CliError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
