import os
import click
import logging
from click_loglevel import LogLevel
from dotenv import load_dotenv
from clients.confluence_client import ConfluenceClient
from s2c_migator import SliteToConfluenceMigrator
from utils.markdown_sanitiser import MarkdownHtmlSanitiser

load_dotenv()

api_key = os.getenv("CONFLUENCE_API_KEY")
user = os.getenv("CONFLUENCE_USER")

jira_domain = os.getenv("JIRA_DOMAIN")

logger = logging.getLogger("MigratorLogger")

confluence_client = ConfluenceClient(api_key, jira_domain, user, logger)
markdown_sanitiser = MarkdownHtmlSanitiser(logger)


class ClickColorFormatter(logging.Formatter):
    LOG_COLORS = {
        logging.DEBUG: "blue",
        logging.INFO: "white",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "bright_red"
    }

    def format(self, record):
        # Format string: [TIME] [LEVEL] message
        log_time = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        msg = record.getMessage()

        formatted = f"[{log_time}] [{level}] {msg}"
        color = self.LOG_COLORS.get(record.levelno)
        return click.style(formatted, fg=color)


@click.group()
@click.pass_context
@click.option("--log-level", type=LogLevel(), default=logging.INFO)
def cli(ctx, log_level):
    sh = logging.StreamHandler()
    sh.setLevel(log_level)
    sh.setFormatter(ClickColorFormatter())
    logger.addHandler(sh)
    logger.setLevel(log_level)
    logger.debug("Click group initiated")


@cli.command()
@click.option("--slite-directory", "-sd", help="Directory of Slite channels backup - for example slite-backup/channels")
@click.option("--private-channels", "-pc", help="Comma-seperated list of private channel names (must be EXACT match)")
def execute_migration(slite_directory, private_channels):
    click.echo(f"Migrating from: {slite_directory}")

    # Private channels will get migrated in the users name ONLY.
    # Permissions/user groups will have to be created manually
    private_channel_set = set(map(str.strip, private_channels.split(","))) if private_channels else set()

    migrator = SliteToConfluenceMigrator(slite_directory, confluence_client, markdown_sanitiser, logger)

    migrator.generate_structure_json(
        private_channels=private_channel_set
    )

    migrator.deduplicate_titles()
    migrator.migrate_spaces()
    migrator.migrate_pages()

    migrator.migrate_media()  # has intended side effect of fixing references
    migrator.fix_all_references()



@cli.command()
@click.option("--page-id", "-p", required=True, help="Confluence Page ID to upload attachment to")
@click.option("--path", "-f", required=True, type=click.Path(exists=True), help="Path to the attachment file")
def upload_attachment(page_id, path):
    """Upload a file as an attachment to a Confluence page."""
    logger.info(f"Uploading {path} to page {page_id}")
    try:
        result = confluence_client.upload_attachment(page_id, path)
        logger.info(f"Attachment uploaded: {result['title']}")
        logger.info(f"Attachment URL: /download/attachments/{page_id}/{result['title']}")
    except Exception as e:
        logger.error(f"Upload failed: {e}")


@cli.command()
@click.option("--slite-directory", "-sd", required=True, help="Directory of Slite channels backup")
@click.option("--title", "-t", required=True, help="Title of the page to create")
@click.option("--path", "-f", required=True, type=click.Path(exists=True), help="Path to the markdown file")
@click.option("--space-id", required=True, help="Confluence Space ID")
@click.option("--space-key", required=True, help="Confluence Space Key")
@click.option("--parent-id", required=False, help="Parent Page ID (optional)")
def migrate_single_page(slite_directory, title, path, space_id, space_key, parent_id):
    """
    This will migrate a single page. It cannot handle fixing references to other documents, or attachments.
    These will have to be done manually.
    :param slite_directory:
    :param title:
    :param path:
    :param space_id:
    :param space_key:
    :param parent_id:
    :return:
    """
    logger.info(f"Migrating single page {title} from {path} into space {space_key}")

    migrator = SliteToConfluenceMigrator(slite_directory, confluence_client, markdown_sanitiser, logger)

    page_id = migrator.migrate_single_page(
        title=title,
        content_path=path,
        space_id=space_id,
        space_key=space_key,
        parent_id=parent_id
    )

    migrator.fix_single_page_references(title, path, page_id)

    if page_id:
        logger.info(f"Page created successfully with ID: {page_id}")
    else:
        logger.error(f"ERROR: Page creation failed.")


@cli.command()
@click.option("--slite-directory", "-sd", required=True, help="Directory of Slite channels backup")
@click.option("--title", "-t", required=True, help="Title of the page to create")
@click.option("--path", "-f", required=True, type=click.Path(exists=True), help="Path to the markdown file")
@click.option("--page-id", "-pid", required=True, help="Confluence page id")
def migrate_media_single_page(slite_directory, title, path, page_id):
    logger.info(f"Updating media for {title}")

    migrator = SliteToConfluenceMigrator(slite_directory, confluence_client, markdown_sanitiser, logger)
    upload_status, links_fixed, media_links_fixed = migrator.migrate_media_for_single_page(title, path, page_id)

    for file in upload_status:
        logger.debug(f"{file} uploaded = {upload_status[file]['uploaded']}")

    logger.debug(f"Links Fixed = {links_fixed}")
    logger.debug(f"Media Links Fixed = {media_links_fixed}")


if __name__ == "__main__":
    cli()
