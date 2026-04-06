#!/usr/bin/env python3
"""
Wedding Photo Selector
======================
A cross-platform photo viewer for selecting wedding photos.
Browse photos from a USB drive, like the ones you want, and they'll be
copied + renamed sequentially into a 'selected' folder on the same drive.

Controls:
    → / d          Next photo
    ← / a          Previous photo
    Space / L      Like photo (copy to selected/)
    X / Delete     Dislike photo (remove from selected/)
    Ctrl+Z         Undo last like/dislike action
    E              Export summary for photographer
    P              Play/Pause auto-slideshow
    + / =          Speed up slideshow
    - / _          Slow down slideshow
    F / F11        Toggle fullscreen
    H / ?          Show/hide keyboard shortcuts
    Q / Escape     Quit
"""

import json
import os
import platform
import shutil
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    print("Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

RAW_SUPPORT = False
try:
    import rawpy
    RAW_SUPPORT = True
except ImportError:
    pass

# Supported file extensions
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp",
}
RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2",
    ".pef", ".sr2", ".srw", ".x3f", ".3fr", ".ari", ".bay", ".crw",
    ".dcr", ".erf", ".fff", ".iiq", ".k25", ".kdc", ".mef", ".mos",
    ".mrw", ".nrw", ".ptx", ".r3d", ".raw", ".rwl", ".rwz",
}

PROGRESS_FILE = ".photo_selector_progress.json"
SELECTED_DIR = "Aniket_Selected"
NAMING_PREFIX = "aniket_selected_"
SUMMARY_FILE = "selection_summary.txt"


class PhotoSelector:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Wedding Photo Selector")
        self.root.configure(bg="black")
        self.root.geometry("1200x800")

        # State
        self.photos: list[Path] = []
        self.current_index: int = 0
        # Maps relative source path -> selected filename (e.g. "aniket_selected_001.jpg")
        self.liked: dict[str, str] = {}
        self.like_counter: int = 0
        self.source_dir: Path | None = None
        self.drive_root: Path | None = None
        self.selected_dir: Path | None = None
        self.is_fullscreen: bool = False
        self.slideshow_active: bool = False
        self.slideshow_delay: int = 3000  # ms
        self.slideshow_job = None
        self.current_image = None  # keep reference to prevent GC
        self._resize_job = None
        self._progress_dirty = False
        self._help_visible = False
        self._help_widgets = []

        # Undo stack: list of (action, rel_key, selected_name, photo_index) tuples
        self._undo_stack: list[tuple[str, str, str, int]] = []

        # UI setup
        self._build_ui()
        self._bind_keys()

        # Start by asking for the photo directory
        self.root.after(100, self._choose_directory)

    def _build_ui(self):
        # Top bar
        self.top_frame = tk.Frame(self.root, bg="#1a1a1a", height=40)
        self.top_frame.pack(fill=tk.X, side=tk.TOP)
        self.top_frame.pack_propagate(False)

        self.info_label = tk.Label(
            self.top_frame, text="", fg="white", bg="#1a1a1a",
            font=("Helvetica", 12), anchor="w", padx=10,
        )
        self.info_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.slideshow_label = tk.Label(
            self.top_frame, text="", fg="#888888", bg="#1a1a1a",
            font=("Helvetica", 10), padx=10,
        )
        self.slideshow_label.pack(side=tk.RIGHT)

        # Image canvas
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bottom bar
        self.bottom_frame = tk.Frame(self.root, bg="#1a1a1a", height=50)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.bottom_frame.pack_propagate(False)

        btn_style = {"fg": "white", "bg": "#333333", "font": ("Helvetica", 11),
                      "relief": "flat", "padx": 12, "pady": 4, "cursor": "hand2"}

        self.prev_btn = tk.Button(self.bottom_frame, text="◀ Prev", command=self._prev_photo, **btn_style)
        self.prev_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.like_btn = tk.Button(self.bottom_frame, text="♥ Like", command=self._like_photo,
                                   fg="white", bg="#c0392b", font=("Helvetica", 11, "bold"),
                                   relief="flat", padx=16, pady=4, cursor="hand2")
        self.like_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.dislike_btn = tk.Button(self.bottom_frame, text="✕ Remove", command=self._dislike_photo,
                                      fg="white", bg="#7f8c8d", font=("Helvetica", 11),
                                      relief="flat", padx=12, pady=4, cursor="hand2")
        self.dislike_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.undo_btn = tk.Button(self.bottom_frame, text="↩ Undo", command=self._undo,
                                   fg="white", bg="#555555", font=("Helvetica", 11),
                                   relief="flat", padx=12, pady=4, cursor="hand2",
                                   state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.next_btn = tk.Button(self.bottom_frame, text="Next ▶", command=self._next_photo, **btn_style)
        self.next_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.play_btn = tk.Button(self.bottom_frame, text="▶ Play", command=self._toggle_slideshow, **btn_style)
        self.play_btn.pack(side=tk.LEFT, padx=8, pady=8)

        self.help_btn = tk.Button(self.bottom_frame, text="? Help", command=self._toggle_help, **btn_style)
        self.help_btn.pack(side=tk.RIGHT, padx=8, pady=8)

        self.export_btn = tk.Button(self.bottom_frame, text="📋 Export", command=self._export_summary, **btn_style)
        self.export_btn.pack(side=tk.RIGHT, padx=8, pady=8)

        self.counter_label = tk.Label(
            self.bottom_frame, text="", fg="#aaaaaa", bg="#1a1a1a",
            font=("Helvetica", 11), padx=10,
        )
        self.counter_label.pack(side=tk.RIGHT, padx=8)

        self.status_label = tk.Label(
            self.bottom_frame, text="", fg="#27ae60", bg="#1a1a1a",
            font=("Helvetica", 11), padx=10,
        )
        self.status_label.pack(side=tk.RIGHT)

        # Flash overlay (shown briefly on like/dislike)
        self.flash_label = tk.Label(
            self.canvas, text="", fg="#e74c3c", bg="black",
            font=("Helvetica", 28, "bold"),
        )

        # Bind resize
        self.canvas.bind("<Configure>", self._on_resize)

    def _bind_keys(self):
        self.root.bind("<Right>", lambda e: self._next_photo())
        self.root.bind("<Left>", lambda e: self._prev_photo())
        self.root.bind("d", lambda e: self._next_photo())
        self.root.bind("a", lambda e: self._prev_photo())
        self.root.bind("<space>", lambda e: self._like_photo())
        self.root.bind("l", lambda e: self._like_photo())
        self.root.bind("L", lambda e: self._like_photo())
        self.root.bind("x", lambda e: self._dislike_photo())
        self.root.bind("X", lambda e: self._dislike_photo())
        self.root.bind("<Delete>", lambda e: self._dislike_photo())
        self.root.bind("<BackSpace>", lambda e: self._dislike_photo())
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Command-z>", lambda e: self._undo())  # macOS Cmd+Z
        self.root.bind("e", lambda e: self._export_summary())
        self.root.bind("E", lambda e: self._export_summary())
        self.root.bind("p", lambda e: self._toggle_slideshow())
        self.root.bind("P", lambda e: self._toggle_slideshow())
        self.root.bind("f", lambda e: self._toggle_fullscreen())
        self.root.bind("F", lambda e: self._toggle_fullscreen())
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.root.bind("<plus>", lambda e: self._speed_up())
        self.root.bind("<equal>", lambda e: self._speed_up())
        self.root.bind("<minus>", lambda e: self._slow_down())
        self.root.bind("<underscore>", lambda e: self._slow_down())
        self.root.bind("h", lambda e: self._toggle_help())
        self.root.bind("H", lambda e: self._toggle_help())
        self.root.bind("<question>", lambda e: self._toggle_help())
        self.root.bind("q", lambda e: self._quit())
        self.root.bind("Q", lambda e: self._quit())
        self.root.bind("<Escape>", lambda e: self._quit())

    def _relative_key(self, photo_path: Path) -> str:
        """Return a path relative to source_dir for stable cross-session tracking."""
        try:
            return str(photo_path.relative_to(self.source_dir))
        except ValueError:
            return str(photo_path)

    @staticmethod
    def _find_drive_root(path: Path) -> Path:
        """Find the root/mount point of the drive containing the given path.

        - macOS: /Volumes/USB_NAME/
        - Windows: E:\\
        - Linux: /media/user/USB_NAME/ or /mnt/usb/
        - Fallback: the path itself (if not on a removable drive)
        """
        resolved = path.resolve()

        # macOS: /Volumes/<name>/...
        if str(resolved).startswith("/Volumes/"):
            parts = resolved.parts  # ('/', 'Volumes', 'USB_NAME', ...)
            if len(parts) >= 3:
                return Path(parts[0]) / parts[1] / parts[2]

        # Linux: /media/<user>/<name>/...
        if str(resolved).startswith("/media/"):
            parts = resolved.parts
            if len(parts) >= 4:
                return Path(parts[0]) / parts[1] / parts[2] / parts[3]

        # Linux: /mnt/<name>/...
        if str(resolved).startswith("/mnt/"):
            parts = resolved.parts
            if len(parts) >= 3:
                return Path(parts[0]) / parts[1] / parts[2]

        # Windows: drive letter root (e.g. E:\)
        if platform.system() == "Windows":
            return Path(resolved.anchor)

        # Fallback: use the selected directory itself
        return path

    def _is_drive_accessible(self) -> bool:
        """Check if the USB drive is still accessible."""
        try:
            return self.drive_root.exists() and os.access(str(self.drive_root), os.R_OK)
        except OSError:
            return False

    def _check_drive(self) -> bool:
        """Check drive accessibility and show error if disconnected. Returns True if OK."""
        if self._is_drive_accessible():
            return True
        messagebox.showerror(
            "Drive Disconnected",
            f"The USB drive is no longer accessible:\n{self.drive_root}\n\n"
            "Please reconnect the drive and try again.\n"
            "Your progress up to the last save has been preserved.",
        )
        return False

    def _choose_directory(self):
        directory = filedialog.askdirectory(
            title="Select the folder containing your wedding photos (USB drive)",
        )
        if not directory:
            messagebox.showinfo("No folder selected", "Please select a folder to continue.")
            self.root.destroy()
            return

        self.source_dir = Path(directory)
        self.drive_root = self._find_drive_root(self.source_dir)
        self.selected_dir = self.drive_root / SELECTED_DIR
        self._scan_photos()
        self._load_progress()
        self._show_current()

    def _scan_photos(self):
        all_extensions = IMAGE_EXTENSIONS.copy()
        if RAW_SUPPORT:
            all_extensions |= RAW_EXTENSIONS

        files = []

        def _collect(directory: Path):
            try:
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix.lower() in all_extensions:
                        files.append(f)
                    elif f.is_dir() and f.name != SELECTED_DIR:
                        _collect(f)
            except PermissionError:
                pass

        _collect(self.source_dir)
        self.photos = files

        if not self.photos:
            supported = ", ".join(sorted(all_extensions))
            messagebox.showwarning(
                "No photos found",
                f"No supported image files found in:\n{self.source_dir}\n\nSupported: {supported}",
            )
            self.root.destroy()

    def _load_progress(self):
        progress_path = self.drive_root / PROGRESS_FILE
        if progress_path.exists():
            try:
                data = json.loads(progress_path.read_text(encoding="utf-8"))
                self.current_index = min(data.get("current_index", 0), len(self.photos) - 1)
                self.like_counter = data.get("like_counter", 0)

                # Support both old format (list) and new format (dict)
                liked_data = data.get("liked", {})
                if isinstance(liked_data, list):
                    # Migrate old format: no filename mapping available
                    self.liked = {path: "" for path in liked_data}
                else:
                    self.liked = liked_data

                if self.current_index > 0:
                    resume = messagebox.askyesno(
                        "Resume?",
                        f"Found previous session.\n"
                        f"Resume from photo {self.current_index + 1}/{len(self.photos)}?\n"
                        f"({len(self.liked)} photos selected)\n\n"
                        f"Yes = Resume | No = Start from beginning",
                    )
                    if not resume:
                        self.current_index = 0
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_progress(self):
        if not self._progress_dirty:
            return
        if not self._is_drive_accessible():
            return
        progress_path = self.drive_root / PROGRESS_FILE
        data = {
            "current_index": self.current_index,
            "liked": self.liked,
            "like_counter": self.like_counter,
        }
        try:
            progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._progress_dirty = False
        except OSError:
            pass

    def _mark_dirty(self):
        """Mark progress as needing a save, and schedule a debounced write."""
        self._progress_dirty = True

    def _load_image(self, path: Path) -> Image.Image | None:
        try:
            if path.suffix.lower() in RAW_EXTENSIONS:
                if not RAW_SUPPORT:
                    return None
                with rawpy.imread(str(path)) as raw:
                    rgb = raw.postprocess()
                return Image.fromarray(rgb)
            else:
                img = Image.open(path)
                img.load()
                # Handle EXIF rotation
                try:
                    from PIL import ImageOps
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                return img
        except OSError:
            # File may be on a disconnected drive
            if not self._check_drive():
                return None
            return None
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None

    def _show_current(self):
        if not self.photos:
            return

        photo_path = self.photos[self.current_index]
        img = self._load_image(photo_path)

        if img is None:
            self.info_label.config(text=f"[Cannot load] {photo_path.name}")
            self._update_counter()
            return

        # Fit image to canvas
        canvas_w = self.canvas.winfo_width() or 1200
        canvas_h = self.canvas.winfo_height() or 700

        img_w, img_h = img.size
        scale = min(canvas_w / img_w, canvas_h / img_h, 1.0)
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))

        img = img.resize((new_w, new_h), Image.LANCZOS)
        self.current_image = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        x = canvas_w // 2
        y = canvas_h // 2
        self.canvas.create_image(x, y, anchor=tk.CENTER, image=self.current_image)

        # Show info
        rel_key = self._relative_key(photo_path)
        is_liked = rel_key in self.liked
        liked_marker = " [LIKED]" if is_liked else ""
        raw_marker = " [RAW]" if photo_path.suffix.lower() in RAW_EXTENSIONS else ""
        self.info_label.config(
            text=f"{photo_path.name}{raw_marker}{liked_marker}  |  "
                 f"{img_w}x{img_h}  |  {self._format_size(photo_path)}",
        )

        # Update like/dislike button states
        if is_liked:
            self.like_btn.config(text="♥ Liked", bg="#27ae60")
            self.dislike_btn.config(state=tk.NORMAL, bg="#c0392b")
        else:
            self.like_btn.config(text="♥ Like", bg="#c0392b")
            self.dislike_btn.config(state=tk.DISABLED, bg="#555555")

        self._update_counter()
        # Mark dirty for navigation tracking; actual write is deferred to quit
        self._progress_dirty = True

    def _update_counter(self):
        total = len(self.photos)
        current = self.current_index + 1
        self.counter_label.config(text=f"{current} / {total}")
        self.status_label.config(text=f"{len(self.liked)} selected")
        speed_sec = self.slideshow_delay / 1000
        state = "Playing" if self.slideshow_active else "Paused"
        self.slideshow_label.config(text=f"Slideshow: {state} ({speed_sec:.1f}s)")

        # Update undo button state
        if self._undo_stack:
            self.undo_btn.config(state=tk.NORMAL, bg="#333333")
        else:
            self.undo_btn.config(state=tk.DISABLED, bg="#555555")

    @staticmethod
    def _format_size(path: Path) -> str:
        size = path.stat().st_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _next_photo(self):
        if self.current_index < len(self.photos) - 1:
            self.current_index += 1
            self._show_current()
        elif self.slideshow_active:
            self._toggle_slideshow()  # Stop at end

    def _prev_photo(self):
        if self.current_index > 0:
            self.current_index -= 1
            self._show_current()

    def _like_photo(self):
        if not self.photos:
            return
        if not self._check_drive():
            return

        photo_path = self.photos[self.current_index]
        rel_key = self._relative_key(photo_path)

        if rel_key in self.liked:
            self._show_flash("Already selected!")
            return

        # Create selected directory if needed
        if not self.selected_dir.exists():
            try:
                self.selected_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Error", f"Cannot create selected folder:\n{e}")
                return

        # Copy with sequential name
        self.like_counter += 1
        ext = photo_path.suffix.lower()
        new_name = f"{NAMING_PREFIX}{self.like_counter:03d}{ext}"
        dest = self.selected_dir / new_name

        try:
            shutil.copy2(str(photo_path), str(dest))
        except OSError as e:
            self.like_counter -= 1
            if not self._check_drive():
                return
            messagebox.showerror("Error", f"Failed to copy photo:\n{e}")
            return

        self.liked[rel_key] = new_name
        self._undo_stack.append(("like", rel_key, new_name, self.current_index))
        self._mark_dirty()
        self._save_progress()
        self._show_flash(f"♥ Saved as {new_name}")
        self._show_current()

    def _dislike_photo(self):
        if not self.photos:
            return
        if not self._check_drive():
            return

        photo_path = self.photos[self.current_index]
        rel_key = self._relative_key(photo_path)

        if rel_key not in self.liked:
            self._show_flash("Not selected")
            return

        selected_name = self.liked[rel_key]
        if selected_name and self.selected_dir:
            selected_path = self.selected_dir / selected_name
            try:
                if selected_path.exists():
                    selected_path.unlink()
            except OSError as e:
                if not self._check_drive():
                    return
                messagebox.showerror("Error", f"Failed to remove photo:\n{e}")
                return

        del self.liked[rel_key]
        self._undo_stack.append(("dislike", rel_key, selected_name, self.current_index))
        self._mark_dirty()
        self._save_progress()
        self._show_flash("✕ Removed from selection")
        self._show_current()

    def _undo(self):
        """Undo the last like or dislike action."""
        if not self._undo_stack:
            self._show_flash("Nothing to undo")
            return
        if not self._check_drive():
            return

        action, rel_key, selected_name, photo_index = self._undo_stack.pop()

        if action == "like":
            # Undo a like: remove the copied file and unmark
            if selected_name and self.selected_dir:
                selected_path = self.selected_dir / selected_name
                try:
                    if selected_path.exists():
                        selected_path.unlink()
                except OSError:
                    pass
            self.liked.pop(rel_key, None)
            self._show_flash(f"↩ Undo: removed {selected_name}")

        elif action == "dislike":
            # Undo a dislike: re-copy the file and re-mark
            source_path = self.source_dir / rel_key
            if source_path.exists() and selected_name:
                if not self.selected_dir.exists():
                    self.selected_dir.mkdir(parents=True, exist_ok=True)
                dest = self.selected_dir / selected_name
                try:
                    shutil.copy2(str(source_path), str(dest))
                    self.liked[rel_key] = selected_name
                    self._show_flash(f"↩ Undo: restored {selected_name}")
                except OSError:
                    self._show_flash("↩ Undo failed: copy error")
                    return
            else:
                self._show_flash("↩ Undo failed: source missing")
                return

        # Navigate to the photo that was affected
        self.current_index = min(photo_index, len(self.photos) - 1)
        self._mark_dirty()
        self._save_progress()
        self._show_current()

    def _toggle_help(self):
        """Show or hide the keyboard shortcuts overlay."""
        if self._help_visible:
            self._hide_help()
        else:
            self._show_help()

    def _show_help(self):
        self._help_visible = True

        shortcuts = [
            ("Navigation", [
                ("→  or  D", "Next photo"),
                ("←  or  A", "Previous photo"),
                ("P", "Play / Pause slideshow"),
                ("+  /  -", "Speed up / slow down"),
            ]),
            ("Selection", [
                ("Space  or  L", "Like photo"),
                ("X  or  Delete", "Remove from selection"),
                ("Ctrl+Z", "Undo last action"),
            ]),
            ("View", [
                ("F  or  F11", "Toggle fullscreen"),
                ("H  or  ?", "Show / hide this help"),
            ]),
            ("Other", [
                ("E", "Export summary for photographer"),
                ("Q  or  Esc", "Quit"),
            ]),
        ]

        # Semi-transparent background overlay
        canvas_w = self.canvas.winfo_width() or 1200
        canvas_h = self.canvas.winfo_height() or 700

        overlay = self.canvas.create_rectangle(
            0, 0, canvas_w, canvas_h, fill="black", stipple="gray50", tags="help",
        )

        # Title
        y_pos = canvas_h // 2 - 180
        self.canvas.create_text(
            canvas_w // 2, y_pos, text="Keyboard Shortcuts",
            fill="white", font=("Helvetica", 20, "bold"), tags="help",
        )
        y_pos += 40

        for section_name, keys in shortcuts:
            self.canvas.create_text(
                canvas_w // 2 - 150, y_pos, text=section_name,
                fill="#3498db", font=("Helvetica", 14, "bold"), anchor="w", tags="help",
            )
            y_pos += 28
            for key, desc in keys:
                self.canvas.create_text(
                    canvas_w // 2 - 130, y_pos, text=key,
                    fill="#f39c12", font=("Courier", 12, "bold"), anchor="w", tags="help",
                )
                self.canvas.create_text(
                    canvas_w // 2 + 50, y_pos, text=desc,
                    fill="white", font=("Helvetica", 12), anchor="w", tags="help",
                )
                y_pos += 24
            y_pos += 10

        self.canvas.create_text(
            canvas_w // 2, y_pos + 10, text="Press H or ? to close",
            fill="#888888", font=("Helvetica", 11), tags="help",
        )

    def _hide_help(self):
        self._help_visible = False
        self.canvas.delete("help")

    def _export_summary(self):
        """Export a text summary of selected photos for the photographer."""
        if not self.liked:
            self._show_flash("No photos selected yet")
            return
        if not self._check_drive():
            return

        lines = []
        lines.append("=" * 60)
        lines.append("WEDDING PHOTO SELECTION SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Source:    {self.source_dir}")
        lines.append(f"Output:    {self.selected_dir}")
        lines.append(f"Total selected: {len(self.liked)} photos")
        lines.append("")
        lines.append("-" * 60)
        lines.append(f"{'Selected Name':<35} {'Original File'}")
        lines.append("-" * 60)

        # Sort by selected name for clean output
        sorted_items = sorted(self.liked.items(), key=lambda x: x[1])
        for original_rel, selected_name in sorted_items:
            if selected_name:
                lines.append(f"{selected_name:<35} {original_rel}")
            else:
                lines.append(f"{'(unknown)':<35} {original_rel}")

        lines.append("-" * 60)
        lines.append("")
        lines.append("INSTRUCTIONS FOR PHOTOGRAPHER:")
        lines.append(f"  All selected photos are in the '{SELECTED_DIR}' folder.")
        lines.append(f"  Files are named {NAMING_PREFIX}001, 002, etc.")
        lines.append("  Original filenames are listed above for reference.")
        lines.append("")

        summary_text = "\n".join(lines)
        summary_path = self.selected_dir / SUMMARY_FILE

        try:
            if not self.selected_dir.exists():
                self.selected_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(summary_text, encoding="utf-8")
            self._show_flash(f"📋 Exported to {SUMMARY_FILE}")
        except OSError as e:
            messagebox.showerror("Export Error", f"Failed to export summary:\n{e}")

    def _show_flash(self, text: str):
        # Set color based on action
        if "Removed" in text or "✕" in text:
            color = "#e67e22"  # orange for removal
        elif "♥" in text or "Saved" in text:
            color = "#2ecc71"  # green for like
        elif "↩" in text:
            color = "#3498db"  # blue for undo
        elif "📋" in text or "Export" in text:
            color = "#9b59b6"  # purple for export
        else:
            color = "#e74c3c"  # red for info

        self.flash_label.config(text=text, fg=color)
        self.flash_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.root.after(1000, lambda: self.flash_label.place_forget())

    def _toggle_slideshow(self):
        self.slideshow_active = not self.slideshow_active
        if self.slideshow_active:
            self.play_btn.config(text="⏸ Pause")
            self._slideshow_tick()
        else:
            self.play_btn.config(text="▶ Play")
            if self.slideshow_job:
                self.root.after_cancel(self.slideshow_job)
                self.slideshow_job = None
        self._update_counter()

    def _slideshow_tick(self):
        if self.slideshow_active:
            self._next_photo()
            self.slideshow_job = self.root.after(self.slideshow_delay, self._slideshow_tick)

    def _speed_up(self):
        self.slideshow_delay = max(500, self.slideshow_delay - 500)
        self._update_counter()

    def _slow_down(self):
        self.slideshow_delay = min(10000, self.slideshow_delay + 500)
        self._update_counter()

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)
        # On macOS, also handle the topmost attribute
        if platform.system() == "Darwin":
            self.root.attributes("-topmost", self.is_fullscreen)

    def _on_resize(self, event):
        if self.photos:
            if self._resize_job is not None:
                self.root.after_cancel(self._resize_job)
            self._resize_job = self.root.after(150, self._show_current)

    def _quit(self):
        self._mark_dirty()
        self._save_progress()
        self.root.destroy()


def main():
    if not RAW_SUPPORT:
        print("Note: RAW file support not available. Install rawpy for RAW support:")
        print("  pip install rawpy")
        print("Continuing with standard image formats only...\n")

    root = tk.Tk()
    root.minsize(800, 600)
    PhotoSelector(root)
    root.mainloop()


if __name__ == "__main__":
    main()
