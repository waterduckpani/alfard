# Google Drive Skill

## Available tools
- gdrive_list_files — list files in Google Drive
- gdrive_search(query) — search for files by name or content
- gdrive_get_file(file_id) — get metadata for a specific file

## Usage
When the user asks about Google Drive files, always call
gdrive_list_files first to see what's available.
Use gdrive_search to find specific files by name or type.

## Examples
- "list my drive files" → gdrive_list_files()
- "find my spreadsheets" → gdrive_search("mimeType='application/vnd.google-apps.spreadsheet'")
- "find files named report" → gdrive_search("name contains 'report'")
