"""不连接平台的本地行为检查；会话内容和项目编号均为虚构数据。"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "aisaisi-hpc" / "scripts"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aisaisi-local-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.session = self.directory / "session.json"
        self.session.write_text(json.dumps({
            "origin": "https://ai4s.yicloud.com",
            "access_token": "offline-placeholder-not-a-real-credential",
        }), encoding="utf-8")

    def upload_arguments(self):
        return ["aisaisi_upload.py", "--session", str(self.session),
                "--project", "1", "--remote-dir", "/offline-test"]

    def test_upload_works_after_relocation_without_home_install(self):
        relocated = self.directory / "different installation"
        relocated.mkdir()
        for filename in ("aisaisi_upload.py", "aisaisi_cli.py"):
            shutil.copyfile(SCRIPTS / filename, relocated / filename)
        upload = load_module(relocated / "aisaisi_upload.py", "relocated_upload")
        stdout = io.StringIO()
        with patch.object(Path, "home", return_value=self.directory / "no-home-install"), \
             patch.object(sys, "argv", self.upload_arguments() + ["--list"]), \
             patch.object(upload, "request", return_value={"items": None, "total": 0}) as request, \
             contextlib.redirect_stdout(stdout):
            self.assertEqual(upload.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["items"], [])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[3], "/hpc-portal/file/v1/List")

    def test_existing_remote_filename_is_not_uploaded(self):
        upload = load_module(SCRIPTS / "aisaisi_upload.py", "collision_upload")
        source = self.directory / "input.txt"
        source.write_text("offline input", encoding="utf-8")
        stderr = io.StringIO()
        with patch.object(sys, "argv", self.upload_arguments() + [str(source)]), \
             patch.object(upload, "request", return_value={"items": [{"name": source.name}], "total": 1}) as request, \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(upload.main(), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[3], "/hpc-portal/file/v1/List")
        self.assertIn("拒绝覆盖", stderr.getvalue())

    def test_render_preserves_exit_status_and_existing_script(self):
        slurm = load_module(SCRIPTS / "aisaisi_slurm.py", "render_slurm")
        run_dir = self.directory / "run with ' quotes $ and spaces"
        run_dir.mkdir()
        entry = run_dir / "entry.sh"
        entry.write_text("#!/bin/bash\nexit 17\n", encoding="utf-8")
        output = self.directory / "job.slurm"
        arguments = ["render", "--partition", "HPC", "--name", "offline-test",
                     "--workdir", str(run_dir), "--output", str(output),
                     "--nodes", "1", "--cpus-per-task", "1", "--gpus-per-node", "0",
                     "--mem", "1G", "--time", "00:01:00", "--entry", str(entry)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(slurm.main(arguments), 0)
        original = output.read_bytes()
        execution = subprocess.run(["bash", str(output)], capture_output=True, timeout=5)
        self.assertEqual(execution.returncode, 17)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(slurm.main(arguments), 2)
        self.assertEqual(output.read_bytes(), original)

    def test_mhpc_rejects_ordinary_gpu_request(self):
        slurm = load_module(SCRIPTS / "aisaisi_slurm.py", "mhpc_slurm")
        output = self.directory / "must-not-exist.slurm"
        arguments = ["render", "--partition", "MHPC", "--name", "offline-md",
                     "--workdir", str(self.directory), "--output", str(output),
                     "--nodes", "1", "--cpus-per-task", "1", "--gpus-per-node", "1",
                     "--mem", "1G", "--time", "00:01:00",
                     "--ctl", str(self.directory / "md.ctl"), "--module", "logic-md/1.1.4.tcl"]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(slurm.main(arguments), 2)
        self.assertFalse(output.exists())

    def test_session_for_another_site_is_rejected_before_request(self):
        cli = load_module(SCRIPTS / "aisaisi_cli.py", "session_cli")
        stderr = io.StringIO()
        with patch.object(cli, "http_json") as request, contextlib.redirect_stderr(stderr):
            result = cli.main(["--origin", "https://example.org", "--session", str(self.session), "projects"])
        self.assertEqual(result, 2)
        request.assert_not_called()
        self.assertIn("站点不同", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
