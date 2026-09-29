"""Find the web browser to use (Google Chrome first, Microsoft Edge as a fallback) and manage its app windows.

Both are Chromium browsers and behave the same way for what this app needs: an "app mode" window with no tabs or
address bar, and a private profile folder so the app can close exactly its own windows and nothing else.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Browser:
    name: str      # shown to people
    path: str
    process: str   # Windows process name
    channel: str   # Playwright channel name


def _first_existing(paths) -> str | None:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _chrome() -> Browser | None:
    roots = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    path = _first_existing([shutil.which("chrome"), shutil.which("google-chrome"),
                            *[os.path.join(r, "Google", "Chrome", "Application", "chrome.exe") for r in roots if r],
                            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"])
    return Browser("Google Chrome", path, "chrome.exe", "chrome") if path else None


def _edge() -> Browser | None:
    path = _first_existing([shutil.which("msedge"),
                            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"])
    return Browser("Microsoft Edge", path, "msedge.exe", "msedge") if path else None


def find_browser() -> Browser | None:
    """Google Chrome if it is installed (it's Pete's default browser), otherwise Microsoft Edge."""
    return _chrome() or _edge()


def kill_profile_windows(profile_names: list[str]) -> None:
    """Close every Chrome/Edge process that was started with one of these private profile folders.

    Only processes whose command line mentions the profile are touched, so normal browsing windows are safe.
    """
    if os.name != "nt":
        return
    match = " -or ".join(f"$_.CommandLine -like '*{n}*'" for n in profile_names)
    script = ("Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') "
              f"-and ({match}) }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=0x08000000, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
