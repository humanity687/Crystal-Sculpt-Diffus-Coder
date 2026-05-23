"""
Execute System Command Tool
Allows AI to execute system commands with a whitelist-based security model.
"""

import shlex
import subprocess
import locale

# System encoding for decoding command output (e.g. cp936 on Chinese Windows)
_SYS_ENCODING = locale.getpreferredencoding()

# Allowed command whitelist — only these executables can be run
_ALLOWED_COMMANDS = {
    "echo", "cat", "head", "tail", "wc", "sort", "uniq", "grep",
    "find", "ls", "dir", "pwd", "whoami", "date", "time", "env",
    "mkdir", "touch", "mv", "cp", "chmod", "chown",
    "git", "python", "python3", "python3-m", "pip", "pip3",
    "npm", "node", "npx", "cargo", "rustc", "go", "java", "javac",
    "curl", "wget", "tar", "gzip", "gunzip", "zip", "unzip",
}


def execute(command: str) -> str:
    """
    Execute system command (whitelist-based security model).

    Args:
        command: Command string to execute

    Returns:
        Command execution result or error message
    """
    # Parse command into list form (shell=False safe)
    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"❌ Error: Failed to parse command: {e}"

    if not args:
        return "❌ Error: Empty command"

    # Check executable against whitelist
    executable = args[0]
    if executable not in _ALLOWED_COMMANDS:
        return (
            f"❌ Error: Command '{executable}' is not in the allowed list. "
            f"Permitted commands: {', '.join(sorted(_ALLOWED_COMMANDS))}"
        )

    # Block deletion operations explicitly (e.g. rm, del, rmdir) as final safety net
    dangerous = {"rm", "del", "rmdir", "rd", "erase", "shred", "unlink"}
    if executable in dangerous:
        return (
            "❌ Error: Deletion commands are prohibited. FranxAgent security rules "
            "do not allow direct deletion of files or folders."
        )

    try:
        result = subprocess.run(args, shell=False, capture_output=True, timeout=30)

        # Decode with system encoding first (e.g. cp936 on Chinese Windows), fall back to UTF-8
        def safe_decode(data: bytes) -> str:
            for enc in (_SYS_ENCODING, "utf-8"):
                try:
                    return data.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return data.decode("utf-8", errors="replace")

        stdout = safe_decode(result.stdout)
        stderr = safe_decode(result.stderr)

        # Build output: stdout first, then stderr if present
        parts = []
        if stdout.strip():
            parts.append(stdout.strip())
        if stderr.strip():
            parts.append(f"[stderr]\n{stderr.strip()}")
        output = "\n".join(parts)

        if result.returncode != 0:
            prefix = f"Command returned non-zero exit code {result.returncode}"
            output = f"{prefix}\n{output}" if output else prefix

        return output or "Command executed successfully (no output)"

    except subprocess.TimeoutExpired:
        return "Error: Command execution timed out"
    except FileNotFoundError:
        return f"❌ Error: Command '{executable}' not found on the system"
    except Exception as e:
        return f"Execution failed: {e}"
