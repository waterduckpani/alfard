# GitHub Skill

## Authentication
Uses a personal access token. Scopes needed: repo, read:user.

## Common operations
- List repos: list_repos
- Get an issue: get_issue with owner, repo, issue_number
- Create an issue: create_issue — irreversible, requires approval
- Get file contents: get_file_contents with owner, repo, path
- Search: search_repositories or search_code

## Rules
- Always confirm repo owner and name before any write operation
- Never push code without showing the diff to the user first
- For PRs: always show what will be merged before calling
  merge_pull_request
