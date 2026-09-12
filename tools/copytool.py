"""Clipboard HTML/text/image -> Markdown collector.

Windows clipboard의 HTML Format과 이미지 데이터를 우선 사용하고,
rich clipboard를 제공하지 않는 프로그램에서는 일반 텍스트로 안전하게
fallback합니다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import sys
import threading
import time
import tkinter as tk
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import unquote
from urllib.request import Request, urlopen
import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

try:
    import win32clipboard
    import win32con
except ImportError:  # pragma: no cover - non-Windows or dependency missing
    win32clipboard = None
    win32con = None


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "result"
MAX_EXTERNAL_IMAGE_BYTES = 25 * 1024 * 1024
EXTERNAL_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()(?P<source><https?://[^>]+>|https?://[^\s)]+)(\))", re.IGNORECASE)


@dataclass
class ClipboardPayload:
    html: str = ""
    text: str = ""
    image: Image.Image | None = None


class _Node:
    def __init__(self, tag: str = "root", attrs: dict[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children: list[_Node | str] = []


class _DomParser(HTMLParser):
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in self._void_tags:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void_tags and len(self.stack) > 1:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def _extract_html_fragment(raw: bytes | str) -> str:
    """CF_HTML 헤더의 StartFragment/EndFragment 범위만 반환합니다."""
    if isinstance(raw, str):
        return raw
    header = raw[:4096].decode("ascii", errors="ignore")
    start_match = re.search(r"StartFragment:\s*(\d+)", header, re.IGNORECASE)
    end_match = re.search(r"EndFragment:\s*(\d+)", header, re.IGNORECASE)
    if start_match and end_match:
        start, end = int(start_match.group(1)), int(end_match.group(1))
        if 0 <= start < end <= len(raw):
            return raw[start:end].decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _read_clipboard() -> ClipboardPayload:
    """Windows rich clipboard를 읽고, 사용할 수 없는 형식은 건너뜁니다."""
    payload = ClipboardPayload()
    if win32clipboard is not None:
        html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(html_format):
                        payload.html = _extract_html_fragment(win32clipboard.GetClipboardData(html_format))
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        payload.text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
                break
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
                time.sleep(0.05)

    # ImageGrab은 clipboard를 닫은 뒤 호출해야 합니다.
    try:
        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, Image.Image):
            payload.image = grabbed.convert("RGBA")
    except Exception:
        pass
    return payload


class MarkdownConverter:
    """HTML DOM을 의존성 추가 없이 Markdown으로 변환합니다."""

    block_tags = {"address", "article", "aside", "div", "dl", "fieldset", "footer", "form", "header", "main", "nav", "ol", "p", "pre", "section", "table", "ul"}

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.image_dir = output_dir / "images"
        self.image_index = 0
        self.has_image = False

    def convert(self, source: str) -> str:
        parser = _DomParser()
        parser.feed(source)
        parser.close()
        result = self._render_blocks(parser.root).strip()
        return re.sub(r"\n{3,}", "\n\n", result)

    def _render_blocks(self, node: _Node) -> str:
        chunks: list[str] = []
        inline_buffer: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                inline_buffer.append(child)
                continue
            if child.tag in self.block_tags or child.tag in {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr"}:
                if inline_buffer:
                    chunks.append(self._clean_inline("".join(inline_buffer)))
                    inline_buffer.clear()
                rendered = self._render_block(child)
                if rendered:
                    chunks.append(rendered)
            else:
                inline_buffer.append(self._render_inline(child))
        if inline_buffer:
            chunks.append(self._clean_inline("".join(inline_buffer)))
        return "\n\n".join(part for part in chunks if part.strip())

    def _render_block(self, node: _Node) -> str:
        tag = node.tag
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self._clean_inline(self._render_inline_children(node))
            return f"{'#' * int(tag[1])} {text}" if text else ""
        if tag == "p":
            return self._clean_inline(self._render_inline_children(node))
        if tag == "pre":
            text = self._plain_text(node).strip("\n")
            language = node.attrs.get("data-language", "")
            return f"```{language}\n{text}\n```"
        if tag in {"ul", "ol"}:
            return self._render_list(node, ordered=tag == "ol")
        if tag == "table":
            return self._render_table(node)
        if tag == "blockquote":
            text = self._render_blocks(node).strip()
            return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
        if tag == "hr":
            return "---"
        return self._render_blocks(node)

    def _render_inline_children(self, node: _Node) -> str:
        return "".join(child if isinstance(child, str) else self._render_inline(child) for child in node.children)

    def _render_inline(self, node: _Node) -> str:
        tag = node.tag
        if tag == "br":
            return "\n"
        if tag == "img":
            src = node.attrs.get("src", "").strip()
            alt = node.attrs.get("alt", "image").strip() or "image"
            if src.startswith("data:image/"):
                src = self._save_data_image(src)
            if not src:
                return ""
            self.has_image = True
            return f"![{self._escape_brackets(alt)}]({src})"
        content = self._render_inline_children(node)
        if tag in {"strong", "b"}:
            return f"**{content.strip()}**"
        if tag in {"em", "i"}:
            return f"*{content.strip()}*"
        if tag == "del" or tag == "s":
            return f"~~{content.strip()}~~"
        if tag == "code":
            return f"`{content.strip()}`"
        if tag == "a":
            href = node.attrs.get("href", "").strip()
            return f"[{content.strip()}]({href})" if href else content
        return content

    def _render_list(self, node: _Node, ordered: bool) -> str:
        lines: list[str] = []
        number = 1
        for child in node.children:
            if not isinstance(child, _Node) or child.tag != "li":
                continue
            content = self._clean_inline(self._render_inline_children(child)).strip()
            prefix = f"{number}. " if ordered else "- "
            lines.append(prefix + content)
            number += 1
        return "\n".join(lines)

    def _render_table(self, node: _Node) -> str:
        rows: list[list[str]] = []

        def find_rows(current: _Node) -> None:
            if current.tag == "tr":
                cells = [child for child in current.children if isinstance(child, _Node) and child.tag in {"td", "th"}]
                if cells:
                    rows.append([self._table_cell(self._render_inline_children(cell)) for cell in cells])
                return
            for child in current.children:
                if isinstance(child, _Node):
                    find_rows(child)

        find_rows(node)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)

    @staticmethod
    def _table_cell(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().replace("|", "\\|")

    @staticmethod
    def _plain_text(node: _Node) -> str:
        return "".join(child if isinstance(child, str) else MarkdownConverter._plain_text(child) for child in node.children)

    @staticmethod
    def _clean_inline(value: str) -> str:
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        return re.sub(r" *\n *", "\n", value).strip()

    @staticmethod
    def _escape_brackets(value: str) -> str:
        return value.replace("[", "\\[").replace("]", "\\]")

    def _save_data_image(self, source: str) -> str:
        try:
            header, encoded = source.split(",", 1)
            extension = header.split("/", 1)[1].split(";", 1)[0].lower()
            extension = "jpg" if extension == "jpeg" else extension
            if extension not in {"png", "jpg", "gif", "webp", "bmp"}:
                extension = "png"
            image_bytes = base64.b64decode(encoded, validate=True)
            return self._save_bytes(image_bytes, extension)
        except (ValueError, binascii.Error):
            return ""

    def save_clipboard_image(self, image: Image.Image) -> str:
        self.image_index += 1
        self.image_dir.mkdir(parents=True, exist_ok=True)
        filename = f"clipboard_{self.image_index:03d}.png"
        image.save(self.image_dir / filename, format="PNG")
        return f"images/{filename}"

    def _save_bytes(self, image_bytes: bytes, extension: str) -> str:
        self.image_index += 1
        self.image_dir.mkdir(parents=True, exist_ok=True)
        filename = f"image_{self.image_index:03d}.{extension}"
        (self.image_dir / filename).write_bytes(image_bytes)
        return f"images/{filename}"


def _payload_to_markdown(payload: ClipboardPayload, output_dir: Path) -> str:
    converter = MarkdownConverter(output_dir)
    if payload.html.strip():
        markdown = converter.convert(payload.html)
    else:
        markdown = payload.text.strip()
    if payload.image is not None and not converter.has_image:
        image_path = converter.save_clipboard_image(payload.image)
        markdown = f"{markdown}\n\n![clipboard image]({image_path})".strip()
    return markdown.strip()


def _external_image_urls(markdown: str) -> list[str]:
    """Markdown 이미지 구문에서 HTTP(S) 주소만 중복 없이 추출합니다."""
    urls: list[str] = []
    for match in EXTERNAL_IMAGE_RE.finditer(markdown):
        source = match.group("source")
        source = source[1:-1] if source.startswith("<") and source.endswith(">") else source
        if source not in urls:
            urls.append(source)
    return urls


def _download_external_image(source: str, image_dir: Path) -> str:
    """외부 이미지를 검증한 뒤 PNG로 저장하고 Markdown 상대 경로를 반환합니다."""
    filename = f"external_{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}.png"
    destination = image_dir / filename
    if destination.exists():
        return f"images/{filename}"

    request = Request(source, headers={"User-Agent": "AssetCommon-CopyTool/1.0"})
    with urlopen(request, timeout=15) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_EXTERNAL_IMAGE_BYTES:
            raise ValueError("이미지 크기가 25MB 제한을 초과했습니다.")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_EXTERNAL_IMAGE_BYTES:
                raise ValueError("이미지 크기가 25MB 제한을 초과했습니다.")
            chunks.append(chunk)

    # 확장자와 Content-Type을 신뢰하지 않고 실제 이미지인지 확인합니다.
    with Image.open(BytesIO(b"".join(chunks))) as loaded:
        loaded.load()
        image = loaded.convert("RGBA")
    image_dir.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")
    return f"images/{filename}"


def _replace_external_image_links(markdown: str, replacements: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        source = match.group("source")
        unwrapped = source[1:-1] if source.startswith("<") and source.endswith(">") else source
        local_path = replacements.get(unwrapped)
        if not local_path:
            return match.group(0)
        return f"{match.group(1)}{local_path}{match.group(3)}"

    return EXTERNAL_IMAGE_RE.sub(replace, markdown)


class CopyToolApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("참고자료 정리")
        self.geometry("900x700")
        self.minsize(700, 500)
        self.output_dir = DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.payload = ClipboardPayload()
        self._preview_after_id: str | None = None
        self._preview_image_refs: list[ImageTk.PhotoImage] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="참고자료 정리", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, padx=24, pady=(18, 2), sticky="w")
        ctk.CTkLabel(header, text="웹에서 복사한 텍스트·이미지·표를 Markdown 문서로 저장합니다.", text_color="gray60").grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, padx=18, pady=(14, 8), sticky="ew")
        toolbar.grid_columnconfigure(4, weight=1)
        ctk.CTkButton(toolbar, text="클립보드 붙여넣기", command=self.paste_clipboard).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(toolbar, text="내용 지우기", fg_color="gray40", hover_color="gray30", command=self.clear_content).grid(row=0, column=1, padx=(0, 12))
        self.external_image_button = ctk.CTkButton(toolbar, text="외부 이미지 로컬 변환", width=150, command=self.convert_external_images)
        self.external_image_button.grid(row=0, column=2, padx=(0, 16))
        self.status_label = ctk.CTkLabel(toolbar, text="Ctrl+V 또는 버튼으로 붙여넣으세요.", anchor="w", text_color="gray60")
        self.status_label.grid(row=0, column=3, columnspan=2, sticky="ew")

        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.grid(row=2, column=0, padx=18, pady=8, sticky="nsew")
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)
        self.paned_window = tk.PanedWindow(
            content_frame,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief="raised",
            showhandle=True,
            opaqueresize=True,
            bd=0,
            relief="flat",
            bg="#c4c7cc",
        )
        self.paned_window.grid(row=0, column=0, sticky="nsew")

        editor_pane = ctk.CTkFrame(self.paned_window)
        editor_pane.grid_rowconfigure(1, weight=1)
        editor_pane.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(editor_pane, text="Markdown 편집", anchor="w", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=8, pady=(6, 6), sticky="w")
        editor_panel = ctk.CTkFrame(editor_pane)
        editor_panel.grid(row=1, column=0, padx=4, pady=(0, 4), sticky="nsew")
        editor_panel.grid_rowconfigure(0, weight=1)
        editor_panel.grid_columnconfigure(0, weight=1)
        self.editor = ctk.CTkTextbox(editor_panel, wrap="word", font=ctk.CTkFont(size=14))
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.bind("<Control-v>", self._on_ctrl_v)
        self.editor.bind("<Control-V>", self._on_ctrl_v)
        self.editor.bind("<KeyRelease>", self._on_editor_change)

        preview_pane = ctk.CTkFrame(self.paned_window)
        preview_pane.grid_rowconfigure(1, weight=1)
        preview_pane.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(preview_pane, text="md 미리보기", anchor="w", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=8, pady=(6, 6), sticky="w")
        preview_panel = ctk.CTkFrame(preview_pane)
        preview_panel.grid(row=1, column=0, padx=4, pady=(0, 4), sticky="nsew")
        preview_panel.grid_rowconfigure(0, weight=1)
        preview_panel.grid_columnconfigure(0, weight=1)
        self.preview = tk.Text(
            preview_panel,
            wrap="word",
            state="disabled",
            padx=14,
            pady=14,
            relief="flat",
            borderwidth=0,
            background="#ffffff",
            foreground="#202124",
            font=("Segoe UI", 11),
        )
        self.preview.grid(row=0, column=0, sticky="nsew")
        preview_scrollbar = ctk.CTkScrollbar(preview_panel, command=self.preview.yview)
        preview_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)
        self.preview.configure(yscrollcommand=preview_scrollbar.set)
        self._configure_preview_tags()
        self.paned_window.add(editor_pane, minsize=260, stretch="always")
        self.paned_window.add(preview_pane, minsize=220, stretch="always")
        self.after_idle(lambda: self.paned_window.sash_place(0, 500, 1))

        bottom = ctk.CTkFrame(self)
        bottom.grid(row=3, column=0, padx=18, pady=(8, 18), sticky="ew")
        bottom.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bottom, text="저장 폴더").grid(row=0, column=0, padx=(12, 8), pady=10)
        self.folder_var = ctk.StringVar(value=str(self.output_dir))
        ctk.CTkEntry(bottom, textvariable=self.folder_var).grid(row=0, column=1, padx=4, pady=10, sticky="ew")
        ctk.CTkButton(bottom, text="폴더 선택", width=100, command=self.choose_folder).grid(row=0, column=2, padx=4, pady=10)
        ctk.CTkLabel(bottom, text="파일명").grid(row=1, column=0, padx=(12, 8), pady=(0, 10))
        self.filename_var = ctk.StringVar(value=f"reference_{datetime.now():%Y%m%d_%H%M%S}.md")
        ctk.CTkEntry(bottom, textvariable=self.filename_var).grid(row=1, column=1, padx=4, pady=(0, 10), sticky="ew")
        ctk.CTkButton(bottom, text="md로 저장", width=140, command=self.save_markdown).grid(row=1, column=2, padx=4, pady=(0, 10))

    def _on_ctrl_v(self, _event=None):
        self.paste_clipboard()
        return "break"

    def _on_editor_change(self, _event=None):
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(150, self._update_preview_from_editor)

    def _configure_preview_tags(self) -> None:
        self.preview.tag_configure("body", font=("Segoe UI", 11))
        self.preview.tag_configure("heading1", font=("Segoe UI", 20, "bold"), spacing3=8)
        self.preview.tag_configure("heading2", font=("Segoe UI", 17, "bold"), spacing3=6)
        self.preview.tag_configure("heading3", font=("Segoe UI", 14, "bold"), spacing3=4)
        self.preview.tag_configure("heading", font=("Segoe UI", 12, "bold"))
        self.preview.tag_configure("bold", font=("Segoe UI", 11, "bold"))
        self.preview.tag_configure("italic", font=("Segoe UI", 11, "italic"))
        self.preview.tag_configure("code", font=("Consolas", 10), background="#f1f3f4")
        self.preview.tag_configure("quote", foreground="#5f6368", lmargin1=14, lmargin2=14)
        self.preview.tag_configure("table", font=("Consolas", 10))

    def _update_preview_from_editor(self) -> None:
        self._preview_after_id = None
        self._render_markdown_preview(self.editor.get("1.0", "end").strip())

    def _render_markdown_preview(self, markdown: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self._preview_image_refs.clear()
        in_code = False
        for line in markdown.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.preview.insert("end", line + "\n", "code")
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                level = min(len(heading.group(1)), 3)
                self._insert_inline(heading.group(2), f"heading{level}")
                self.preview.insert("end", "\n\n")
                continue
            if not line.strip():
                self.preview.insert("end", "\n")
                continue
            if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", line):
                continue
            if line.lstrip().startswith(">"):
                self._insert_inline(line.lstrip()[1:].lstrip(), "quote")
            elif re.match(r"^\s*(?:[-*+]\s|\d+[.)]\s)", line):
                self._insert_inline(line, "body")
            elif line.lstrip().startswith("|"):
                self._insert_inline(line, "table")
            elif line.strip() == "---":
                self.preview.insert("end", "────────────────────────\n", "heading")
            else:
                self._insert_inline(line, "body")
            self.preview.insert("end", "\n")
        self.preview.configure(state="disabled")

    def _insert_inline(self, text: str, default_tag: str = "body") -> None:
        pattern = re.compile(r"(!\[[^\]]*\]\([^)]*\)|\*\*.*?\*\*|`.*?`|\[[^\]]+\]\([^)]*\)|\*[^*]+\*)")
        position = 0
        for match in pattern.finditer(text):
            if match.start() > position:
                self.preview.insert("end", text[position:match.start()], default_tag)
            token = match.group(0)
            image_match = re.match(r"!\[([^]]*)\]\(([^)]*)\)", token)
            if image_match:
                self._insert_preview_image(image_match.group(1), image_match.group(2))
            elif token.startswith("**"):
                self.preview.insert("end", token[2:-2], "bold")
            elif token.startswith("`"):
                self.preview.insert("end", token[1:-1], "code")
            elif token.startswith("["):
                label = token[1:].split("]", 1)[0]
                self.preview.insert("end", label, default_tag)
            else:
                self.preview.insert("end", token.strip("*"), "italic")
            position = match.end()
        if position < len(text):
            self.preview.insert("end", text[position:], default_tag)

    def _insert_preview_image(self, alt: str, source: str) -> None:
        if source.startswith(("http://", "https://", "data:")):
            self.preview.insert("end", f"[이미지: {alt or 'image'}]", "body")
            return
        image_path = Path(unquote(source))
        if not image_path.is_absolute():
            image_path = self.output_dir / image_path
        try:
            with Image.open(image_path) as loaded:
                image = loaded.convert("RGBA")
            max_width = max(220, self.preview.winfo_width() - 40)
            if image.width > max_width:
                ratio = max_width / image.width
                image = image.resize((max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self._preview_image_refs.append(photo)
            self.preview.image_create("end", image=photo)
            self.preview.insert("end", "\n")
        except (OSError, ValueError):
            self.preview.insert("end", f"[이미지: {alt or 'image'}]", "body")

    def convert_external_images(self) -> None:
        markdown = self.editor.get("1.0", "end").strip()
        sources = _external_image_urls(markdown)
        if not sources:
            self.status_label.configure(text="변환할 외부 이미지가 없습니다.", text_color="gray60")
            return

        output_dir = self.output_dir
        image_dir = output_dir / "images"
        self.external_image_button.configure(state="disabled")
        self.status_label.configure(text=f"외부 이미지 {len(sources)}개를 다운로드하는 중...", text_color="#2563eb")
        worker = threading.Thread(
            target=self._convert_external_images_worker,
            args=(markdown, sources, image_dir),
            daemon=True,
        )
        worker.start()

    def _convert_external_images_worker(self, markdown: str, sources: list[str], image_dir: Path) -> None:
        replacements: dict[str, str] = {}
        errors: list[str] = []
        for source in sources:
            try:
                replacements[source] = _download_external_image(source, image_dir)
            except Exception as error:  # 네트워크별 오류를 UI에 모아서 표시합니다.
                errors.append(f"{source}: {error}")
        self.after(0, self._finish_external_image_conversion, markdown, replacements, errors)

    def _finish_external_image_conversion(self, markdown: str, replacements: dict[str, str], errors: list[str]) -> None:
        try:
            if replacements:
                converted = _replace_external_image_links(markdown, replacements)
                # 이후 폴더 변경/옵션 변경 시 원본 HTML로 되돌아가지 않도록
                # 현재 Markdown을 새 입력으로 보관합니다.
                self.payload = ClipboardPayload(text=converted)
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", converted)
                self._render_markdown_preview(converted)
            if errors:
                self.status_label.configure(text=f"{len(replacements)}개 변환 완료, {len(errors)}개 실패", text_color="#d97706")
                messagebox.showwarning("일부 이미지 변환 실패", "\n".join(errors[:5]))
            else:
                self.status_label.configure(text=f"외부 이미지 {len(replacements)}개를 로컬 images 폴더로 변환했습니다.", text_color="#16a34a")
        finally:
            self.external_image_button.configure(state="normal")

    def paste_clipboard(self) -> None:
        payload = _read_clipboard()
        if not payload.html and not payload.text and payload.image is None:
            self.status_label.configure(text="클립보드에 붙여넣을 내용이 없습니다.", text_color="#d97706")
            return
        self.payload = payload
        self._refresh_preview()
        kinds = ", ".join(filter(None, ["HTML" if payload.html else "텍스트", "이미지" if payload.image else ""]))
        self.status_label.configure(text=f"{kinds} 내용을 변환했습니다.", text_color="#16a34a")

    def _refresh_preview(self) -> None:
        markdown = _payload_to_markdown(self.payload, self.output_dir)
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", markdown)
        self._render_markdown_preview(markdown)

    def clear_content(self) -> None:
        self.payload = ClipboardPayload()
        self.editor.delete("1.0", "end")
        self._render_markdown_preview("")
        self.status_label.configure(text="내용을 지웠습니다.", text_color="gray60")

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.output_dir), title="Markdown 저장 폴더 선택")
        if selected:
            self.output_dir = Path(selected)
            self.folder_var.set(str(self.output_dir))
            if self.payload.html or self.payload.text or self.payload.image is not None:
                self._refresh_preview()

    def save_markdown(self) -> None:
        content = self.editor.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("저장할 내용 없음", "먼저 클립보드 내용을 붙여넣으세요.")
            return
        filename = self.filename_var.get().strip()
        if not filename:
            filename = f"reference_{datetime.now():%Y%m%d_%H%M%S}.md"
        if not filename.lower().endswith(".md"):
            filename += ".md"
        # 경로 조작을 방지하고 선택한 폴더 바로 아래에만 저장합니다.
        filename = Path(filename).name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        destination = self.output_dir / filename
        destination.write_text(content + "\n", encoding="utf-8")
        next_filename = f"reference_{datetime.now():%Y%m%d_%H%M%S_%f}.md"
        self.filename_var.set(next_filename)
        self.status_label.configure(text=f"저장 완료: {destination}  |  다음 파일명: {next_filename}", text_color="#16a34a")
        messagebox.showinfo("저장 완료", f"Markdown 파일을 저장했습니다.\n{destination}\n\n다음 파일명으로 갱신했습니다.\n{next_filename}")


def main() -> None:
    if sys.platform != "win32":
        print("경고: Windows 외 환경에서는 HTML/이미지 클립보드 지원이 제한될 수 있습니다.")
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = CopyToolApp()
    app.mainloop()


if __name__ == "__main__":
    main()
