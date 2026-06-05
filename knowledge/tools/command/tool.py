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
    "git", "python", "python3", "pip", "pip3",
    "npm", "node", "npx", "cargo", "rustc", "go", "java", "javac",
    "curl", "wget", "tar", "gzip", "gunzip", "zip", "unzip",
}

# Commands that delete files — always forbidden
_FORBIDDEN = {"rm", "del", "rmdir", "rd", "erase", "shred", "unlink"}

# Safe commands — read-only, no side effects, no confirmation needed
_SAFE_EXECUTABLES = {
    "ls", "dir", "pwd", "whoami", "date", "time", "env",
    "cat", "head", "tail", "wc", "sort", "uniq", "grep", "find",
    "echo",
}

# Safe git subcommands — read-only operations
_SAFE_GIT_SUBCOMMANDS = {
    "status", "log", "diff", "branch", "show",
    "stash",  # only "list" is safe, but we check below
    "remote",  # "remote -v" is safe
    "tag",  # "tag -l" / "tag --list" is safe
    "rev-parse", "rev-list", "ls-files", "ls-tree",
    "config",  # only --get is safe
    "describe", "name-rev", "shortlog",
    "whatchanged", "reflog",
    "grep", "blame", "archive",
}


def classify_command(command: str) -> str:
    """
    Classify a command into one of three security tiers.

    Returns:
        "safe"      — read-only, no confirmation needed
        "dangerous" — modifies state, requires confirmation with warning
        "forbidden" — deletion commands, never allowed
    """
    try:
        args = shlex.split(command)
    except ValueError:
        return "dangerous"  # Can't parse — be cautious

    if not args:
        return "dangerous"

    executable = args[0]

    # Forbidden check
    if executable in _FORBIDDEN:
        return "forbidden"

    # Whitelist check — unknown executables are dangerous
    if executable not in _ALLOWED_COMMANDS:
        return "dangerous"

    # Safe executables (no subcommand complexity)
    if executable in _SAFE_EXECUTABLES:
        return "safe"

    # Git — classify by subcommand
    if executable == "git" and len(args) > 1:
        subcmd = args[1]
        # Handle flags before subcommand (e.g. git -C /path status)
        if subcmd.startswith("-"):
            for a in args[1:]:
                if not a.startswith("-"):
                    subcmd = a
                    break
        if subcmd in _SAFE_GIT_SUBCOMMANDS:
            # Special cases within safe subcommands
            if subcmd == "stash" and len(args) > 2:
                stash_action = args[2]
                if stash_action not in ("list", "show"):
                    return "dangerous"
            if subcmd == "remote" and len(args) > 2:
                # "git remote add/remove/set-url" are dangerous
                if args[2] in ("add", "remove", "rm", "set-url", "set-head", "rename"):
                    return "dangerous"
            if subcmd == "tag" and len(args) > 2:
                # "git tag -d/--delete" is dangerous
                if args[2] in ("-d", "--delete"):
                    return "dangerous"
            if subcmd == "config" and len(args) > 2:
                # Only --get / --get-regexp is safe
                if args[2] not in ("--get", "--get-regexp", "--get-all", "-l", "--list"):
                    return "dangerous"
            if subcmd == "branch" and len(args) > 2:
                # "git branch -d/-D/-m/-M" modifies branches
                if args[2] in ("-d", "-D", "--delete", "-m", "-M", "--move", "-c", "--copy"):
                    return "dangerous"
            return "safe"
        return "dangerous"

    # Everything else (mkdir, touch, mv, cp, chmod, chown,
    # python*, node, npm, pip*, curl, wget, tar*, zip*, go, rustc, cargo, java, javac)
    return "dangerous"


schema = {
    "type": "function",
    "function": {
        "name": "command",
        "description": (
            "Execute a system command with whitelist-based security. "
            "Read-only commands (ls, cat, git log, etc.) run directly. "
            "State-modifying commands (mkdir, touch, mv, pip install, etc.) require user confirmation. "
            "Deletion commands (rm, del) are forbidden. "
            "Shell operators (&&, |, >, <) are not supported — run one command at a time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
            },
            "required": ["command"],
        },
    },
}


def execute(command: str, **kwargs) -> str:
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

    # Detect shell operators that can't work with shell=False
    _SHELL_OPERATORS = {"&&", "||", "|", ";", ">", "<", ">>", "&"}
    if any(op in args for op in _SHELL_OPERATORS):
        return (
            "Error: Shell operators (&&, ||, |, ;, >, <, &) are not supported. "
            "Run one command at a time, or use a script file for complex operations."
        )

    # Check executable against whitelist
    executable = args[0]
    if executable not in _ALLOWED_COMMANDS:
        return (
            f"❌ Error: Command '{executable}' is not in the allowed list. "
            f"Permitted commands: {', '.join(sorted(_ALLOWED_COMMANDS))}"
        )

    # Block deletion operations explicitly as final safety net
    if executable in _FORBIDDEN:
        return (
            "❌ Error: Deletion commands are prohibited. Crystal-Sculpt-Diffus-Coder security rules "
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
