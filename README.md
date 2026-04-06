# Wedding Photo Selector

A cross-platform desktop app to browse wedding photos from a USB drive, select your favourites, and automatically copy them with sequential naming into a `selected/` folder — ready to hand to your photographer for album printing.

## Features

- **Auto-slideshow** with adjustable speed
- **Manual navigation** with keyboard or buttons
- **One-key selection** — liked photos are copied (not moved) and renamed sequentially
- **RAW file support** — CR2, NEF, ARW, DNG, and 25+ other RAW formats
- **Resume support** — close and come back later, pick up where you left off
- **EXIF-aware** — auto-rotates photos based on EXIF orientation
- **Cross-platform** — works on macOS and Windows

## Installation

```bash
# Clone the repo
git clone https://github.com/aniketdharma/wedding-photo-selector.git
cd wedding-photo-selector

# Install dependencies
pip install -r requirements.txt
```

> **Note:** `rawpy` is optional. Without it, the app works with JPG/PNG/BMP/TIFF/WebP. With it, you also get RAW support.

## Usage

```bash
python photo_selector.py
```

A file dialog will open — select the folder (or USB drive) containing your wedding photos.

### Keyboard Controls

| Key | Action |
|-----|--------|
| `→` or `D` | Next photo |
| `←` or `A` | Previous photo |
| `Space` or `L` | Like photo (copy to selected/) |
| `P` | Play/Pause slideshow |
| `+` / `-` | Speed up / slow down slideshow |
| `F` or `F11` | Toggle fullscreen |
| `Q` or `Esc` | Quit |

### Output

Liked photos are copied to a `selected/` folder inside the same directory you chose:

```
USB Drive/
├── IMG_0001.jpg          # Originals (untouched)
├── IMG_0002.cr2
├── ...
├── selected/
│   ├── aniket_selected_01.jpg
│   ├── aniket_selected_02.cr2
│   └── ...
└── .photo_selector_progress.json   # Resume tracking
```

## Requirements

- Python 3.10+
- Pillow (required)
- rawpy (optional, for RAW file support)
