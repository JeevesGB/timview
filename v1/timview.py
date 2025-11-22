import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import numpy as np

##########################
#### WORK IN PROGRESS ####
##########################

def read_tim(filepath, palette_index=0):
    with open(filepath, 'rb') as f:
        if struct.unpack("<I", f.read(4))[0] != 0x10:
            raise ValueError("Not a TIM file")

        flags = struct.unpack("<I", f.read(4))[0]
        has_clut = flags & 0x08
        bpp_mode = flags & 0x07

        bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(bpp_mode, None)
        if bpp is None:
            raise ValueError("Unsupported BPP")

        clut = None
        if has_clut:
            clut_size = struct.unpack("<I", f.read(4))[0]
            clut_x, clut_y, clut_w, clut_h = struct.unpack("<4H", f.read(8))
            clut_data = f.read(clut_size - 12)
            clut_colors = np.frombuffer(clut_data, dtype=np.uint16)
            clut = clut_colors.reshape((-1, clut_w))
            if palette_index >= len(clut):
                palette_index = 0  # fallback to first palette
            selected_palette = clut[palette_index]
        else:
            selected_palette = None

        image_size = struct.unpack("<I", f.read(4))[0]
        x, y, w_words, h = struct.unpack("<4H", f.read(8))

        # Convert width from words to pixels
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
                pixels_unpack[i] = byte & 0x0F if i % 2 == 0 else (byte >> 4) & 0x0F
            pixels = pixels_unpack.reshape((h, w))
            color_vals = selected_palette[pixels]

        elif bpp == 8:
            pixels = np.frombuffer(raw_data[:w * h], dtype=np.uint8).reshape((h, w))
            color_vals = selected_palette[pixels]

        elif bpp == 16:
            img_array = np.frombuffer(raw_data, dtype=np.uint16).reshape((h, w))
            r = (img_array & 0x1F) << 3
            g = ((img_array >> 5) & 0x1F) << 3
            b = ((img_array >> 10) & 0x1F) << 3
            return Image.merge("RGB", [Image.fromarray(r.astype(np.uint8)),
                                       Image.fromarray(g.astype(np.uint8)),
                                       Image.fromarray(b.astype(np.uint8))])

        elif bpp == 24:
            return Image.frombytes("RGB", (w, h), raw_data[:w * h * 3], "raw", "RGB")

        else:
            raise NotImplementedError("Unsupported BPP")

        r = (color_vals & 0x1F) << 3
        g = ((color_vals >> 5) & 0x1F) << 3
        b = ((color_vals >> 10) & 0x1F) << 3
        return Image.merge("RGB", [Image.fromarray(r.astype(np.uint8)),
                                   Image.fromarray(g.astype(np.uint8)),
                                   Image.fromarray(b.astype(np.uint8))])


def image_to_tim(image: Image.Image, bpp=8):


    if image.mode != 'P':
        image = image.convert('P', palette=Image.ADAPTIVE, colors=16 if bpp == 4 else 256)

    palette = image.getpalette()
    if palette is None:
        raise ValueError("Image has no palette")

    width, height = image.size
    pixels = np.array(image)



    clut_colors = []
    for i in range(0, len(palette), 3):
        r = palette[i] >> 3
        g = palette[i+1] >> 3
        b = palette[i+2] >> 3
        color_16 = (b << 10) | (g << 5) | r
        clut_colors.append(color_16)

    unique_colors = np.unique(pixels)
    clut_array = np.array([clut_colors[c] for c in unique_colors], dtype=np.uint16)


    clut_array = np.array(clut_colors[:16 if bpp == 4 else 256], dtype=np.uint16)
    clut_w = 16 if bpp == 4 else 256
    clut_h = 1


    clut_data = clut_array.tobytes()


    flags = 0x08  # has CLUT
    flags |= 0 if bpp == 4 else 1 if bpp == 8 else 0


    header = struct.pack("<I", 0x10)  # magic
    flags_val = 0
    if bpp == 4:
        flags_val = 0  # 4bpp
    elif bpp == 8:
        flags_val = 1  # 8bpp
    else:
        raise NotImplementedError("Only 4bpp and 8bpp supported for writing TIM")

    flags_val |= 0x08  # CLUT flag

    header += struct.pack("<I", flags_val)


    clut_block_size = 12 + len(clut_data)


    header += struct.pack("<I", clut_block_size)
    header += struct.pack("<4H", 0, 0, clut_w, clut_h)
    header += clut_data



    if bpp == 4:
        w_words = width // 4
    else:
        w_words = width // 2


    if bpp == 4:
        flat_pixels = pixels.flatten()
        flat_pixels = np.clip(flat_pixels, 0, 15)
        packed_pixels = bytearray()
        for i in range(0, len(flat_pixels), 2):
            first = flat_pixels[i]
            second = flat_pixels[i+1] if i+1 < len(flat_pixels) else 0
            packed_pixels.append((second << 4) | first)
        pixel_bytes = bytes(packed_pixels)
    else:

        pixel_bytes = pixels.tobytes()

    img_block_size = 12 + len(pixel_bytes)
    header += struct.pack("<I", img_block_size)
    header += struct.pack("<4H", 0, 0, w_words, height)
    header += pixel_bytes

    return header

class TIMViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TIM View")
        self.geometry("1000x860")

        self.tim_files = []
        self.images = []
        self.tk_images_cache = []
        self.palettes = []
        self.palette_indices = []
        self.zoom_levels = []
        self.bpp_modes = []
        self.file_types = []

        self.index = 0


        self.img_label = tk.Label(self)
        self.img_label.pack(pady=10)
        self.img_label.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows
        self.img_label.bind("<Button-4>", self.on_mouse_wheel)    # Linux scroll up
        self.img_label.bind("<Button-5>", self.on_mouse_wheel)    # Linux scroll down


        self.status_label = tk.Label(self, text="")
        self.status_label.pack()


        ctrl_frame = tk.Frame(self)
        ctrl_frame.pack(pady=5)

        tk.Button(ctrl_frame, text="<< Prev", command=self.prev_image).pack(side=tk.LEFT, padx=5)
        tk.Button(ctrl_frame, text="Next >>", command=self.next_image).pack(side=tk.LEFT, padx=5)

        zoom_frame = tk.Frame(self)
        zoom_frame.pack(pady=5)
        tk.Label(zoom_frame, text="Zoom:").pack(side=tk.LEFT)
        self.zoom_level = tk.IntVar(value=4)
        self.zoom_slider = tk.Scale(zoom_frame, from_=1, to=8, orient=tk.HORIZONTAL,
                                    variable=self.zoom_level, command=lambda e: self.display_image())
        self.zoom_slider.pack(side=tk.LEFT)

        palette_frame = tk.Frame(self)
        palette_frame.pack(pady=5)
        tk.Label(palette_frame, text="Palette:").pack(side=tk.LEFT)
        self.palette_cb = ttk.Combobox(palette_frame, state="readonly")
        self.palette_cb.pack(side=tk.LEFT)
        self.palette_cb.bind("<<ComboboxSelected>>", self.on_palette_change)

        self.debug_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Show Debug Info", variable=self.debug_var, command=self.display_image).pack(pady=5)


        options_frame = tk.Frame(self)
        options_frame.pack(pady=5)

        self.convert_png_var = tk.BooleanVar(value=True)
        self.convert_bmp_var = tk.BooleanVar(value=True)
        self.convert_to_tim_var = tk.BooleanVar(value=False)

        tk.Checkbutton(options_frame, text="Convert to PNG", variable=self.convert_png_var).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(options_frame, text="Convert to BMP", variable=self.convert_bmp_var).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(options_frame, text="Convert PNG/BMP to TIM", variable=self.convert_to_tim_var).pack(side=tk.LEFT, padx=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Select Folder", command=self.select_folder).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Batch Convert", command=self.batch_convert).pack(side=tk.LEFT, padx=10)


        self.bind("<Left>", lambda e: self.prev_image())
        self.bind("<Right>", lambda e: self.next_image())

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        all_files = [os.path.join(folder, f) for f in os.listdir(folder)]
        self.tim_files.clear()
        self.images.clear()
        self.tk_images_cache.clear()
        self.palettes.clear()
        self.palette_indices.clear()
        self.zoom_levels.clear()
        self.bpp_modes.clear()
        self.file_types.clear()


        for path in all_files:
            ext = os.path.splitext(path)[1].lower()
            if ext == '.tim':

                try:
                    with open(path, "rb") as f:
                        if struct.unpack("<I", f.read(4))[0] == 0x10:
                            self.tim_files.append(path)
                            self.file_types.append('tim')  # <-- NEW
                except Exception:
                    continue
            elif ext in ['.png', '.bmp']:
                self.tim_files.append(path)
                self.file_types.append(ext[1:])  # 'png' or 'bmp'

        if not self.tim_files:
            messagebox.showinfo("No Valid Files", "No valid TIM, PNG, or BMP files found.")
            return


        for i, path in enumerate(self.tim_files):
            ft = self.file_types[i]
            if ft == 'tim':
                try:
                    with open(path, 'rb') as f:
                        f.seek(4)
                        flags = struct.unpack("<I", f.read(4))[0]
                        has_clut = flags & 0x08
                        bpp_mode = flags & 0x07
                        bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(bpp_mode, None)

                        if has_clut:
                            f.seek(12)
                            clut_size = struct.unpack("<I", f.read(4))[0]
                            clut_x, clut_y, clut_w, clut_h = struct.unpack("<4H", f.read(8))
                            palettes_count = clut_h
                        else:
                            palettes_count = 1

                        self.palettes.append(palettes_count)
                        self.palette_indices.append(0)
                        self.bpp_modes.append(bpp)
                        self.zoom_levels.append(4)
                except Exception as e:
                    self.palettes.append(1)
                    self.palette_indices.append(0)
                    self.bpp_modes.append(4)
                    self.zoom_levels.append(4)
            else:
                # For PNG/BMP, no palettes, bpp = 24
                self.palettes.append(1)
                self.palette_indices.append(0)
                self.bpp_modes.append(24)
                self.zoom_levels.append(4)

        self.index = 0
        self.display_image()
        self.update_palette_combobox()

    def update_palette_combobox(self):
        palettes = self.palettes[self.index]
        if palettes > 1:
            self.palette_cb.config(values=list(range(palettes)), state="readonly")
            self.palette_cb.current(self.palette_indices[self.index])
            self.palette_cb.pack(side=tk.LEFT)
        else:
            self.palette_cb.set("")
            self.palette_cb.pack_forget()

    def on_palette_change(self, event):
        selected = self.palette_cb.current()
        self.palette_indices[self.index] = selected
        self.display_image()

    def load_image(self, idx):
        path = self.tim_files[idx]
        ft = self.file_types[idx]

        if ft == 'tim':
            try:
                img = read_tim(path, self.palette_indices[idx])
                return img
            except Exception as e:
                print(f"Error loading TIM file: {path} {e}")
                return None
        elif ft in ['png', 'bmp']:
            try:
                img = Image.open(path).convert("RGBA")
                return img
            except Exception as e:
                print(f"Error loading image file: {path} {e}")
                return None
        else:
            return None

    def display_image(self):
        img = self.load_image(self.index)
        if img is None:
            self.img_label.config(image='', text="Failed to load image")
            return

        zoom = self.zoom_level.get()
        w, h = img.size
        img = img.resize((w * zoom, h * zoom), Image.NEAREST)

        if self.debug_var.get():
            debug_text = f"{self.index + 1}/{len(self.tim_files)} | {os.path.basename(self.tim_files[self.index])} | Zoom: {zoom}x | Palette: {self.palette_indices[self.index]}"
            self.status_label.config(text=debug_text)
        else:
            self.status_label.config(text=os.path.basename(self.tim_files[self.index]))

        tk_img = ImageTk.PhotoImage(img)
        self.tk_images_cache = [tk_img]  # prevent GC
        self.img_label.config(image=tk_img)

    def prev_image(self):
        if not self.tim_files:
            return
        self.index = (self.index - 1) % len(self.tim_files)
        self.update_palette_combobox()
        self.display_image()

    def next_image(self):
        if not self.tim_files:
            return
        self.index = (self.index + 1) % len(self.tim_files)
        self.update_palette_combobox()
        self.display_image()

    def on_mouse_wheel(self, event):
        delta = 0
        if event.num == 5 or event.delta < 0:
            delta = -1
        elif event.num == 4 or event.delta > 0:
            delta = 1
        current = self.zoom_level.get()
        new_val = max(1, min(8, current + delta))
        self.zoom_level.set(new_val)
        self.display_image()

    def batch_convert(self):
        if not self.tim_files:
            messagebox.showinfo("No files", "No files loaded.")
            return

        folder = filedialog.askdirectory()
        if not folder:
            return

        save_folder = folder

        if self.convert_to_tim_var.get():
            save_folder = os.path.join(folder, "Converted to TIM")
            os.makedirs(save_folder, exist_ok=True)

        count = 0
        for i, path in enumerate(self.tim_files):
            ft = self.file_types[i]
            filename = os.path.splitext(os.path.basename(path))[0]

            try:
                if ft == 'tim':
                    if self.convert_png_var.get():
                        img = read_tim(path, self.palette_indices[i])
                        save_path = os.path.join(save_folder, f"{filename}.png")
                        img.save(save_path)
                        count += 1
                    if self.convert_bmp_var.get():
                        img = read_tim(path, self.palette_indices[i])
                        save_path = os.path.join(save_folder, f"{filename}.bmp")
                        img.save(save_path)
                        count += 1
                elif ft in ['png', 'bmp']:
                    if self.convert_to_tim_var.get():
                        # Load image and convert to TIM bytes
                        img = Image.open(path).convert('RGBA')
                        # Convert to 'P' mode for indexed palette, default 8bpp
                        img_p = img.convert('P', palette=Image.ADAPTIVE, colors=16)
                        tim_bytes = image_to_tim(img_p, bpp=4)

                        save_path = os.path.join(save_folder, f"{filename}.tim")
                        with open(save_path, "wb") as f:
                            f.write(tim_bytes)
                        count += 1
            except Exception as e:
                print(f"Error converting {path}: {e}")

        messagebox.showinfo("Batch Conversion", f"Conversion complete! {count} files saved.")

if __name__ == "__main__":
    app = TIMViewer()
    app.mainloop()
