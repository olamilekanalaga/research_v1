from __future__ import annotations

import argparse
import sqlite3
import subprocess
import time

from .config import get_settings


def matching_processes() -> list[dict[str, str]]:
    command = (
        "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
        "Select-Object ProcessId,CommandLine | "
        "Where-Object { $_.CommandLine -like '*pump_momentum_scanner*' } | "
        "ConvertTo-Json"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout.strip():
        return []
    import json

    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return data


def print_status() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    now = int(time.time())
    print("Runtime processes")
    for proc in matching_processes():
        print(f"{proc.get('ProcessId')}: {proc.get('CommandLine')}")
    print()
    print("API burn")
    print(f"api_logs_total={conn.execute('SELECT COUNT(*) FROM api_logs').fetchone()[0]}")
    print(f"last_hour={conn.execute('SELECT COUNT(*) FROM api_logs WHERE timestamp>=?', (now - 3600,)).fetchone()[0]}")
    print(f"last_10m={conn.execute('SELECT COUNT(*) FROM api_logs WHERE timestamp>=?', (now - 600,)).fetchone()[0]}")
    print(
        "solanatracker_last_10m="
        f"{conn.execute('SELECT COUNT(*) FROM api_logs WHERE source=? AND timestamp>=?', ('solanatracker', now - 600)).fetchone()[0]}"
    )


def pause_runtime() -> None:
    for proc in matching_processes():
        pid = proc.get("ProcessId")
        command_line = proc.get("CommandLine") or ""
        if pid and ("pump_momentum_scanner.scanner" in command_line or "pump_momentum_scanner.bot_server" in command_line):
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid}"], check=False)
            print(f"stopped {pid}: {command_line}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show or pause scanner runtime")
    parser.add_argument("action", choices=["status", "pause"])
    args = parser.parse_args()
    if args.action == "status":
        print_status()
    else:
        pause_runtime()


if __name__ == "__main__":
    main()
