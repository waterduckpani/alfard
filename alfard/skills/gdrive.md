# Google Drive Skill

Access Google Drive via the `gog` shell command. Always use the 
shell execution tool — there are no Drive Python functions.

## Safety flags — always include
--json        clean output for parsing
--no-input    fail instead of prompting

## Listing and searching
gog drive ls --json --no-input
gog drive ls --parent <folderId> --json --no-input
gog drive search "quarterly report" --json --no-input

## Reading files
gog docs cat <docId> --json --no-input
gog sheets get <spreadsheetId> 'Sheet1!A1:B10' --json --no-input

## Uploading and downloading
gog drive upload ./file.pdf --parent <folderId> --no-input
gog drive download <fileId> --out ./file.pdf --no-input

## Rules
- Never share or make files public without explicit user confirmation
- Always search before assuming a file ID
- If a command fails show the error and ask how to proceed
