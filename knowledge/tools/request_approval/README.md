### request_approval - Present Lx Output for User Approval

Store a ModuleRecord snapshot and present the Lx phase output to the user for
approval.  This replaces the old set_project(action="record", ...) which
unreliably auto-captured the "most recent assistant message".

**Parameters:**
- `phase` (string, required): Workflow phase — "L3", "L4", "L5", "L6", "L7", "L3.1"
- `module` (string, required): Current module name (e.g., "Auth")
- `content` (string, required): Approval request body in Markdown — natural language
  description, summary, contract details, algorithm steps, test results, etc.
- `files` (string[], optional): Attachments (附件). File paths for code files,
  drafts, test outputs, etc. Tool reads each file and includes its content
  for inline preview. Mainly used in L7 but any layer may attach files.
- `summary` (string, optional): One-line summary for snapshot index.

**When to use:**
- After completing each layer's output (L3-L7) for a module
- BEFORE the user approves — snapshot is stored atomically before the
  approval blocking step
- Before calling `crystallize` for the final crystal product (crystallize
  is called after user approval)

**When NOT to use:**
- For phase/module switching (use set_project activate)
- For exiting project context (use set_project deactivate)
- For storing final crystal products (use crystallize after approval)
