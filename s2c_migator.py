import os
import json
import markdown
import shortuuid
from bs4 import BeautifulSoup
import re
import urllib.parse


class SliteToConfluenceMigrator:
    def __init__(self, base_dir, confluence_client, markdown_sanitiser, logger):
        self.base_dir = base_dir
        self.client = confluence_client

        self.structure = {}
        self.url_map = {}

        self.data_files = {
            "structure": {
                "path": os.path.join(self.base_dir, "structure.json"),
                "data": self.structure
            },
            "url_map": {
                "path": os.path.join(self.base_dir, "url_map.json"),
                "data": self.url_map
            }
        }

        self.markdown_sanitiser = markdown_sanitiser

        self.logger = logger

    def generate_url_map(self):
        if os.path.exists(self.data_files["url_map"]["path"]):
            self.logger.warning(f'Skipping structure generation: {self.data_files["structure"]["path"]} already exists.')

    def generate_structure_json(self, private_channels=[]):
        if os.path.exists(self.data_files["structure"]["path"]):
            self.logger.warning(f'Skipping structure generation: {self.data_files["structure"]["path"]} already exists.')
            return

        for channel in os.listdir(self.base_dir):
            private = False

            channel_path = os.path.join(self.base_dir, channel)
            if not os.path.isdir(channel_path):
                continue

            root_md = f"{channel}.md"
            root_md_path = os.path.join(channel_path, root_md)
            child_folder = os.path.join(channel_path, channel)

            if not os.path.isfile(root_md_path):
                self.logger.debug(f"Skipping '{channel}': No root markdown file found.")
                continue

            space_key = self._generate_space_key(channel)

            # Updating url map for later mapping of urls.
            self.url_map[root_md_path] = f"{self.client.base_space_url}/{space_key}"

            if channel in private_channels:
                private = True

            self.logger.debug(f"> Channel (Space): {channel} → key: {space_key}")
            self.structure[channel] = {
                "type": "channel",
                "private": private,
                "space_key": space_key,
                "space_id": None,
                "space_created": False,
                "page_id": None,
                "path": root_md_path,
                "uploaded": False,
                "media_uploaded": {},
                "media_links_fixed": False,
                "links_fixed": False,
                "children": {}
            }

            if os.path.isdir(child_folder):
                self.structure[channel]["children"] = self._parse_page_tree(child_folder, parent=channel)

        self._save_progress("structure")
        self._save_progress("url_map")

    def _parse_page_tree(self, folder_path, parent, parent_type="channel"):
        pages = {}
        for item in os.listdir(folder_path):
            if not item.endswith(".md"):
                continue

            page_name = os.path.splitext(item)[0]
            md_path = os.path.join(folder_path, item)

            self.logger.debug(f"    Page: {page_name} (parent: {parent})")

            media_folder_name = f"Media_{item[:-3]}"  # removes .md
            media_folder_path = os.path.join(folder_path, media_folder_name)

            media_uploaded = {}
            if os.path.isdir(media_folder_path):
                for media_file in os.listdir(media_folder_path):
                    media_uploaded[media_file] = {
                        "uploaded": False
                    }
                self.logger.debug(f"        Found media folder with {len(media_uploaded)} items")

            child_dir = os.path.join(folder_path, page_name)
            children = {}
            if os.path.isdir(child_dir):
                self.logger.debug(f"        Found child folder: {page_name}/")
                children = self._parse_page_tree(child_dir, parent=page_name, parent_type="page")

            pages[page_name] = {
                "type": "page",
                "path": md_path,
                "parent": parent if parent_type == "page" else None,
                "parent_id": None,
                "page_id": None,
                "uploaded": False,
                "media_uploaded": media_uploaded,
                "media_links_fixed": False,
                "links_fixed": False,
                "children": children
            }

        return pages

    def _generate_space_key(self, name):
        # TODO Not checking for collisions so this could explode
        words = name.upper().replace("-", " ").split()
        key = "".join(word[0] for word in words)[:10]
        if not key:
            key = name[:10].upper()
        return key

    def _save_progress(self, name):
        self.logger.debug(f"Saving progress on {name}")
        info = self.data_files[name]
        with open(info["path"], "w", encoding="utf-8") as f:
            json.dump(info["data"], f, indent=4)
        self.logger.debug(f"\n  Saved '{name}' to: {info['path']}")

    def _load_progress(self, name):
        info = self.data_files[name]
        if os.path.exists(info["path"]):
            with open(info["path"], "r", encoding="utf-8") as f:
                data = json.load(f)
                info["data"].clear()
                info["data"].update(data)
            self.logger.debug(f"\n  Loaded '{name}' from: {info['path']}")
        else:
            self.logger.error(f"{info['path']} not found !!!")

    def migrate_spaces(self):
        self._load_progress("structure")

        for channel_name, data in self.structure.items():
            if data.get("space_created"):
                self.logger.warning(f"Space already created for {channel_name}")
                continue

            # This is super flaky doing this all in one block :/
            self.logger.info(f"Creating space {channel_name}")

            is_private = data["private"]

            space_id, home_page_id = self.client.create_space(
                name=channel_name,
                key=data["space_key"],
                description=f"Imported from Slite {channel_name}",
                private=is_private
            )

            self.logger.info(f"Attempting to update home page for space {data['space_key']}")

            with open(data["path"], "r", encoding="utf-8") as file:
                raw_md = file.read()
                html = self.render_content_for_confluence(raw_md)

            page_version_number = self.get_page_version_number(home_page_id)
            page_version_number += 1

            r_page_id = self.client.update_page(
                page_id=home_page_id,
                title=f"{channel_name} Home",
                content=html,
                version=page_version_number,
                version_message="Updated homepage"
            )

            if r_page_id:
                self.logger.info(f"Updated homepage for {data['space_key']} {r_page_id}")
            else:
                self.logger.error(f"    Failed to update home page for {data['space_key']}")

            if space_id:
                data["space_id"] = space_id
                data["space_created"] = True
                self._save_progress("structure")

    def migrate_single_page(self, title, content_path, space_id, space_key, parent_id=None):
        """
        Migrate a single page to confluence
        :param title:
        :param content_path:
        :param space_id:
        :param space_key:
        :param parent_id:
        :return:
        """

        with open(content_path, "r", encoding="utf-8") as file:
            raw_md = file.read()
            html = self.render_content_for_confluence(raw_md)

        page_id = self.client.create_page(
            space_id=space_id,
            title=title,
            parent_id=parent_id,
            content=html
        )

        if page_id:
            self.logger.info(f"Uploaded page: {title} to space {space_key}")
            return page_id
        else:
            self.logger.error(f"Failed to upload page: {title} to space {space_key}")

    def migrate_pages(self):
        self._load_progress("structure")

        for channel, data in self.structure.items():
            space_id = data.get("space_id")
            self.logger.info(f"Migrating pages for {channel}: {space_id}")

            self._migrate_pages(data["children"], None, space_id=space_id, space_key=data["space_key"])

    def render_content_for_confluence(self, content):
        content = self.remove_slite_meta_data(content)
        # sanitises the markdown, attempting to remove 'erroneous' html safely.
        content = self.markdown_sanitiser.sanitise_content(content)

        content = self.markdown_sanitiser.fix_duplicate_links(content)
        # Convert !! style admonitions for parsing in html later
        content = self.markdown_sanitiser.convert_bang_admonitions(content)

        # Convert markdown to html
        html = markdown.markdown(content, extensions=["tables", "fenced_code"])

        try:
            html = self.convert_admonitions(html)
        except Exception as e:
            self.logger.error(f"Failed to convert admonitions {e}")

        html = self.convert_multi_line_code_blocks(html)

        return html

    def convert_multi_line_code_blocks(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        code_replacements = {}

        for i, pre_tag in enumerate(soup.find_all("pre")):
            code_tag = pre_tag.code
            if not code_tag:
                self.logger.warning("No code tag inside <pre>")
                continue

            code_text = code_tag.get_text()

            # Only convert multiline code blocks
            if "\n" in code_text:
                lines = code_text.strip("\n").split("\n")
                language = None
                class_attr = code_tag.get("class", [])

                for cls in class_attr:
                    if cls.startswith("language-"):
                        language = cls.replace("language-", "").strip()
                        break

                placeholder = f"__CODEBLOCK_{i}__"

                macro = soup.new_tag('ac:structured-macro', **{'ac:name': 'code'})

                if language:
                    param = soup.new_tag('ac:parameter', **{'ac:name': 'language'})
                    param.string = language
                    macro.append(param)

                body = soup.new_tag('ac:plain-text-body')
                body.string = placeholder
                macro.append(body)

                pre_tag.replace_with(macro)

                code_clean = "\n".join(lines)
                code_replacements[placeholder] = f"<![CDATA[{code_clean}]]>"

        html = str(soup)

        for placeholder, cdata in code_replacements.items():
            html = html.replace(placeholder, cdata)

        html = re.sub(
            r'<p>\s*(<ac:structured-macro[\s\S]+?</ac:structured-macro>)\s*</p>',
            r'\1',
            html,
            flags=re.MULTILINE
        )

        return html

    def convert_admonitions(self, html):
        soup = BeautifulSoup(html, 'html.parser')

        for blockquote in soup.find_all('blockquote'):
            paragraphs = blockquote.find_all('p')
            new_blocks = []

            for p in paragraphs:
                match_admonition = re.match(r'\[\!(\w+)\]', p.text.strip())

                if match_admonition:
                    admonition_type = match_admonition.group(1).lower()

                    # Only allow known Confluence macro types
                    macro_map = {
                        'note': 'info',  # Slite 'Note' is actually an info panel in Confluence for some reason.
                        'warning': 'warning',
                        'tip': 'tip',
                        'important': 'important',
                        'caution': 'caution'
                    }

                    macro_name = macro_map.get(admonition_type, 'info')

                    # Remove the [!TYPE] part
                    content = re.sub(r'^\[\!\w+\]\s*', '', p.decode_contents())

                    if not content:
                        self.logger.warning(f"Skipping empty admonition block of type '{macro_name}'.")
                        continue

                    self.logger.debug(
                        f"Admonition detected: type={macro_name}'), content=\"{content}\""
                    )
                else:
                    new_blocks.append(p)
                    continue

                # Build the Confluence macro
                macro = soup.new_tag('ac:structured-macro', **{'ac:name': macro_name})
                body = soup.new_tag('ac:rich-text-body')
                new_p = soup.new_tag('p')
                new_p.append(BeautifulSoup(content, 'html.parser'))
                body.append(new_p)
                macro.append(body)
                new_blocks.append(macro)

            blockquote.insert_after(*new_blocks)
            blockquote.decompose()

        return str(soup)

    def _migrate_pages(self, page_data, parent_id, space_id, space_key):
        for title, page_data in page_data.items():
            self.logger.info(f"Processing page {title} in channel {space_id}")

            if page_data.get("parent"):
                self.logger.debug(f"    Page {title} has parent {page_data['parent']}")

            if page_data.get("uploaded"):
                self.logger.debug(f"        Page {title} is already uploaded. Progressing.")
            else:
                content_path = page_data["path"]

                page_id = self.migrate_single_page(title, content_path, space_id, space_key, parent_id)

                if page_id:
                    page_data["page_id"] = page_id
                    page_data["uploaded"] = True

                    # Update url map for later updating of references
                    self.url_map[page_data["path"]] = f'{self.client.base_space_url}/{space_key}/pages/{page_id}'

                    self._save_progress("structure")
                    self._save_progress("url_map")
                else:
                    self.logger.error(f"ERROR: Unable to get page_id for {page_data['title']} !!!")

            if page_data.get("children") and page_data.get("page_id"):
                self._migrate_pages(
                    page_data=page_data["children"],
                    parent_id=page_data["page_id"],
                    space_id=space_id,
                    space_key=space_key
                )

    def remove_slite_meta_data(self, page_content):
        # Removes the meta data at the start of the page that Slite spits out.
        # Dumb if they change this as it could strip content. e.g. ->

        #
        # title: My Title Project
        # created at: Wed Nov 12 2024 13:13:31 GMT+0000 (Coordinated Universal Time)
        # updated at: Thu Mar 06 2025 15:40:25 GMT+0000 (Coordinated Universal Time)
        # ---
        #

        lines = page_content.splitlines()[6:]
        return "\n".join(lines).lstrip()

    def deduplicate_titles(self):
        self._load_progress("structure")
        self.logger.info("De-duplicating titles - Confluence does not allow duplicate titles in a single space.")

        for space_name, space_data in self.structure.items():
            self.logger.debug(f"Checking and updating duplicate titles in {space_name}...")
            title_map = {}
            used_titles = set()

            def collect_titles(pages, parent_title):
                for title, data in pages.items():
                    key = title.strip().lower()
                    title_map.setdefault(key, [])
                    title_map[key].append((pages, title, data, parent_title))

                    if data.get("children"):
                        collect_titles(data["children"], parent_title=title)

            collect_titles(space_data["children"], parent_title=space_name)

            for key, entries in title_map.items():
                if len(entries) <= 1:
                    continue

                for i, (pages_dict, old_title, data, parent_title) in enumerate(entries):
                    new_title = f"{old_title} ({parent_title})"
                    self.logger.debug(f"Updating {old_title} to {new_title}.")
                    if new_title in used_titles:
                        self.logger.debug(f"{new_title} is still not unique!")
                        new_title = f"{new_title} {shortuuid.ShortUUID().random(8)}"
                        self.logger.debug(f"New title is {new_title}")
                        used_titles.add(new_title)
                    else:
                        used_titles.add(new_title)

                    pages_dict[new_title] = pages_dict.pop(old_title)

        self._save_progress("structure")

    def replace_local_slite_links(self, markdown):
        self._load_progress("url_map")
        pattern = r'\[([^\]]+)]\(([^)]+)\)'

        def replacer(match):
            text, link = match.groups()
            sanitised_link = urllib.parse.unquote(link)
            sanitised_link = f"{self.base_dir}{sanitised_link}"

            if sanitised_link in self.url_map:
                self.logger.debug(f"REPLACING: [{text}]({link}) -> [{text}]({self.url_map[sanitised_link]})")
                return f"[{text}]({self.url_map[sanitised_link]})"
            return match.group(0)
        return re.sub(pattern, replacer, markdown)

    def fix_all_references(self):
        self._load_progress("structure")

        def _fix_all_references(pages):
            for title, page_data in pages.items():
                self.logger.debug(f"Checking links for {title}")
                page_path = page_data.get("path")
                page_id = page_data.get("page_id")

                if not page_id:
                    self.logger.warning(f"No page id found for {title}")
                    continue

                if page_data.get("links_fixed"):
                    self.logger.debug(f"Links already fixed for {page_path}")
                else:
                    with open(page_path, "r", encoding="utf-8") as file:
                        original_md = file.read()

                    updated_md = self.replace_local_slite_links(original_md)

                    if updated_md != original_md:
                        content = self.render_content_for_confluence(content=updated_md)

                        # Get and increment the version number
                        page_version_number = self.get_page_version_number(page_id)
                        page_version_number += 1

                        success = self.client.update_page(
                            page_id,
                            title,
                            content,
                            page_version_number,
                            "Replacing Slite references with confluence urls"
                        )
                        if success:
                            page_data["links_fixed"] = True
                            self.logger.info(f"Updated links for {title}")
                            self._save_progress("structure")
                        else:
                            self.logger.error(f"Failed to update links for {title}")
                    else:
                        self.logger.debug(f"No links to fix for {title}")

                if page_data.get("children"):
                    _fix_all_references(page_data["children"])

        for channel, data in self.structure.items():
            self.logger.info(f"\nFixing urls in space {channel}")
            _fix_all_references(data["children"])

    def get_page_version_number(self, page_id):
        page = self.client.get_page(page_id)
        return page["version"]["number"]

    def migrate_media(self):
        # Step 1 identify associated media with the respective channel / page.
        # Step 2 upload as an attachment using the confluence client
        # Step 3 upload returns identifier for attachment, replace reference to this in MD and PUT to update in the page
        self._load_progress("structure")

        for channel, data in self.structure.items():
            self._migrate_media(channel, data["children"])

    def _migrate_media(self, channel, pages):
        for title, page_data in pages.items():
            page_path = page_data.get("path")
            page_id = page_data.get("page_id")

            media_files = page_data.get("media_uploaded", {})
            if media_files:
                self.logger.debug(f"Checking media for: {title}")

                media_path_title = f"Media_{os.path.basename(page_path)[:-3]}"  # removes .md
                media_directory = os.path.join(*page_path.split('/')[:-1], media_path_title)

                if not os.path.exists(media_directory):
                    self.logger.warning(f"Media folder missing: {media_directory}")
                else:
                    for filename, status in media_files.items():
                        if status["uploaded"]:
                            self.logger.debug(f"Already uploaded: {filename}")
                            continue

                        full_path = os.path.join(media_directory, filename)

                        if not os.path.isfile(full_path):
                            self.logger.error(f"File missing: {full_path}")
                            status["error"] = "file not found"
                            continue

                        try:
                            self.logger.info(f"  Uploading: {filename}")
                            self.client.upload_attachment(page_id, full_path)
                            status["uploaded"] = True
                            self.logger.info(f"Uploaded: {filename}")

                            self._save_progress("structure")  # Save after each successful upload

                        except Exception as e:
                            self.logger.error(f"Upload failed for {filename}: {e}")
                            status["error"] = str(e)

                    if page_data["media_links_fixed"]:
                        self.logger.debug(f"Already linked media for: {title}")
                        continue

                    with open(page_path, "r") as file:
                        markdown = file.read()

                    for filename, status in media_files.items():
                        url_encoded_filename = urllib.parse.quote(filename)

                        atlassian_attachment_url = f"{self.client.base_url}/download/attachments/{page_id}/{url_encoded_filename}"
                        self.logger.debug(f"Attachment url = {atlassian_attachment_url}")

                        markdown = re.sub(
                            rf'!\[([^\]]*)\]\(([^)]*{re.escape(url_encoded_filename)})\)',
                            rf'![\1]({atlassian_attachment_url})',
                            markdown
                        )

                        self.logger.debug(f"Updating markdown for {filename} → {atlassian_attachment_url}")

                    html = self.render_content_for_confluence(markdown)

                    # Get an increment the version number
                    page_version_number = self.get_page_version_number(page_id)
                    page_version_number += 1

                    response = self.client.update_page(
                        page_id=page_id,
                        title=title,
                        content=html,
                        version=page_version_number,
                        version_message="Linked media"
                    )

                    if response:
                        page_data["media_links_fixed"] = True
                        self._save_progress("structure")
                        self.logger.info(f"Media links for {title} resolved")
                    else:
                        self.logger.error(f"Error updating markdown for {title}")

            # Recurse into child pages
            if page_data.get("children"):
                self._migrate_media(channel, page_data["children"])
