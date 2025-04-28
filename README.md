# Slite2Confluence
This CLI tool automates the migration of content from a Slite markdown backup into Confluence
It handles
* Markdown sanitisation
* Admonitions, referential integrity (links between docs), code blocks
* Space and page creation in confluence
* Title deduplication 
* Media migration

## Setup
1. Install pipenv if you don't already have it
```bash
pip install pipenv
```

1. Install project dependencies

```
pipenv install
```
2. Create .env file
```bash
cp .env.example .env
```

3. Edit your .env file

You need to include you confluence API token, your confluence user (email address) and your jira subdomain.

## Usage

Inside the project repo enter virtual env with `pipenv shell`

### Full Migration

For a full migration you will need to have a local _markdown_ copy of your Slite backup

Run the command, pointing to the _channels_ directory of your backup
```bash
python main.py execute-migration -sd "<your_path>/slite-backup/channels"
```

For every Slite channel it will create a respective Space in confluence, and migrate all pages therein.

Progress is tracked locally in a .json file called structure.json which will get created in your channels directory.

This is flaky but in theory idempotent, so if there is an exception you can run the command again and it will pick up where you left off.

**If you the process dies or you kill it whilst it's writing the json file you will have to unpick this yourself.**

### Private Channels
If you have private channels pass a flag with a comma separated list of the channel names. This will give ONLY your user access and you will have to resolve access / user groups post-migration

E.g.

```bash
python main.py execute-migration -sd "<your_path>/slite-backup/channels" -pc "Admin,TopSecret"
```

### Single Page
You can also migrate a single markdown page into confluence.

**This does not handle fixing internal links, or migrating attachments. It is intended for small manual migrations or testing**

Example:

```bash
pipenv run python main.py migrate-single-page \
  --slite-directory "/slite-backup/channels" \
  --title "Migration Test Page" \
  --path ./slite-backup/channels/misc/test-page.md \
  --space-id 123456789 \
  --space-key DEMO
```

## CLI

`main.py` before specifying the command the log level can be set.

| Option | Required | Description |
|:-------|:---------|:------------|
| `--log-level` | ❌ | Set the log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) — defaults to `INFO` |

`execute-migration`

| Option | Required | Description |
|:-------|:---------|:------------|
| `-sd`, `--slite-directory` | ✅ | Path to the Slite `channels/` directory |
| `-pc`, `--private-channels` | ❌ | Comma-separated list of private channel names (must match exactly) |

`migrate-single-page`

| Option | Required | Description |
|:-------|:---------|:------------|
| `-sd`, `--slite-directory` | ✅ | Path to the Slite `channels/` directory (used for resolving references, if needed) |
| `-t`, `--title` | ✅ | Title of the page to create |
| `-f`, `--path` | ✅ | Path to the markdown file for the page |
| `--space-id` | ✅ | Confluence Space ID where the page will be created |
| `--space-key` | ✅ | Confluence Space Key (short code for the space) |
| `--parent-id` | ❌ | (Optional) Confluence Parent Page ID to nest the new page under |
