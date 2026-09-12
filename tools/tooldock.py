"""가벼운 Python 도구 실행기.

tools 폴더의 Python 도구를 등록해 빠르게 실행하고, 등록 정보는
tool_registry.json에 저장합니다.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
TOOLS_DIR = APP_DIR
PROJECT_DIR = TOOLS_DIR.parent
REGISTRY_PATH = TOOLS_DIR / "tool_registry.json"
ICON_DIR = TOOLS_DIR / "icons"
ICON_EXTENSIONS = {".png", ".jpg", ".jpeg", ".ico"}
DEFAULT_TOOL = {
    "name": "copytool",
    "script": "copytool.py",
    "description": "클립보드 내용을 Markdown으로 정리합니다.",
}


@dataclass
class RegisteredTool:
    name: str
    script: str
    description: str = ""
    icon: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RegisteredTool":
        return cls(
            name=str(data.get("name", "이름 없는 툴")),
            script=str(data.get("script", "")),
            description=str(data.get("description", "")),
            icon=str(data.get("icon", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "script": self.script, "description": self.description, "icon": self.icon}


def _load_tools() -> list[RegisteredTool]:
    if not REGISTRY_PATH.exists():
        return [RegisteredTool.from_dict(DEFAULT_TOOL)]
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        tools = [RegisteredTool.from_dict(item) for item in data.get("tools", []) if isinstance(item, dict)]
        return tools
    except (OSError, json.JSONDecodeError, AttributeError):
        return [RegisteredTool.from_dict(DEFAULT_TOOL)]


def _save_tools(tools: list[RegisteredTool]) -> None:
    REGISTRY_PATH.write_text(
        json.dumps({"tools": [tool.to_dict() for tool in tools]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_script(script: str) -> Path:
    path = Path(script)
    return path if path.is_absolute() else TOOLS_DIR / path


def _stored_script(path: Path) -> str:
    try:
        return path.resolve().relative_to(TOOLS_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def _python_launcher() -> str | None:
    """소스 실행과 EXE 실행 모두에서 등록된 .py를 실행할 Python을 찾습니다."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    candidates = [
        Path(sys.executable).with_name("pythonw.exe"),
        Path(sys.executable).with_name("python.exe"),
        Path(sys.prefix) / "pythonw.exe",
        Path(sys.prefix) / "python.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for command in ("pythonw.exe", "pyw.exe", "python.exe", "py.exe"):
        found = shutil.which(command)
        if found:
            return found
    return None


def _resolve_icon(icon: str) -> Path | None:
    if not icon:
        return None
    path = Path(icon)
    path = path if path.is_absolute() else TOOLS_DIR / path
    return path if path.is_file() else None


def _copy_icon(source: Path, tool_name: str) -> str:
    """선택한 아이콘을 프로젝트 내부 icons 폴더에 복사해 상대 경로를 반환합니다."""
    if source.suffix.lower() not in ICON_EXTENSIONS:
        raise ValueError("지원되는 아이콘 형식은 PNG, JPG, JPEG, ICO입니다.")
    with Image.open(source) as image:
        image.verify()
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", tool_name).strip("_") or "tool"
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    destination = ICON_DIR / f"{safe_name}_{digest}{source.suffix.lower()}"
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination.relative_to(TOOLS_DIR).as_posix()


class ToolInfoDialog(ctk.CTkToplevel):
    """툴 이름·설명·아이콘을 한 화면에서 입력받는 모달 창입니다."""

    def __init__(
        self,
        parent: ctk.CTk,
        initial_name: str,
        initial_description: str = "",
        initial_icon: Path | None = None,
        edit_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.result: tuple[str, str, Path | None] | None = None
        self.icon_path = initial_icon
        self.title("툴 설정" if edit_mode else "툴 등록 정보")
        self.geometry("480x310")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="툴 설정" if edit_mode else "툴 등록", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 14), sticky="w")
        ctk.CTkLabel(self, text="툴 이름").grid(row=1, column=0, padx=(20, 8), pady=6, sticky="w")
        self.name_entry = ctk.CTkEntry(self)
        self.name_entry.grid(row=1, column=1, padx=(0, 20), pady=6, sticky="ew")
        self.name_entry.insert(0, initial_name)
        ctk.CTkLabel(self, text="설명").grid(row=2, column=0, padx=(20, 8), pady=6, sticky="w")
        self.description_entry = ctk.CTkEntry(self, placeholder_text="간단한 툴 설명(선택)")
        self.description_entry.grid(row=2, column=1, padx=(0, 20), pady=6, sticky="ew")
        self.description_entry.insert(0, initial_description)
        ctk.CTkLabel(self, text="아이콘").grid(row=3, column=0, padx=(20, 8), pady=6, sticky="w")
        icon_frame = ctk.CTkFrame(self, fg_color="transparent")
        icon_frame.grid(row=3, column=1, padx=(0, 20), pady=6, sticky="ew")
        icon_frame.grid_columnconfigure(0, weight=1)
        self.icon_var = ctk.StringVar(value=initial_icon.name if initial_icon is not None else "기본 아이콘 사용")
        ctk.CTkLabel(icon_frame, textvariable=self.icon_var, anchor="w", text_color="gray60").grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(icon_frame, text="아이콘 선택", width=100, command=self.select_icon).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(icon_frame, text="기본값", width=70, fg_color="gray40", hover_color="gray30", command=self.clear_icon).grid(row=0, column=2, padx=(6, 0))

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=4, column=0, columnspan=2, padx=20, pady=(16, 18), sticky="e")
        ctk.CTkButton(button_frame, text="취소", width=80, fg_color="gray40", hover_color="gray30", command=self.cancel).pack(side="left", padx=(0, 8))
        ctk.CTkButton(button_frame, text="저장" if edit_mode else "등록", width=80, command=self.confirm).pack(side="left")
        self.name_entry.bind("<Return>", lambda _event: self.confirm())
        self.description_entry.bind("<Return>", lambda _event: self.confirm())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(50, self.name_entry.focus_set)

    def select_icon(self) -> None:
        path_string = filedialog.askopenfilename(
            parent=self,
            title="툴 아이콘 선택",
            initialdir=str(ICON_DIR if ICON_DIR.exists() else TOOLS_DIR),
            filetypes=[("아이콘 이미지", "*.png *.jpg *.jpeg *.ico"), ("모든 파일", "*.*")],
        )
        if path_string:
            self.icon_path = Path(path_string).resolve()
            self.icon_var.set(self.icon_path.name)

    def clear_icon(self) -> None:
        self.icon_path = None
        self.icon_var.set("기본 아이콘 사용")

    def confirm(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("툴 이름", "툴 이름을 입력하세요.", parent=self)
            return
        self.result = (name, self.description_entry.get().strip(), self.icon_path)
        self.grab_release()
        self.destroy()

    def cancel(self) -> None:
        self.grab_release()
        self.destroy()


def _ask_tool_info(
    parent: ctk.CTk,
    initial_name: str,
    initial_description: str = "",
    initial_icon: Path | None = None,
    edit_mode: bool = False,
) -> tuple[str, str, Path | None] | None:
    dialog = ToolInfoDialog(parent, initial_name, initial_description, initial_icon, edit_mode)
    parent.wait_window(dialog)
    return dialog.result


class ToolDock(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Tool Dock")
        self.geometry("380x420")
        self.minsize(340, 320)
        self.tools = _load_tools()
        self.selected_index: int | None = None
        self.running_processes: list[subprocess.Popen[bytes]] = []
        self._icon_refs: list[ctk.CTkImage] = []
        self._tile_refs: list[ctk.CTkButton] = []
        self._build_ui()
        self._render_tools()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        tool_header = ctk.CTkFrame(self, fg_color="transparent")
        tool_header.grid(row=1, column=0, padx=14, pady=(10, 6), sticky="ew")
        tool_header.grid_columnconfigure(4, weight=1)
        button_style = {"width": 28, "height": 28, "fg_color": "#2563eb", "hover_color": "#1d4ed8"}
        ctk.CTkButton(tool_header, text="+", command=self.add_tool, **button_style).grid(row=0, column=0, padx=2)
        ctk.CTkButton(tool_header, text="−", command=self.delete_tool, **button_style).grid(row=0, column=1, padx=2)
        ctk.CTkButton(tool_header, text="►", command=self.run_selected_tool, **button_style).grid(row=0, column=2, padx=(2, 8))
        ctk.CTkButton(tool_header, text="⚙", command=self.edit_selected_tool, **button_style).grid(row=0, column=3, padx=(0, 8))
        self.status_label = ctk.CTkLabel(tool_header, text="툴을 선택한 후 실행하세요.", anchor="w", text_color="gray60")
        self.status_label.grid(row=0, column=4, padx=(4, 0), sticky="ew")

        self.tool_list = ctk.CTkScrollableFrame(self, orientation="vertical")
        self.tool_list.grid(row=2, column=0, padx=14, pady=6, sticky="nsew")

    def _render_tools(self) -> None:
        for child in self.tool_list.winfo_children():
            child.destroy()
        self._icon_refs.clear()
        self._tile_refs.clear()
        if self.selected_index is not None and self.selected_index >= len(self.tools):
            self.selected_index = None
        columns = 4
        for column in range(columns):
            self.tool_list.grid_columnconfigure(column, weight=1)
        if not self.tools:
            ctk.CTkLabel(self.tool_list, text="등록된 툴이 없습니다.", text_color="gray60").grid(row=0, column=0, columnspan=columns, pady=32)
            return
        for index, tool in enumerate(self.tools):
            selected = index == self.selected_index
            icon_image = None
            icon_path = _resolve_icon(tool.icon)
            if icon_path is not None:
                try:
                    with Image.open(icon_path) as loaded:
                        icon_source = loaded.convert("RGBA")
                    icon_image = ctk.CTkImage(light_image=icon_source, dark_image=icon_source, size=(32, 32))
                    self._icon_refs.append(icon_image)
                except (OSError, ValueError):
                    icon_image = None
            display_name = tool.name if len(tool.name) <= 9 else f"{tool.name[:8]}…"
            tile = ctk.CTkButton(
                self.tool_list,
                text=display_name if icon_image is not None else f"▣\n{display_name}",
                image=icon_image,
                compound="top",
                width=72,
                height=72,
                corner_radius=8,
                border_width=2 if selected else 0,
                border_color="#60a5fa",
                fg_color="#2563eb" if selected else ("#3b3f46", "#e5e7eb"),
                text_color="#ffffff" if selected else ("#ffffff", "#202124"),
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda i=index: self.select_tool(i),
            )
            tile.grid(row=index // columns, column=index % columns, padx=5, pady=5)
            tile.bind("<Double-Button-1>", lambda _event, i=index: self._run_double_click(i), add="+")
            self._tile_refs.append(tile)

    def select_tool(self, index: int) -> None:
        self.selected_index = index
        self._update_tile_styles()
        self.status_label.configure(text=f"선택됨: {self.tools[index].name}", text_color="gray60")

    def _update_tile_styles(self) -> None:
        for index, tile in enumerate(self._tile_refs):
            selected = index == self.selected_index
            tile.configure(
                border_width=2 if selected else 0,
                fg_color="#2563eb" if selected else ("#3b3f46", "#e5e7eb"),
                text_color="#ffffff" if selected else ("#ffffff", "#202124"),
            )

    def _run_double_click(self, index: int):
        self.select_tool(index)
        self.run_tool(index)
        return "break"

    def add_tool(self) -> None:
        path_string = filedialog.askopenfilename(
            title="등록할 Python 툴 선택",
            initialdir=str(TOOLS_DIR),
            filetypes=[("Python/실행 파일", "*.py *.exe"), ("모든 파일", "*.*")],
        )
        if not path_string:
            return
        path = Path(path_string).resolve()
        if path.suffix.lower() not in {".py", ".exe"}:
            messagebox.showwarning("등록할 수 없음", "Python 파일(.py) 또는 실행 파일(.exe)만 등록할 수 있습니다.")
            return
        if any(_resolve_script(tool.script).resolve() == path for tool in self.tools):
            messagebox.showinfo("이미 등록됨", "이미 등록된 Python 툴입니다.")
            return
        metadata = _ask_tool_info(self, path.stem)
        if metadata is None:
            return
        name, description, icon_source = metadata
        icon = ""
        if icon_source is not None:
            try:
                icon = _copy_icon(icon_source, name)
            except (OSError, ValueError) as error:
                messagebox.showerror("아이콘 등록 실패", str(error))
                return
        self.tools.append(RegisteredTool(name=name, script=_stored_script(path), description=description.strip(), icon=icon))
        _save_tools(self.tools)
        self.selected_index = len(self.tools) - 1
        self._render_tools()
        self.status_label.configure(text=f"등록 완료: {name}", text_color="#16a34a")

    def delete_tool(self) -> None:
        if self.selected_index is None:
            messagebox.showinfo("툴 삭제", "먼저 삭제할 툴을 선택하세요.")
            return
        tool = self.tools[self.selected_index]
        if not messagebox.askyesno("툴 삭제", f"'{tool.name}' 등록을 삭제할까요?\n(실제 Python 파일은 삭제하지 않습니다.)"):
            return
        self.tools.pop(self.selected_index)
        self.selected_index = None
        _save_tools(self.tools)
        self._render_tools()
        self.status_label.configure(text=f"등록 삭제 완료: {tool.name}", text_color="gray60")

    def run_selected_tool(self) -> None:
        if self.selected_index is None:
            messagebox.showinfo("툴 실행", "먼저 실행할 툴을 선택하세요.")
            return
        self.run_tool(self.selected_index)

    def edit_selected_tool(self) -> None:
        if self.selected_index is None:
            messagebox.showinfo("툴 설정", "먼저 설정할 툴을 선택하세요.")
            return
        index = self.selected_index
        tool = self.tools[index]
        metadata = _ask_tool_info(
            self,
            tool.name,
            initial_description=tool.description,
            initial_icon=_resolve_icon(tool.icon),
            edit_mode=True,
        )
        if metadata is None:
            return
        name, description, icon_source = metadata
        icon = ""
        if icon_source is not None:
            try:
                icon = _copy_icon(icon_source, name)
            except (OSError, ValueError) as error:
                messagebox.showerror("아이콘 설정 실패", str(error))
                return
        self.tools[index] = RegisteredTool(name=name, script=tool.script, description=description, icon=icon)
        _save_tools(self.tools)
        self._render_tools()
        self.status_label.configure(text=f"설정 저장 완료: {name}", text_color="#16a34a")

    def run_tool(self, index: int) -> None:
        tool = self.tools[index]
        script = _resolve_script(tool.script).resolve()
        if not script.is_file() or script.suffix.lower() not in {".py", ".exe"}:
            messagebox.showerror("실행할 수 없음", f"등록된 실행 파일을 찾을 수 없습니다.\n{script}")
            return
        self.selected_index = index
        self._update_tile_styles()
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        if script.suffix.lower() == ".exe":
            command = [str(script)]
        else:
            launcher = _python_launcher()
            if launcher is None:
                messagebox.showerror("Python을 찾을 수 없음", "등록된 Python 툴을 실행할 Python 인터프리터를 찾을 수 없습니다.")
                return
            command = [launcher, str(script)]
        try:
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_DIR),
                creationflags=creation_flags,
            )
            self.running_processes.append(process)
            self.running_processes = [item for item in self.running_processes if item.poll() is None]
            self.status_label.configure(text=f"실행 중: {tool.name} (PID {process.pid})", text_color="#16a34a")
        except OSError as error:
            messagebox.showerror("툴 실행 실패", str(error))


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = ToolDock()
    app.mainloop()


if __name__ == "__main__":
    main()
