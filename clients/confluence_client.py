import os.path
import click
import requests
import time
import json
from requests.auth import HTTPBasicAuth


class ConfluenceClient:
    def __init__(self, api_key, domain, user, logger):
        self.base_url_v1 = f"https://{domain}.atlassian.net/wiki/rest/api"
        self.base_url_v2 = f"https://{domain}.atlassian.net/wiki/api/v2"

        self.base_space_url = f"https://{domain}.atlassian.net/wiki/spaces"
        self.base_url = f"https://{domain}.atlassian.net/wiki"

        self.auth = HTTPBasicAuth(user, api_key)
        self.headers = self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self.logger = logger

    def _make_request(self, method, request_url, json_payload=None, max_retries=5, headers=None, files=None):
        self.logger.debug(f"Making Request: {method.upper()} - {request_url}")

        data_payload = None

        final_headers = self.headers

        if json_payload:
            data_payload = json.dumps(json_payload)

        # Optionally pass in headers to override the default, used for uploading attachments currently.
        if headers:
            final_headers = headers

        for attempt in range(1, max_retries + 1):
            response = requests.request(
                method=method,
                url=request_url,
                headers=final_headers,
                auth=self.auth,
                data=data_payload,
                files=files
            )

            self.logger.debug(f"  Status: {response.status_code}")

            if response.status_code < 400:
                return response

            if response.status_code in (429, 500, 502, 503, 504):
                wait_time = 2 ** (attempt - 1)
                self.logger.warning(f"Request failed (attempt {attempt}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            self.logger.error(f"Error on request: {response.status_code}: {response.text}")
            break

        self.logger.critical("All retry attempts failed.")
        return response

    def create_space(self, name, key, description=None, private: bool = False):
        url = f"{self.base_url_v1}/space"

        if private:
            # If space is private just create under the user.
            # They will have to sort permissions and user groups out post-migration.
            url = f"{self.base_url_v1}/space/_private"

        payload = {
            "name": name,
            "key": key,
            "description": {
                "value": description,
                "representation": "plain"
            }
        }

        try:
            response = self._make_request("POST", url, payload)
            self.logger.debug(f"Received response (truncated): {response.text.splitlines()[4:]}")
            if response.status_code in (200, 201):
                return response.json().get("id"), response.json()["homepage"].get("id")

            raise Exception(f"Error Creating confluence space. Status: {response.status_code} \n Body {response.text}")
        except Exception as e:
            raise Exception(f"Error creating space '{name}' with key '{key}': {e}")

    def create_page(self, space_id, title, parent_id, content):
        url = f"{self.base_url_v2}/pages"

        payload = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "parentId": parent_id,
            "body": {
                "representation": "storage",
                "value": content
            }
        }

        try:
            response = self._make_request("POST", url, payload)
            self.logger.debug(f"Received response (truncated): {response.text.splitlines()[4:]}")

            if response.status_code in (200, 201):
                page_id = response.json().get("id")
                self.logger.info(f" Created page '{title}' with id {page_id}")
                return page_id

            if response.status_code == 400 and "A page already exists with the same TITLE" in response.text:
                raise Exception(f"Page with title '{title}' already exists in the space.")

            raise Exception(
                f"Failed to create page '{title}'. Status: {response.status_code}\nResponse: {response.text}")

        except Exception as e:
            raise Exception(f"Error creating page '{title}': {e}")

    def update_page(self, page_id, title, content, version, version_message):
        url = f"{self.base_url_v2}/pages/{page_id}"

        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": content
            },
            "version": {
                "number": version,
                "message": version_message
            }
        }

        try:
            response = self._make_request("PUT", url, payload)

            if response.status_code in (200, 201):
                page_id = response.json().get("id")
                self.logger.info(f"Updated page '{title}' with id {page_id}")
                return page_id

            raise Exception(
                f" Failed to update page '{title}'. Status: {response.status_code}\nResponse: {response.text}")
        except Exception as e:
            raise Exception(f"Error updating page '{title}': {e}")

    def get_page(self, page_id):
        url = f"{self.base_url_v2}/pages/{page_id}"
        try:
            response = self._make_request("GET", url)
            if response.status_code == 200:
                return response.json()
            raise Exception(
                f" Failed to get page '{page_id}'. Status: {response.status_code}\nResponse: {response.text}")
        except Exception as e:
            raise Exception(f"Error getting page '{page_id}': {e}")

    def upload_attachment(self, page_id, file_path, comment="Uploaded from Slite"):
        url = f"{self.base_url_v1}/content/{page_id}/child/attachment"

        with open(file_path, "rb") as file:
            files = {
                "file": (os.path.basename(file_path), file),
                "minorEdit": (None, "true"),
                "comment": (None, comment, "text/plain; charset=utf-8")
            }

            headers = {
                "X-Atlassian-Token": "nocheck"
            }

            response = self._make_request("POST", url, json_payload=None, max_retries=3, headers=headers, files=files)

        if response.status_code not in (200, 201):
            raise Exception(
                click.style(f" Attachment upload failed: {response.status_code} — {response.text}", fg="red")
            )

        result = response.json()["results"][0]
        self.logger.debug(f"Uploaded attachment: {result['title']} → /download/attachments/{page_id}/{result['title']}")

        return result

    def set_space_homepage(self, space_key, page_id):
        url = f"{self.base_url_v1}/space/{space_key}"

        payload = {
            "homepage": {
                "id": page_id
            }
        }

        try:
            response = self._make_request("PUT", url, payload)
            if response.status_code in (200, 201):
                space_id = response.json().get("id")
                self.logger.debug(f" Setting {space_key} homepage to {page_id}")
                return space_id

            raise Exception(
                f" Failed to set space home page '{page_id}'. Status: {response.status_code}\nResponse: {response.text}")
        except Exception as e:
            raise Exception(f"Error setting space homepage '{page_id}': {e}")
