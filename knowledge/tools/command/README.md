<!--
This file is part of Crystal-Sculpt-Diffus-Coder.
Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.
-->

### `command` - Execute System Commands

- **Purpose**: Execute system commands in a sandboxed subprocess (`shell=False`).
- **Input**:
```json
{
    "command": "Full command string to execute"
}
```
- `command`: **string** (required; pass the complete system command string)
- **Output**: Standard output and standard error output of the command. Returns exit code if non-zero.
- **Security Model — Three-tier classification**:

| Tier | Commands | Behavior |
|------|----------|----------|
| **Safe** | `ls`, `cat`, `head`, `tail`, `wc`, `sort`, `uniq`, `grep`, `find`, `pwd`, `echo`, `whoami`, `date`, `time`, `env`; `git status/log/diff/branch/show` | Execute directly, no confirmation |
| **Dangerous** | `mkdir`, `touch`, `mv`, `cp`, `chmod`, `chown`; most `git` subcommands; `pip`/`npm`/`npx`; `curl`/`wget`; `tar`/`zip`/`unzip`; `python`/`node`/`go`/`rustc`/`cargo`/`java`/`javac` | ⚠️ Warning + user confirmation required |
| **Forbidden** | `rm`, `del`, `rmdir`, `rd`, `erase`, `shred`, `unlink` | Hard blocked, never executes |

  - Whitelist-based: only commands in the permitted list below can be executed.
  - **Deletion commands are prohibited**: `rm`, `del`, `rmdir`, `rd`, `erase`, `shred`, `unlink` are blocked regardless of context.
  - Commands run via `subprocess.run(shell=False)` with a 30-second timeout.

### Permitted Commands

| Category | Commands |
|----------|----------|
| File ops | `ls`, `dir`, `cat`, `head`, `tail`, `wc`, `sort`, `uniq`, `grep`, `find`, `pwd`, `mkdir`, `touch`, `mv`, `cp`, `chmod`, `chown` |
| System | `echo`, `whoami`, `date`, `time`, `env` |
| Languages | `python`, `python3`, `python3-m`, `pip`, `pip3`, `node`, `npm`, `npx`, `go`, `rustc`, `cargo`, `java`, `javac` |
| VCS | `git` |
| Network | `curl`, `wget` |
| Archives | `tar`, `gzip`, `gunzip`, `zip`, `unzip` |

Commands NOT in this list will be rejected with an error listing all permitted commands.

**Usage notes**:
- `cd` does not work as expected (subprocess exits immediately after changing directory). Use absolute paths instead.
- Package managers (`apt`, `brew`, etc.) are not in the permitted list — use language-specific package managers (`pip`, `npm`, `cargo`) instead.
- `chmod` and `chown` are permitted but require confirmation with a warning.
