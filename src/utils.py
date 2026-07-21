import os
import platform
import subprocess


def is_wsl() -> bool:
    """Checks if the Python runtime environment is operating inside WSL (Windows Subsystem for Linux)."""
    # Quick environment variable check
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True

    # Secondary kernel check for Linux builds
    if platform.system() == "Linux":
        try:
            with open("/proc/version", "r") as f:
                version_info = f.read().lower()
                return "microsoft" in version_info or "wsl" in version_info
        except FileNotFoundError:
            return False

    return False


def get_ollama_host_ip() -> str:
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
                return ip_address
        except Exception:
            # If network command fails, safely fall back
            pass

    return "127.0.0.1"
