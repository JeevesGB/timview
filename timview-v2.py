#!/usr/bin/env python3
"""
TIM Viewer & Converter - Full script with UI upgrades

Features:
- View .tim (PlayStation TIM), .png, .bmp
- Convert TIM -> PNG/BMP, PNG/BMP -> TIM (basic)
- Modern dark ttk UI
- Split layout: file list, thumbnail grid, preview
- Drag & drop support via tkinterdnd2 (optional)
- Right-click context menu for files
- Palette (CLUT) preview & quick palette switch
- TIM header inspector
- Keyboard navigation & mouse wheel zoom
- Batch conversion and thumbnails caching

Dependencies:
- Pillow (PIL)
- numpy
- tkinter (stdlib)
- tkinterdnd2 (optional, for drag & drop)
"""

import os
import sys
import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageOps
import numpy as np
import platform
import subprocess
import math
import io
import traceback

# ---------- Optional drag & drop ----------
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

# ---------- TIM read / write functions ----------
def read_tim(filepath, palette_index=0):
    """
    Return a PIL.Image for the TIM file at filepath.
    Supports 4bpp (CLUT), 8bpp (CLUT), 16bpp, 24bpp.
    """
    with open(filepath, 'rb') as f:
        magic = struct.unpack("<I", f.read(4))[0]
        if magic != 0x10:
            raise ValueError("Not a TIM file (bad magic)")

        flags = struct.unpack("<I", f.read(4))[0]
        has_clut = bool(flags & 0x08)
        bpp_mode = flags & 0x07
        bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(bpp_mode, None)
        if bpp is None:
            raise ValueError(f"Unsupported BPP mode: {bpp_mode}")

        clut = None
        selected_palette = None
        if has_clut:
            clut_block_size = struct.unpack("<I", f.read(4))[0]
            clut_x, clut_y, clut_w, clut_h = struct.unpack("<4H", f.read(8))
            clut_data = f.read(clut_block_size - 12)
            clut_colors = np.frombuffer(clut_data, dtype=np.uint16)
            try:
                clut = clut_colors.reshape((-1, clut_w))
            except Exception:
                clut = clut_colors.reshape((1, -1))
            if palette_index >= len(clut):
                palette_index = 0
            selected_palette = clut[palette_index]
        else:
            selected_palette = None

        img_block_size = struct.unpack("<I", f.read(4))[0]
        x, y, w_words, h = struct.unpack("<4H", f.read(8))

        if bpp == 4:
            w = w_words * 4
        elif bpp == 8:
            w = w_words * 2
        else:
            w = w_words

        raw_data = f.read()

        if bpp == 4:
            num_pixels = w * h
            bytes_needed = (num_pixels + 1) // 2
            pixels = np.frombuffer(raw_data[:bytes_needed], dtype=np.uint8)
            pixels_unpack = np.zeros(num_pixels, dtype=np.uint8)
            for i in range(num_pixels):
                byte = pixels[i // 2]
                if (i & 1) == 0:
                    pixels_unpack[i] = byte & 0x0F
                else:
                    pixels_unpack[i] = (byte >> 4) & 0x0F
            pixels = pixels_unpack.reshape((h, w))
            if selected_palette is None:
                color_vals = np.array([(i & 0x1F) | ((i & 0x1F) << 5) | ((i & 0x1F) << 10) for i in range(16)], dtype=np.uint16)
                color_vals = color_vals[pixels]
            else:
                color_vals = selected_palette[pixels]

        elif bpp == 8:
            pixels = np.frombuffer(raw_data[:w * h], dtype=np.uint8).reshape((h, w))
            if selected_palette is None:
                selected_palette = np.array([(i & 0x1F) | ((i & 0x1F) << 5) | ((i & 0x1F) << 10) for i in range(256)], dtype=np.uint16)
            color_vals = selected_palette[pixels]

        elif bpp == 16:
            img_array = np.frombuffer(raw_data[:w * h * 2], dtype=np.uint16).reshape((h, w))
            r = (img_array & 0x1F) << 3
            g = ((img_array >> 5) & 0x1F) << 3
            b = ((img_array >> 10) & 0x1F) << 3
            rgb = np.stack([r, g, b], axis=2).astype(np.uint8)
            return Image.fromarray(rgb, mode="RGB")

        elif bpp == 24:
            return Image.frombytes("RGB", (w, h), raw_data[:w * h * 3], "raw", "RGB")

        else:
            raise NotImplementedError("Unsupported BPP")

        r = (color_vals & 0x1F) << 3
        g = ((color_vals >> 5) & 0x1F) << 3
        b = ((color_vals >> 10) & 0x1F) << 3
        r_img = Image.fromarray(r.astype(np.uint8))
        g_img = Image.fromarray(g.astype(np.uint8))
        b_img = Image.fromarray(b.astype(np.uint8))
        return Image.merge("RGB", [r_img, g_img, b_img])


def image_to_tim(image: Image.Image, bpp=8):
    """
    Basic TIM writer: writes TIM with CLUT for 4bpp or 8bpp.
    Input image should be 'P' mode (palette) or will be converted.
    Returns bytes of TIM file.
    """
    if bpp not in (4, 8):
        raise NotImplementedError("Only 4bpp and 8bpp supported for writing TIM")

    if image.mode != 'P':
        colors = 16 if bpp == 4 else 256
        image = image.convert('P', palette=Image.ADAPTIVE, colors=colors)

    palette = image.getpalette()
    if palette is None:
        raise ValueError("Image has no palette")

    width, height = image.size
    pixels = np.array(image)

    clut_colors = []
    pal_len = 16 if bpp == 4 else 256
    for i in range(pal_len):
        idx = i * 3
        if idx + 2 >= len(palette):
            r, g, b = 0, 0, 0
        else:
            r = palette[idx] >> 3
            g = palette[idx + 1] >> 3
            b = palette[idx + 2] >> 3
        color_16 = (b << 10) | (g << 5) | r
        clut_colors.append(color_16 & 0xFFFF)

    clut_array = np.array(clut_colors, dtype=np.uint16)
    clut_data = clut_array.tobytes()
    clut_w = 16 if bpp == 4 else 256
    clut_h = 1

    header = struct.pack("<I", 0x10)
    flags_val = 0x08
    flags_val |= 0 if bpp == 4 else 1
    header += struct.pack("<I", flags_val)

    clut_block_size = 12 + len(clut_data)
    header += struct.pack("<I", clut_block_size)
    header += struct.pack("<4H", 0, 0, clut_w, clut_h)
    header += clut_data

    if bpp == 4:
        w_words = (width + 3) // 4
        flat_pixels = pixels.flatten()
        flat_pixels = np.clip(flat_pixels, 0, 15)
        packed = bytearray()
        for i in range(0, len(flat_pixels), 2):
            first = int(flat_pixels[i])
            second = int(flat_pixels[i+1]) if i+1 < len(flat_pixels) else 0
            packed.append((second << 4) | first)
        pixel_bytes = bytes(packed)
    else:
        w_words = (width + 1) // 2
        pixel_bytes = pixels.tobytes()

    img_block_size = 12 + len(pixel_bytes)
    header += struct.pack("<I", img_block_size)
    header += struct.pack("<4H", 0, 0, w_words, height)
    header += pixel_bytes

    return header

# ---------- UI Application ----------
class TIMViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TIM Viewer & Converter")
        self.root.geometry("1300x920")
        self._setup_style()
        self._create_widgets()

        self.tim_files = []
        self.file_types = []
        self.palettes = []
        self.palette_indices = []
        self.bpp_modes = []
        self.thumb_cache = {}
        self.index = 0

        self.zoom_level_var.set(4)
        self.thumbnail_mode = tk.BooleanVar(value=True)
        self.show_palette_preview = tk.BooleanVar(value=True)

        if DND_AVAILABLE:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self._on_dnd)
            except Exception:
                pass

    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        bg = "#111214"
        fg = "#E7E7E7"
        accent = "#3A82F6"
        panel = "#1c1c1e"
        light_panel = "#222226"

        self.root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg, relief="flat")
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background=light_panel, foreground=fg, padding=6)
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9))
        style.configure("Info.TLabel", font=("Segoe UI", 9))
        style.map("TButton", background=[("active", panel)])

        self._colors = dict(bg=bg, fg=fg, accent=accent, panel=panel, light_panel=light_panel)

    def _create_widgets(self):
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill="x", padx=6, pady=6)

        ttk.Button(toolbar, text="Select Folder", command=self.select_folder).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Add Files", command=self.add_files_dialog).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Batch Convert", command=self.batch_convert).pack(side="left", padx=6)

        ttk.Label(toolbar, text="Zoom:").pack(side="left", padx=(12,2))
        self.zoom_level_var = tk.IntVar(value=4)
        self.zoom_cb = ttk.Combobox(toolbar, textvariable=self.zoom_level_var, width=4, state="readonly",
                                    values=[1,2,3,4,5,6,7,8])
        self.zoom_cb.pack(side="left")
        self.zoom_cb.bind("<<ComboboxSelected>>", lambda e: self.display_image())

        ttk.Button(toolbar, text="Refresh Thumbs", command=self._refresh_thumbs).pack(side="left", padx=8)

        ttk.Label(toolbar, text=" ").pack(side="left", expand=True)

        self.thumbnail_mode = tk.BooleanVar(value=True)
        self.show_palette_preview = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Thumbnail Grid", variable=self.thumbnail_mode,
                        command=self._toggle_thumb_mode).pack(side="right", padx=6)
        ttk.Checkbutton(toolbar, text="Palette Preview", variable=self.show_palette_preview,
                        command=self._update_palette_preview).pack(side="right", padx=6)

        main_paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill="both", expand=True, padx=6, pady=(0,6))

        left_frame = ttk.Frame(main_paned, width=380)
        left_frame.pack_propagate(False)
        main_paned.add(left_frame, weight=1)

        list_label = ttk.Label(left_frame, text="Loaded Files", style="Header.TLabel")
        list_label.pack(anchor="w", padx=6, pady=(6,2))

        self.file_listbox = tk.Listbox(left_frame, bg=self._colors['light_panel'], fg=self._colors['fg'],
                                       height=12, selectbackground="#3f3f3f", activestyle='none')
        self.file_listbox.pack(fill="x", padx=6)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self.file_listbox.bind("<Button-3>", self._on_list_right_click)

        thumbs_label = ttk.Label(left_frame, text="Thumbnails", style="Header.TLabel")
        thumbs_label.pack(anchor="w", padx=6, pady=(8,2))

        self.thumb_canvas_frame = ttk.Frame(left_frame)
        self.thumb_canvas_frame.pack(fill="both", expand=True, padx=6, pady=2)

        self.thumb_canvas = tk.Canvas(self.thumb_canvas_frame, bg=self._colors['panel'], highlightthickness=0)
        self.thumb_vscroll = ttk.Scrollbar(self.thumb_canvas_frame, orient="vertical", command=self.thumb_canvas.yview)
        self.thumb_canvas.configure(yscrollcommand=self.thumb_vscroll.set)
        self.thumb_vscroll.pack(side="right", fill="y")
        self.thumb_canvas.pack(side="left", fill="both", expand=True)

        self.thumb_inner = ttk.Frame(self.thumb_canvas)
        self.thumb_window = self.thumb_canvas.create_window((0,0), window=self.thumb_inner, anchor="nw")
        self.thumb_inner.bind("<Configure>", lambda e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.bind('<Configure>', lambda e: self.thumb_canvas.itemconfigure(self.thumb_window, width=e.width))

        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=3)

        preview_holder = ttk.Frame(right_frame)
        preview_holder.pack(fill="both", expand=True, padx=6, pady=6)

        self.preview_label = tk.Label(preview_holder, text="No image", bg=self._colors['panel'])
        self.preview_label.pack(fill="both", expand=True)
        self.preview_label.bind("<MouseWheel>", self._on_mouse_wheel)
        self.preview_label.bind("<Button-4>", self._on_mouse_wheel)
        self.preview_label.bind("<Button-5>", self._on_mouse_wheel)

        info_frame = ttk.Frame(right_frame)
        info_frame.pack(fill="x", padx=6, pady=(0,6))

        pal_frame = ttk.LabelFrame(info_frame, text="Palette (CLUT) Preview")
        pal_frame.pack(side="left", fill="x", expand=True, padx=(0,6))

        self.palette_preview_canvas = tk.Canvas(pal_frame, height=60, bg=self._colors['panel'], highlightthickness=0)
        self.palette_preview_canvas.pack(fill="x", padx=6, pady=6)
        self.palette_preview_canvas.bind("<Button-1>", self._on_palette_click)

        inspector_frame = ttk.LabelFrame(info_frame, text="TIM Header Inspector", width=360)
        inspector_frame.pack(side="right", fill="both", padx=(6,0))
        inspector_frame.pack_propagate(False)

        self.inspector_text = tk.Text(inspector_frame, height=6, bg=self._colors['light_panel'], fg=self._colors['fg'],
                                      wrap="word")
        self.inspector_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.inspector_text.configure(state="disabled")

        self.status_label = ttk.Label(self.root, text="Ready", style="Small.TLabel", anchor="w")
        self.status_label.pack(fill="x", padx=6, pady=(0,6))

        self._create_context_menu()
        self.root.bind("<Left>", lambda e: self.prev_image())
        self.root.bind("<Right>", lambda e: self.next_image())

    def _create_context_menu(self):
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open", command=self._context_open)
        self.context_menu.add_command(label="Remove", command=self._context_remove)
        self.context_menu.add_command(label="Reveal in Explorer", command=self._context_reveal)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Properties", command=self._context_properties)

    def _on_list_right_click(self, event):
        try:
            idx = self.file_listbox.nearest(event.y)
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(idx)
            self.index = idx
            self.update_ui_for_selection()
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _context_open(self):
        path = self._current_path()
        if path:
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.run(["open", path])
                else:
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Open Failed", str(e))

    def _context_remove(self):
        idx = self._current_index()
        if idx is None:
            return
        removed = self.tim_files.pop(idx)
        self.file_types.pop(idx)
        self.palettes.pop(idx)
        self.palette_indices.pop(idx)
        self.bpp_modes.pop(idx)
        self._remove_thumb(removed)
        self._refresh_file_list()
        self.index = max(0, idx-1)
        self.display_image()

    def _context_reveal(self):
        path = self._current_path()
        if not path:
            return
        folder = os.path.dirname(path)
        try:
            if platform.system() == "Windows":
                subprocess.run(["explorer", "/select,", path])
            elif platform.system() == "Darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Reveal Failed", str(e))

    def _context_properties(self):
        path = self._current_path()
        if not path:
            return
        try:
            info = []
            info.append(f"Path: {path}")
            info.append(f"Size: {os.path.getsize(path)} bytes")
            info.append(f"Modified: {os.path.getmtime(path)}")
            messagebox.showinfo("Properties", "\n".join(info))
        except Exception as e:
            messagebox.showerror("Properties", str(e))

    def _current_index(self):
        sel = self.file_listbox.curselection()
        if not sel:
            return None
        return sel[0]

    def _current_path(self):
        idx = self._current_index()
        if idx is None:
            return None
        return self.tim_files[idx]

    def add_files_dialog(self):
        files = filedialog.askopenfilenames(title="Select files", filetypes=[("Images & TIM", "*.tim;*.png;*.bmp;*.jpg;*.jpeg"),("All files","*.*")])
        if not files:
            return
        self._add_paths(files)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        paths = [os.path.join(folder, p) for p in os.listdir(folder)]
        self._add_paths(paths)

    def _add_paths(self, paths):
        added = 0
        for path in paths:
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext == '.tim':
                try:
                    with open(path, "rb") as f:
                        if struct.unpack("<I", f.read(4))[0] != 0x10:
                            continue
                except Exception:
                    continue
                self.tim_files.append(path)
                self.file_types.append('tim')
            elif ext in ('.png', '.bmp', '.jpg', '.jpeg'):
                self.tim_files.append(path)
                self.file_types.append(ext[1:])
            else:
                continue

            idx = len(self.tim_files) - 1
            bpp = 24
            palettes_count = 1
            try:
                if self.file_types[idx] == 'tim':
                    with open(self.tim_files[idx], 'rb') as f:
                        f.seek(4)
                        flags = struct.unpack("<I", f.read(4))[0]
                        has_clut = flags & 0x08
                        bpp_mode = flags & 0x07
                        bpp = {0:4,1:8,2:16,3:24}.get(bpp_mode, 24)
                        if has_clut:
                            f.seek(12)
                            clut_sz = struct.unpack("<I", f.read(4))[0]
                            cx, cy, cw, ch = struct.unpack("<4H", f.read(8))
                            palettes_count = ch if ch > 0 else 1
            except Exception:
                palettes_count = 1
                bpp = 24

            self.palettes.append(palettes_count)
            self.palette_indices.append(0)
            self.bpp_modes.append(bpp)

            added += 1

        if added:
            self._refresh_file_list()
            self._populate_thumbnails()
            self.index = 0
            self._ensure_selection()
            self.display_image()
            self._update_palette_preview()

    def _populate_thumbnails(self):
        for child in self.thumb_inner.winfo_children():
            child.destroy()

        cols = 3
        thumb_size = 120
        pad = 6
        cur_col = 0
        cur_row = 0

        for i, path in enumerate(self.tim_files):
            frame = ttk.Frame(self.thumb_inner, width=thumb_size, height=thumb_size)
            frame.grid(row=cur_row, column=cur_col, padx=pad, pady=pad)
            frame.grid_propagate(False)

            tkimg = self._get_thumbnail_for(path, thumb_size - 4)
            lbl = tk.Label(frame, image=tkimg, bg=self._colors['panel'])
            lbl.image = tkimg
            lbl.pack(expand=True)
            lbl.bind("<Button-1>", lambda e, idx=i: self._on_thumb_click(idx))
            lbl.bind("<Button-3>", lambda e, idx=i: self._on_thumb_right_click(e, idx))

            fname = os.path.basename(path)
            small = ttk.Label(frame, text=fname, style="Small.TLabel")
            small.pack(anchor="w")

            cur_col += 1
            if cur_col >= cols:
                cur_col = 0
                cur_row += 1

    def _on_thumb_click(self, idx):
        self.index = idx
        self.file_listbox.selection_clear(0, tk.END)
        if idx < self.file_listbox.size():
            self.file_listbox.selection_set(idx)
        self.update_ui_for_selection()
        self.display_image()

    def _on_thumb_right_click(self, event, idx):
        self.index = idx
        self.file_listbox.selection_clear(0, tk.END)
        if idx < self.file_listbox.size():
            self.file_listbox.selection_set(idx)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _get_thumbnail_for(self, path, size=100):
        if path in self.thumb_cache:
            return self.thumb_cache[path]

        try:
            if self.file_types[self.tim_files.index(path)] == 'tim':
                img = read_tim(path, 0)
            else:
                img = Image.open(path).convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (size, size), (60,60,60,255))
        img.thumbnail((size, size), Image.LANCZOS)
        bg = Image.new("RGBA", (size, size), (34,34,34,255))
        w,h = img.size
        bg.paste(img, ((size-w)//2, (size-h)//2), img if img.mode == 'RGBA' else None)
        tkimg = ImageTk.PhotoImage(bg)
        self.thumb_cache[path] = tkimg
        return tkimg

    def _remove_thumb(self, path):
        if path in self.thumb_cache:
            del self.thumb_cache[path]
        self._populate_thumbnails()

    def _refresh_thumbs(self):
        self.thumb_cache.clear()
        self._populate_thumbnails()

    def _refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for p in self.tim_files:
            self.file_listbox.insert(tk.END, os.path.basename(p))

    def _ensure_selection(self):
        if not self.tim_files:
            return
        if self.file_listbox.size() > 0:
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(self.index)

    def _toggle_thumb_mode(self):
        self._populate_thumbnails()

    def _on_list_select(self, event):
        sel = event.widget.curselection()
        if not sel:
            return
        self.index = sel[0]
        self.update_ui_for_selection()
        self.display_image()

    def update_ui_for_selection(self):
        self._update_inspector()
        self._update_palette_preview()

    def _update_palette_preview(self):
        self.palette_preview_canvas.delete("all")
        if not self.tim_files or not self.show_palette_preview.get():
            return
        idx = self.index
        if self.file_types[idx] != 'tim':
            return
        path = self.tim_files[idx]
        try:
            with open(path, 'rb') as f:
                f.seek(4)
                flags = struct.unpack("<I", f.read(4))[0]
                has_clut = flags & 0x08
                if not has_clut:
                    return
                f.seek(12)
                clut_block_size = struct.unpack("<I", f.read(4))[0]
                cx, cy, cw, ch = struct.unpack("<4H", f.read(8))
                clut_data = f.read(clut_block_size - 12)
                clut_colors = np.frombuffer(clut_data, dtype=np.uint16)
                if cw == 0:
                    return
                rows = ch
                cols = cw
                sel_row = self.palette_indices[idx] if idx < len(self.palette_indices) else 0
                start = sel_row * cols
                end = start + cols
                row_colors = clut_colors[start:end]
                w = self.palette_preview_canvas.winfo_width() or 400
                h = self.palette_preview_canvas.winfo_height() or 60
                box_w = max(8, w // max(1, len(row_colors)))
                for i, c in enumerate(row_colors):
                    r = (c & 0x1F) << 3
                    g = ((c >> 5) & 0x1F) << 3
                    b = ((c >> 10) & 0x1F) << 3
                    x0 = i * box_w
                    x1 = x0 + box_w
                    self.palette_preview_canvas.create_rectangle(x0, 0, x1, h, fill=_rgb_to_hex((r,g,b)), outline="")
        except Exception:
            pass

    def _on_palette_click(self, event):
        if not self.tim_files:
            return
        idx = self.index
        if self.file_types[idx] != 'tim':
            return
        path = self.tim_files[idx]
        try:
            with open(path, 'rb') as f:
                f.seek(4)
                flags = struct.unpack("<I", f.read(4))[0]
                has_clut = flags & 0x08
                if not has_clut:
                    return
                f.seek(12)
                clut_block_size = struct.unpack("<I", f.read(4))[0]
                cx, cy, cw, ch = struct.unpack("<4H", f.read(8))
                if cw <= 0:
                    return
                w = self.palette_preview_canvas.winfo_width() or 400
                box_w = w / cw
                clicked_col = int(event.x // box_w)
                new_index = clicked_col
                new_index = max(0, min(new_index, cw-1))
                self.palette_indices[idx] = new_index
                self.display_image()
                self._update_palette_preview()
        except Exception:
            pass

    def _update_inspector(self):
        self.inspector_text.configure(state="normal")
        self.inspector_text.delete("1.0", tk.END)
        if not self.tim_files:
            self.inspector_text.insert("1.0", "No file selected")
            self.inspector_text.configure(state="disabled")
            return
        path = self.tim_files[self.index]
        try:
            with open(path, 'rb') as f:
                data = f.read(64)
            out = []
            try:
                magic = struct.unpack_from("<I", data, 0)[0]
                out.append(f"Magic: 0x{magic:08X}")
                flags = struct.unpack_from("<I", data, 4)[0]
                out.append(f"Flags: 0x{flags:08X}")
                has_clut = bool(flags & 0x08)
                bpp_mode = flags & 0x07
                out.append(f"Has CLUT: {has_clut}")
                # fixed f-string usage by precomputing lookup
                bpp_names = {0: '4bpp', 1: '8bpp', 2: '16bpp', 3: '24bpp'}
                out.append(f"BPP mode: {bpp_mode} ({bpp_names.get(bpp_mode, '?')})")
            except Exception:
                out.append("Not a TIM or header too short")
            out.append(f"Path: {path}")
            try:
                out.append(f"Size: {os.path.getsize(path)} bytes")
            except Exception:
                pass
            self.inspector_text.insert("1.0", "\n".join(out))
        except Exception as e:
            self.inspector_text.insert("1.0", f"Error reading file: {e}\n{traceback.format_exc()}")
        self.inspector_text.configure(state="disabled")

    def display_image(self):
        if not self.tim_files:
            self.preview_label.config(image="", text="No image")
            self.status_label.config(text="No files loaded")
            return
        path = self.tim_files[self.index]
        ftype = self.file_types[self.index]
        try:
            if ftype == 'tim':
                img = read_tim(path, self.palette_indices[self.index])
            else:
                img = Image.open(path).convert("RGBA")
        except Exception as e:
            self.preview_label.config(text=f"Failed to load: {e}", image="")
            self.status_label.config(text=f"Failed to load {os.path.basename(path)}")
            return

        zoom = max(1, int(self.zoom_level_var.get()))
        w,h = img.size
        zoomed = img.resize((w*zoom, h*zoom), Image.NEAREST)
        if zoomed.mode not in ("RGB","RGBA"):
            zoomed = zoomed.convert("RGBA")
        tkimg = ImageTk.PhotoImage(zoomed)
        self.preview_label.image = tkimg
        self.preview_label.config(image=tkimg, text="")
        self.status_label.config(text=f"{os.path.basename(path)}  —  {img.size[0]}x{img.size[1]} @ {zoom}x")
        self._update_inspector()
        self._update_palette_preview()

    def prev_image(self):
        if not self.tim_files:
            return
        self.index = (self.index - 1) % len(self.tim_files)
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(self.index)
        self.update_ui_for_selection()
        self.display_image()

    def next_image(self):
        if not self.tim_files:
            return
        self.index = (self.index + 1) % len(self.tim_files)
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(self.index)
        self.update_ui_for_selection()
        self.display_image()

    def _on_mouse_wheel(self, event):
        delta = 0
        if hasattr(event, "delta"):
            delta = 1 if event.delta > 0 else -1
        else:
            if event.num == 4:
                delta = 1
            elif event.num == 5:
                delta = -1
        cur = int(self.zoom_level_var.get())
        new = max(1, min(8, cur + delta))
        self.zoom_level_var.set(new)
        self.zoom_cb.set(new)
        self.display_image()

    def batch_convert(self):
        if not self.tim_files:
            messagebox.showinfo("Batch Convert", "No files loaded")
            return
        folder = filedialog.askdirectory(title="Select output folder")
        if not folder:
            return

        opts = BatchConvertDialog(self.root)
        self.root.wait_window(opts.top)
        if not opts.confirmed:
            return
        convert_tim_to_png = opts.to_png
        convert_tim_to_bmp = opts.to_bmp
        convert_to_tim = opts.to_tim

        count = 0
        for i, path in enumerate(self.tim_files):
            ft = self.file_types[i]
            base = os.path.splitext(os.path.basename(path))[0]
            try:
                if ft == 'tim':
                    img = read_tim(path, self.palette_indices[i])
                    if convert_tim_to_png:
                        img.save(os.path.join(folder, base + ".png"))
                        count += 1
                    if convert_tim_to_bmp:
                        img.save(os.path.join(folder, base + ".bmp"))
                        count += 1
                else:
                    if convert_to_tim:
                        img = Image.open(path).convert('P', palette=Image.ADAPTIVE, colors=16)
                        tim_bytes = image_to_tim(img, bpp=4)
                        with open(os.path.join(folder, base + ".tim"), "wb") as f:
                            f.write(tim_bytes)
                        count += 1
            except Exception as e:
                print("Batch conversion error:", path, e)

        messagebox.showinfo("Batch Convert", f"Done — {count} files saved to: {folder}")

    def _on_dnd(self, event):
        data = event.data
        paths = []
        cur = ""
        in_brace = False
        for ch in data:
            if ch == '{':
                in_brace = True
                cur = ""
            elif ch == '}':
                in_brace = False
                if cur:
                    paths.append(cur)
                cur = ""
            elif ch == ' ' and not in_brace:
                if cur:
                    paths.append(cur)
                cur = ""
            else:
                cur += ch
        if cur:
            paths.append(cur)
        self._add_paths(paths)

class BatchConvertDialog:
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("Batch Conversion Options")
        self.to_png = tk.BooleanVar(value=True)
        self.to_bmp = tk.BooleanVar(value=False)
        self.to_tim = tk.BooleanVar(value=False)
        ttk.Label(self.top, text="Choose conversions to perform:").pack(padx=12, pady=(10,6))
        ttk.Checkbutton(self.top, text="TIM -> PNG", variable=self.to_png).pack(anchor="w", padx=12)
        ttk.Checkbutton(self.top, text="TIM -> BMP", variable=self.to_bmp).pack(anchor="w", padx=12)
        ttk.Checkbutton(self.top, text="PNG/BMP -> TIM", variable=self.to_tim).pack(anchor="w", padx=12)
        btns = ttk.Frame(self.top)
        btns.pack(pady=10)
        ttk.Button(btns, text="Start", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="left", padx=6)
        self.confirmed = False
        self.top.transient(parent)
        self.top.grab_set()
        self.top.protocol("WM_DELETE_WINDOW", self._cancel)

    def _ok(self):
        self.confirmed = True
        self.top.destroy()

    def _cancel(self):
        self.confirmed = False
        self.top.destroy()

def _rgb_to_hex(rgb_tuple):
    return "#%02x%02x%02x" % tuple(int(max(0,min(255,v))) for v in rgb_tuple[:3])

def main():
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    app = TIMViewerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
