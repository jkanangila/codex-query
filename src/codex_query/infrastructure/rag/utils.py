import os
import platform
import subprocess


def is_wsl() -> bool:
    """Check if Python is running inside WSL (Windows Subsystem for Linux)."""
    # Quick environment variable check
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True

    # Secondary kernel check for Linux builds
    if platform.system() == "Linux":
        try:
            with open("/proc/version") as f:
                version_info = f.read().lower()
                return "microsoft" in version_info or "wsl" in version_info
        except FileNotFoundError:
            return False

    return False


def get_ollama_base_url() -> str:
    """
    Resolves the network host address for local service routing.

    Returns:
        The WSL default gateway IP if running under WSL,
        otherwise '127.0.0.1'.
    """
    if is_wsl():
        try:
            # Executes shell command to capture default gateway IP
            result = subprocess.run(
                "ip route show | grep -i default | awk '{print $3}'",
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            ip_address = result.stdout.strip()
            if ip_address:
                return f"http://{ip_address}:11434"
        except Exception:
            # If network command fails, safely fall back
            pass

    return "http://127.0.0.1:11434"
