# Files Skill

## Available tools
- file_list_mounts — discover which folders you have access to
- file_list(path) — list files in a mounted folder
- file_read(path) — read a file's contents
- file_write(path, content) — write a file (requires approval)
- file_append(path, content) — append to a file (requires approval)
- file_delete — disabled for safety

## ALWAYS start with file_list_mounts
When the user asks about files, ALWAYS call file_list_mounts
first to see what folders are available. Never guess paths.

## Use full paths
Always use the full path returned by file_list_mounts.
Example: /Users/bharat/Desktop/test-mount/hello.txt
Never use relative paths like . or ./
