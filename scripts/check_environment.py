"""Read-only environment probe, using only the standard library."""

import argparse
import ctypes
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys


def probe():
    root = Path(__file__).resolve().parents[1]
    report = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "os": platform.platform(), "architecture": platform.machine(),
        "python": platform.python_version(), "python_bits": struct.calcsize("P") * 8,
        "executable": sys.executable, "base_executable": getattr(sys, "_base_executable", None),
        "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "isolated_venv": sys.prefix != sys.base_prefix,
        "logical_cpu_count": os.cpu_count(),
        "workspace_free_gib": round(shutil.disk_usage(root).free / 1024**3, 2),
        "packages": {}, "notes": [],
    }
    for name in ("pip", "matplotlib", "numpy", "pillow", "networkx", "pytest"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                report["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError as exc:
            report["notes"].append(f"CPU registry read: {exc}")

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ("total_phys", "available_phys", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]

        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            report["ram_gib"] = round(memory.total_phys / 1024**3, 2)
            report["available_ram_gib"] = round(memory.available_phys / 1024**3, 2)
    gpu = shutil.which("nvidia-smi")
    if gpu:
        try:
            result = subprocess.run([gpu, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=10, check=True)
            report["gpu"] = result.stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            report["notes"].append(f"GPU probe: {exc}")
    report["simulation_requires_gpu"] = False
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
