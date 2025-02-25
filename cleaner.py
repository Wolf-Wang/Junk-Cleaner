#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, platform, subprocess, shutil, threading, queue, re, argparse
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm

APP_TITLE = "🧹  Junk Cleaner V250225"
OS = platform.system()
DEFAULT_SCAN_PATH = {"Darwin": Path("/Users"), "Windows": Path("C:/")}.get(OS, Path("/home"))
JUNK_FILES = {
    "names": (".DS_Store", "desktop.ini", "Thumbs.db", ".bash_history", ".zsh_history", "fish_history",
        ".viminfo", ".localized", ".sharkgi", ".lesshst", ".python_history", re.compile(r"\.zcompdump-.*")),
    "extensions": (".log", ".tmp", "temp", ".cache"),
    "folders": ("$RECYCLE.BIN", "Logs", "CrashReporter", "tmp", "temp", "log", "logs",
        ".Trash", ".fseventsd", ".Spotlight-V100", ".zsh_sessions", "System Volume Information",
        "Photo Booth Library", "Automatically Add to Music.localized",
        "Media.localized", "Videos Library.tvlibrary", "网易云音乐", re.compile(r"Cache", re.IGNORECASE))
}

class Core:
    """核心功能类，处理文件扫描和清理的逻辑"""
    def __init__(self) -> None:
        self.abort_event = threading.Event()
        self.queue = queue.Queue()
        self.thread = None

    def scan(self, scan_path: Path) -> None:
        """扫描指定路径的垃圾文件"""

        # 重置中断事件, 队列, 和线程
        self.abort_event.clear()
        self.queue = queue.Queue()
        self.thread = None

        # 创建并启动扫描线程
        self.thread = threading.Thread(target=self.scanner, args=(scan_path,))
        self.thread.start()

    def scanner(self, scan_path: Path) -> None:
        """扫描线程的工作函数"""

        def matches_patterns(filename: str, patterns: list) -> bool:
            """内部函数: 检查文件名是否匹配任何模式，不区分大小写"""
            filename = filename.lower()  # 转换为小写进行比较
            return any(
                (pattern.lower() == filename if isinstance(pattern, str)
                else bool(pattern.search(filename)))
                for pattern in patterns
                if pattern)

        total_size = 0
        file_count = 0
        processed_paths = set()  # 用于记录已处理的路径

        for root_path in scan_path.rglob("*"):
            # 在循环开始就检查是否需要中断
            if self.abort_event.is_set():
                return  # 直接返回，不发送 scan_done 消息

            try:
                # 如果当前路径的任何父目录已被处理，则跳过
                if any(str(parent) in processed_paths
                      for parent in root_path.parents):
                    continue

                # 检查垃圾文件夹
                if root_path.is_dir():
                    if matches_patterns(root_path.name, JUNK_FILES["folders"]):
                        size = sum(f.stat().st_size for f in root_path.rglob('*') if f.is_file())
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.queue.put(("found_item", (root_path, "Folder", size, modified)))
                        total_size += size
                        file_count += 1
                        processed_paths.add(str(root_path))  # 记录已处理的目录路径

                # 检查垃圾文件
                elif root_path.is_file():
                    # 同时检查文件名和扩展名(都转换为小写进行比较)
                    if (matches_patterns(root_path.name, JUNK_FILES["names"]) or
                    root_path.suffix.lower() in [ext.lower() for ext in JUNK_FILES["extensions"]]):
                        size = root_path.stat().st_size
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.queue.put(("found_item", (root_path, "File", size, modified)))
                        total_size += size
                        file_count += 1

            except (OSError, PermissionError):
                continue

        # 只有在没有中断的情况下才发送 scan_done 消息
        if not self.abort_event.is_set():
            self.queue.put(("scan_done", (total_size, file_count)))

    def clean(self, items: list[Path]) -> None:
        """清理选定的垃圾文件"""

        # 重置中断事件, 队列, 和线程
        self.abort_event.clear()
        self.queue = queue.Queue()
        self.thread = None

        # 创建并启动扫描线程
        self.thread = threading.Thread(target=self.cleaner, args=(items,))
        self.thread.start()

    def cleaner(self, items: list[Path] = None) -> None:
        """清理垃圾文件"""

        # 计算每个文件清理操作需要的延时
        target_duration = 1.5  # 目标总清理时间（秒）
        item_count = len(items)
        delay = target_duration / item_count if item_count > 0 else 0

        for path in items:
            if self.abort_event.is_set():  # 检查是否中断清理
                break
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                        time.sleep(delay)
                    else:
                        shutil.rmtree(path, ignore_errors=True)
                        time.sleep(delay)
            except (OSError, PermissionError) as e:
                # 发送清理失败消息
                self.queue.put(("clean_error", (path, str(e))))

        # 发送清理完成消息
        self.queue.put(("clean_done", None))

    @staticmethod
    def format_size(size: int) -> str:
        """格式化文件大小"""

        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024: break
            size /= 1024
        return f"{size:.1f} {unit}"

class GUI:
    """GUI界面类"""
    def __init__(self) -> None:
        self.core = Core()
        self.root = None
        self.path_entry = None
        self.tree = None
        self.scan_path = DEFAULT_SCAN_PATH
        self.status_var = None
        self.scan_btn = None
        self.clean_btn = None
        self.path_var = None
        self.context_menu = None
        self.is_scanning = False  # 添加扫描状态标志

    def run(self, path: Path) -> None:
        """运行 GUI 界面"""

        self.scan_path = path
        if not self.root:
            self.create_ui()
            # GUI创建后 100ms 自动开始执行首次扫描
            self.root.after(100, self.toggle_scan)
        self.root.mainloop()

    def create_ui(self) -> None:
        """初始化用户界面"""

        # 创建主窗口
        self.root = tk.Tk()
        self.root.geometry("1200x700")
        self.root.minsize(900, 600)
        self.root.title(APP_TITLE)

        # 路径标签
        path_label = ttk.Label(self.root, text="Path to scan:")
        path_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        # 创建一个 StringVar 来关联路径输入框
        self.path_var = tk.StringVar(value=self.scan_path)
        self.path_var.trace_add(
            "write", lambda *args: setattr(self, "scan_path", Path(self.path_var.get())))

        # 路径输入框
        self.path_entry = ttk.Entry(self.root, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # 浏览按钮
        browse_btn = ttk.Button(self.root, text="📂 Browse", padding=5, width=8, command=self.browse_path)
        browse_btn.grid(row=0, column=2, padx=5, pady=5)

        # 修改扫描按钮的创建
        self.scan_btn = ttk.Button(self.root, text="🔍 Scan", padding=5, width=8, command=self.toggle_scan)
        self.scan_btn.grid(row=0, column=3, padx=5, pady=5)

        # 清理按钮
        self.clean_btn = ttk.Button(self.root, text="❌ Clean", padding=5, width=8, command=self.clean_files)
        self.clean_btn.grid(row=0, column=4, padx=5, pady=5)

        # Treeview
        self.tree = ttk.Treeview(self.root,
            columns=("select", "path", "kind", "size", "modified"), show="headings")

        self.tree.heading("select", text="☑")
        self.tree.heading("path", text="Path", command=lambda: self.treeview_sort("path", False))
        self.tree.heading("kind", text="Kind", command=lambda: self.treeview_sort("kind", False))
        self.tree.heading("size", text="Size", command=lambda: self.treeview_sort("size", False))
        self.tree.heading("modified", text="Modified", command=lambda: self.treeview_sort("modified", False))

        self.tree.column("select", width=10, anchor="center")
        self.tree.column("path", width=500)
        self.tree.column("kind", width=100, anchor="center")
        self.tree.column("size", width=100, anchor="center")
        self.tree.column("modified", width=100, anchor="center")

        ttk.Style().configure("Treeview", rowheight=25)

        self.tree.bind("<Button-1>", self.handle_select)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=5, sticky="ns")

        # 右键菜单
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open", command=self.open_file)
        self.context_menu.add_command(label="Open in Finder", command=self.open_in_finder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy as Path", command=self.copy_path)
        self.tree.bind("<Button-3>", self.show_context_menu)  # 绑定到 Treeview

        # 状态栏
        self.status_var = tk.StringVar()
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", padding=(5, 2))
        status_bar.grid(row=2, column=0, columnspan=6, sticky="ew")

        # 配置网格权重
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

    def browse_path(self) -> None:
        """打开文件夹选择对话框"""

        if path_str := filedialog.askdirectory():
            path = Path(path_str)
            self.path_var.set(str(path))  # StringVar 需要字符串
            self.scan_path = path

    def toggle_scan(self) -> None:
        """切换扫描/停止状态，处理扫描和停止功能"""

        if not self.is_scanning:  # 开始扫描
            # 检查路径是否存在
            if not self.scan_path.exists():
                messagebox.showerror("Error", "Path does not exist")
                return

            # 设置扫描状态
            self.is_scanning = True

            # 更新按钮外观
            self.scan_btn.config(text="🛑 Stop")
            self.clean_btn.config(state="disabled")

            # 清空现有内容
            for item in self.tree.get_children():
                self.tree.delete(item)

            # 开始扫描
            self.core.scan(self.scan_path)
            self.status_var.set("Scanning...")  # 设置初始扫描状态

            # 开始检查队列
            self.root.after(100, self.check_queue, time.time())

        else:  # 停止扫描
            self.core.abort_event.set()  # 触发中断事件
            self.is_scanning = False
            self.scan_btn.config(text="🔍 Scan")
            self.scan_btn.config(state="normal")
            self.clean_btn.config(state="normal" if self.tree.get_children() else "disabled")
            self.status_var.set("Scan cancelled")  # 立即更新状态为已取消

    def clean_files(self) -> None:
        """清理选中的文件"""

        try:
            # 获取所有选中的项目
            selected_items = [item for item in self.tree.get_children()
                             if self.tree.item(item)["values"][0] == "✓"]

            # 如果没有选中项目或用户取消操作, 则返回
            if not selected_items or not messagebox.askyesno("Confirm",
                "Are you sure you want to delete these files?"):
                return

            # 禁用清理按钮
            self.clean_btn.config(state="disabled")

            # 更新状态栏显示
            self.status_var.set("Cleaning...")

            # 将字符串路径转换为 Path 对象 (只获取路径列)
            items_to_clean = [Path(self.tree.item(item)["values"][1])
            for item in selected_items]

            # 开始清理
            self.core.clean(items_to_clean)

            # 开始检查队列
            self.root.after(100, self.check_queue, time.time())

        except Exception as e:
            # 如果遇到错误, 在状态栏显示错误消息, 并启用清理按钮
            self.status_var.set(f"Error starting cleanup: {str(e)}")
            self.clean_btn.config(state="normal")

    def check_queue(self, start_time: float) -> None:
        """检查队列中的消息"""

        # 如果已触发中断，停止检查队列
        if self.core.abort_event.is_set():
            return

        try:
            while True:
                try:  # 从队列中获取消息, 如果队列为空则退出循环
                    msg_type, data = self.core.queue.get_nowait()
                except queue.Empty:
                    break

                match msg_type:

                    case "found_item":  # 在 Treeview 中添加找到的项目
                        full_path, kind, size, modified = data
                        self.tree.insert("", "end", values=("✓", full_path, kind,
                                       self.core.format_size(size), modified))

                    case "scan_done":  # 在状态栏显示扫描完成后的统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time
                        self.status_var.set(
                            f"Scan completed in {elapsed:.2f}s. "
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}")
                        # 重置扫描状态和按钮
                        self.is_scanning = False
                        self.scan_btn.config(text="🔍 Scan")
                        self.scan_btn.config(state="normal")
                        # 清理按钮仅在有选中项时启用
                        self.clean_btn.config(state="normal" if any(
                            self.tree.item(i)["values"][0]=="✓"
                            for i in self.tree.get_children()) else "disabled")
                        return

                    case "clean_error":  # 在状态栏显示清理错误
                        path, error = data
                        self.status_var.set(f"Error cleaning {path}: {error}")

                    case "clean_done":  # 在状态栏显示清理完成消息
                        self.status_var.set("Cleanup completed")
                        # 清空 Treeview 内容
                        for item in self.tree.get_children():
                            self.tree.delete(item)
                        # 禁用清理按钮
                        self.clean_btn.config(state="disabled")
                        return

        except Exception as e:
            # 如果遇到错误，重置扫描状态和按钮
            self.is_scanning = False
            self.scan_btn.config(text="🔍 Scan")
            self.status_var.set(f"Error processing results: {str(e)}")
            self.scan_btn.config(state="normal")
            self.clean_btn.config(state="normal")

        # 如果扫描或清理线程仍在运行,继续检查队列
        if self.core.thread and self.core.thread.is_alive():
            self.root.after(100, self.check_queue, start_time)

    def handle_select(self, event: tk.Event) -> None:
        """处理 Treeview 的点击事件"""

        # 只处理复选框列的点击, 列表为空时不处理
        if (self.tree.identify_column(event.x) != "#1") or (not self.tree.get_children()):
            return

        # 获取点击的区域和项目
        region = self.tree.identify_region(event.x, event.y)
        new_state = None

        if region == "heading":  # 点击表头
            first_item = self.tree.get_children()[0]
            new_state = " " if self.tree.item(first_item)["values"][0] == "✓" else "✓"

            # 更新表头和所有项目
            self.tree.heading("select", text="☐" if new_state == " " else "☑")
            for item in self.tree.get_children():
                values = list(self.tree.item(item)["values"])
                values[0] = new_state
                self.tree.item(item, values=values)

        elif region == "cell":  # 点击单元格
            if item := self.tree.identify_row(event.y):
                values = list(self.tree.item(item)["values"])
                values[0] = " " if values[0] == "✓" else "✓"
                self.tree.item(item, values=values)

                # 更新表头状态
                all_checked = all(self.tree.item(i)["values"][0] == "✓"
                                for i in self.tree.get_children())
                self.tree.heading("select", text="☑" if all_checked else "☐")

        # 更新清理按钮状态
        has_selected = any(self.tree.item(i)["values"][0] == "✓"
                          for i in self.tree.get_children())
        self.clean_btn.config(state="normal" if has_selected else "disabled")

    def treeview_sort(self, col: str, reverse: bool) -> None:
        """对表格列进行排序"""

        # 获取待排序项目
        items = [(k, self.tree.set(k, col)) for k in self.tree.get_children("")]

        # 根据列的类型进行排序
        if col == "size":  # 按文件大小排序
            def size_to_bytes(size_str: str) -> float:
                """内部函数: 把文件大小字符串转换为字节"""
                num, unit = size_str.split()
                units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
                return float(num) * units[unit]
            items = sorted(items, key=lambda x: size_to_bytes(x[1]), reverse=reverse)
        else:
            items = sorted(items, key=lambda x: x[1], reverse=reverse)

        # 重新排列项目
        for idx, (item, _) in enumerate(items):
            self.tree.move(item, "", idx)

        # 更新表头排序指示器
        for header in ["path", "kind", "size", "modified"]:
            text = self.tree.heading(header)["text"].rstrip(" ↑↓")
            self.tree.heading(header,
                text=f"{text} {'↓' if header == col and reverse else '↑' if header == col else ''}")

        # 切换下次排序方向
        self.tree.heading(col, command=lambda: self.treeview_sort(col, not reverse))

    def show_context_menu(self, event: tk.Event) -> None:
        """显示右键菜单"""

        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def open_file(self) -> None:
        """打开选中的文件"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            try:
                if OS == "Darwin":
                    subprocess.run(["open", path])
                elif OS == "Windows":
                    os.startfile(path)
                else:
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file: {str(e)}")

    def open_in_finder(self) -> None:
        """在 Finder 中显示选中的文件"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            try:
                if OS == "Darwin":
                    subprocess.run(["open", "-R", path])
                elif OS == "Windows":
                    subprocess.run(["explorer", "/select,", path])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(path)])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {str(e)}")

    def copy_path(self) -> None:
        """复制选中文件的路径"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            self.root.clipboard_clear()
            self.root.clipboard_append(path)

class CLI:
    """CLI界面类"""
    def __init__(self) -> None:
        self.core = Core()
        self.results = []
        self.console = Console()
        self.scaning_status = None  # 扫描状态动画
        self.cleanup_status = None  # 清理状态动画

    def exit(self) -> None:
        """清理资源并退出程序"""

        # 设置中断标准
        if self.core:
            self.core.abort_event.set()

        # 确保退出前停止所有动画
        if self.scaning_status:
            self.scaning_status.stop()
        if self.cleanup_status:
            self.cleanup_status.stop()

        self.console.print("\nProgram terminated. ", style="red")

        # 退出程序
        sys.exit(0)

    def run(self, path: Path, auto: bool = False) -> None:
        """运行命令行界面"""

        try:
            # 显示程序标题
            title = Text(APP_TITLE, style="bold blue", justify="center")
            self.console.print(Panel(title, border_style="blue"))

            # 创建并启动扫描状态动画
            self.scaning_status = self.console.status(f"[green]Scanning {str(path)}...[/green]")
            self.scaning_status.start()

            # 开始扫描
            self.core.scan(path)
            self.check_queue(time.time(), auto)

        except KeyboardInterrupt:  # 捕获 Ctrl+C 退出程序
            self.exit()

    def check_queue(self, start_time: float, auto: bool = False) -> None:
        """检查队列中的消息"""

        # 创建结果表格
        table = Table(
            title="Scan Results",
            title_style="bold red",
            header_style="bold blue",
            border_style="blue"
        )
        table.add_column("Type", justify="center", style="red", min_width=6)
        table.add_column("Path", justify="default", style="default", min_width=30, overflow="fold")
        table.add_column("Size", justify="right", style="green", min_width=8)
        table.add_column("Modified", justify="center", style="yellow", min_width=19)

        try:
            while True:
                try:
                    # 从队列中获取消息
                    msg_type, data = self.core.queue.get(timeout=None)
                except queue.Empty:  # 如果队列为空, 继续检查线程是否仍在运行
                    if self.core.thread and self.core.thread.is_alive():
                        continue
                    break

                match msg_type:

                    case "found_item":  # 添加到表格
                        full_path, kind, size, modified = data
                        self.results.append(full_path)
                        table.add_row(kind, str(full_path), self.core.format_size(size), modified)

                    case "scan_done":  # 扫描完成后显示统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time

                        # 停止扫描动画
                        self.scaning_status.stop()

                        # 有找到垃圾文件时打印结果表格
                        if self.results:
                            self.console.print()
                            self.console.print(table)

                        # 打印统计信息
                        done_text = Text()
                        done_text.append(f"\nScan completed in {elapsed:.2f}s. ", style="bold green")
                        done_text.append(f"Found {file_count} items, ", style="bold green")
                        done_text.append(f"Total size: {self.core.format_size(total_size)}", style="bold green")
                        self.console.print(done_text)

                        # 如果找到垃圾文件: 非 --auto 模式下要求确认, 否则直接开始清理
                        if self.results:
                            if not auto:
                                ask_text = Text("\nDo you want to clean these files? ", style="red")
                                if not Confirm.ask(ask_text):
                                    self.console.print("\nCleanup cancelled", style="bold green")
                                    return

                            # 创建新的清理状态动画上下文
                            self.cleanup_status = self.console.status("[green]Cleaning...[/green]")
                            self.cleanup_status.start()

                            # 开始清理
                            self.core.clean(self.results)
                        else:
                            return

                    case "clean_error":  # 打印清理错误消息
                        path, error = data
                        self.console.print(f"Error deleting {path}: {error}", style="red")

                    case "clean_done":  # 清理完成后停止清理动画, 打印清理完成消息
                        self.cleanup_status.stop()
                        self.console.print("\nCleanup completed", style="bold green")
                        return

        except KeyboardInterrupt:  # 捕获 Ctrl+C 退出程序
            self.exit()

        except Exception as e:  # 捕获其他错误
            self.console.print(f"Error processing scan results: {str(e)}", style="red")

if __name__ == "__main__":
    """程序入口, 确保当程序不是以模块的形式被导入时才会执行"""

    # 命令行参数
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--cli", "-c", action="store_true", help="run in CLI mode")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="auto clean without confirmation (only works in CLI mode)")
    parser.add_argument("--path", "-p", type=Path, default=DEFAULT_SCAN_PATH,
                        help=f"path to scan (default: {DEFAULT_SCAN_PATH})")
    args = parser.parse_args()

    # 检查 --auto 参数的使用
    if args.auto and not args.cli:
        parser.error("--auto/-a option only works in CLI mode")

    # 根据参数选择运行模式
    if args.cli:
        CLI().run(args.path, args.auto)
    else:
        GUI().run(args.path)
