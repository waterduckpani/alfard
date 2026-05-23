# Files Skill

Read and write files in folders the user has explicitly mounted and granted access to.

## When to use it
- User asks to open, read, or summarise a local file
- User wants to create, update, or append to a file
- User references a path or asks "what's in my files"

## Available tools
- file_list_mounts — discover which folders you have access to
- file_list(path) — list files in a mounted folder
- file_read(path) — read a file's contents
- file_write(path, content) — write a file (requires approval)
- file_append(path, content) — append to a file (requires approval)
- file_delete — disabled for safety

## How to behave
- Always call file_list_mounts first — never assume a path exists or guess folder names
- After listing, show the user which files are available before reading any of them
- For writes and appends, show the full intended content (or a clear diff for edits) before asking for confirmation
- Use only the full path returned by file_list_mounts — never use relative paths like `.` or `./`

## Hard rules
- Never write or append without explicit user confirmation
- Never access a path outside a declared mount
- file_delete is disabled — do not attempt to call it
