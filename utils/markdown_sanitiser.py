import re
from bs4 import BeautifulSoup
from markdownify import markdownify as md


class MarkdownHtmlSanitiser:
	def __init__(self, logger):
		self.valid_html_tags = [
			"a", "abbr", "address", "area", "article", "aside", "audio", "b", "base", "bdi", "bdo", "blockquote",
			"body",
			"br", "button", "canvas", "caption", "cite", "code", "col", "colgroup", "data", "datalist", "dd", "del",
			"details", "dfn", "dialog", "div", "dl", "dt", "em", "embed", "fieldset", "figcaption", "figure", "footer",
			"form", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "i", "iframe", "img", "input",
			"ins", "kbd", "label", "legend", "li", "link", "main", "map", "mark", "meta", "meter", "nav", "noscript",
			"object", "ol", "optgroup", "option", "output", "p", "param", "picture", "pre", "progress", "q", "rp", "rt",
			"ruby", "s", "samp", "script", "section", "select", "small", "source", "span", "strong", "style", "sub",
			"summary", "sup", "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time", "title",
			"tr", "track", "u", "ul", "var", "video", "wbr"
		]
		self.logger = logger

	def _is_valid_html_tag(self, html):
		try:
			soup = BeautifulSoup(html, "html.parser")
			first = soup.find()
			return first and first.name.lower() in self.valid_html_tags
		except Exception:
			return False

	def _remove_code_blocks(self, text):
		# Remove triple-backtick code blocks (multiline-safe)
		text = re.sub(r'```[\s\S]+?```', '', text, flags=re.MULTILINE)

		# Remove inline backtick spans `like <td>`
		text = re.sub(r'`[^`]+`', '', text)

		return text

	def sanitise_content(self, content, file_path=""):
		# Match inline tags: <tag>...</tag> or self-closed <br />
		html_tag_pattern = re.compile(
			r'<\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>(?:.*?)</\1>|<\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*/?>',
			flags=re.IGNORECASE
		)

		content_for_sanitising = self._remove_code_blocks(content)

		for match in html_tag_pattern.finditer(content_for_sanitising):
			html_snippet = match.group(0)
			html_tag = (match.group(1) or match.group(2)).lower()

			if html_tag not in self.valid_html_tags:
				if "http" in html_snippet:
					# Don't touch auto links like <https://potato.com>
					continue
				else:
					self.logger.debug(f"{html_snippet} is not a valid html tag. Escaping angular brackets...")
					sanitised_snippet = html_snippet.replace("<", "&lt;").replace(">", "&gt;")
					content = content.replace(html_snippet, sanitised_snippet)
					continue

			self.logger.debug(f"Full html snippet = '{html_snippet}' with tag {html_tag}")

			sanitised_snippet = md(
				html_snippet,
				escape_asterisks=False,
				escape_underscores=False,
				escape_misc=False,
				newline_style=""
							  ""
			)

			content = content.replace(html_snippet, sanitised_snippet)

		return content

	def fix_duplicate_links(self, content):
		link_pattern = re.compile(r'(\<https.*\>|https.*)\n*(\[\\\[(http.*)\\]]\(http.*\))', re.MULTILINE)
		self.logger.debug("Fixing duplicate links")

		def replacer(match):
			raw_link = match.group(1).strip().lstrip('<').rstrip('>')
			markdown_url = match.group(3).strip()

			if raw_link == markdown_url:
				self.logger.debug(f"Able to replace:   {raw_link} == {markdown_url}")
				return f"[{raw_link}]({raw_link})"
			else:
				self.logger.debug(f"Unable to replace: {raw_link} != {markdown_url}")
				return f"{raw_link}\n[{markdown_url}]({markdown_url})"

		return link_pattern.sub(replacer, content)

	def convert_bang_admonitions(self, content):
		"""
		Convert lines starting with "!!" into [!NOTE] blockquotes for later parsing into confluence admonishments

		:param content: markdown
		:return:
		"""
		converted_lines = []
		lines = content.splitlines()

		for line in lines:
			if line.startswith("!!"):
				bang_content = line[2:].strip()
				converted_lines.append("> [!NOTE]")
				converted_lines.append(f"> {bang_content}")
			else:
				converted_lines.append(line)

		return "\n".join(converted_lines)
