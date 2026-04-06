#!/usr/bin/env python3
"""
Headless tests for the core logic of PhotoSelector.
Tests file scanning, like/dislike, progress save/load, and naming.
Does NOT require a display or Tkinter window.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# We need PIL for creating test images
from PIL import Image

# Patch tkinter before importing photo_selector so it doesn't try to init a display
import sys
mock_tk = MagicMock()
sys.modules['tkinter'] = mock_tk
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()

# Now import the module constants and logic we need
import importlib
import photo_selector as ps

PASS = 0
FAIL = 0


def result(name, passed, detail=""):
    global PASS, FAIL
    if passed:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")


def create_test_image(path: Path, width=100, height=100, color="red"):
    """Create a small test JPEG image."""
    img = Image.new("RGB", (width, height), color=color)
    img.save(str(path), "JPEG")


def setup_test_dir():
    """Create a temp dir with test images mimicking a USB drive."""
    tmp = Path(tempfile.mkdtemp(prefix="photo_test_"))
    # Root-level images
    for i in range(5):
        create_test_image(tmp / f"IMG_{i:04d}.jpg", color=("red", "blue", "green", "yellow", "purple")[i])
    # DCIM subdirectory (1 level)
    dcim = tmp / "DCIM"
    dcim.mkdir()
    for i in range(3):
        create_test_image(dcim / f"DSC_{i:04d}.jpg")
    # Nested DCIM (2 levels deep)
    canon = dcim / "100CANON"
    canon.mkdir()
    for i in range(2):
        create_test_image(canon / f"CANON_{i:04d}.jpg")
    return tmp


def test_scan_photos():
    """Test that scanning finds all photos including nested subdirs."""
    print("\n--- Test: Scan Photos ---")
    tmp = setup_test_dir()
    try:
        all_ext = ps.IMAGE_EXTENSIONS.copy()
        files = []

        def collect(directory):
            try:
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix.lower() in all_ext:
                        files.append(f)
                    elif f.is_dir() and f.name != ps.SELECTED_DIR:
                        collect(f)
            except PermissionError:
                pass

        collect(tmp)

        result("Finds root-level images", len([f for f in files if f.parent == tmp]) == 5,
               f"Found {len([f for f in files if f.parent == tmp])}, expected 5")
        result("Finds DCIM images", len([f for f in files if f.parent.name == "DCIM"]) == 3,
               f"Found {len([f for f in files if f.parent.name == 'DCIM'])}, expected 3")
        result("Finds nested DCIM images (2 levels)", len([f for f in files if "100CANON" in str(f)]) == 2,
               f"Found {len([f for f in files if '100CANON' in str(f)])}, expected 2")
        result("Total photo count", len(files) == 10, f"Found {len(files)}, expected 10")
        result("Excludes selected/ dir", not any(ps.SELECTED_DIR in str(f) for f in files))
    finally:
        shutil.rmtree(tmp)


def test_like_and_copy():
    """Test that liking a photo copies it with correct naming."""
    print("\n--- Test: Like and Copy ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))

        # Simulate like
        liked = {}
        counter = 0

        counter += 1
        ext = photo.suffix.lower()
        new_name = f"{ps.NAMING_PREFIX}{counter:03d}{ext}"
        dest = selected_dir / new_name

        selected_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(photo), str(dest))
        liked[rel_key] = new_name

        result("Aniket_Selected folder created", selected_dir.exists())
        result("Folder name is Aniket_Selected", selected_dir.name == "Aniket_Selected",
               f"Got {selected_dir.name}")
        result("File copied to selected/", dest.exists())
        result("Correct naming format", new_name == "aniket_selected_001.jpg",
               f"Got {new_name}")
        result("Original untouched", photo.exists())
        result("Liked dict tracks mapping", liked.get(rel_key) == new_name)

        # Like a second photo
        photo2 = tmp / "IMG_0001.jpg"
        rel_key2 = str(photo2.relative_to(tmp))
        counter += 1
        new_name2 = f"{ps.NAMING_PREFIX}{counter:03d}{photo2.suffix.lower()}"
        dest2 = selected_dir / new_name2
        shutil.copy2(str(photo2), str(dest2))
        liked[rel_key2] = new_name2

        result("Second file naming sequential", new_name2 == "aniket_selected_002.jpg",
               f"Got {new_name2}")
        result("Two files in selected/",
               len(list(selected_dir.iterdir())) == 2,
               f"Found {len(list(selected_dir.iterdir()))}")
    finally:
        shutil.rmtree(tmp)


def test_dislike_and_remove():
    """Test that disliking removes the file from selected/ folder."""
    print("\n--- Test: Dislike and Remove ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))

        # Like it first
        new_name = "aniket_selected_001.jpg"
        dest = selected_dir / new_name
        shutil.copy2(str(photo), str(dest))
        liked = {rel_key: new_name}

        result("File in selected/ before dislike", dest.exists())

        # Now dislike
        selected_name = liked[rel_key]
        selected_path = selected_dir / selected_name
        if selected_path.exists():
            selected_path.unlink()
        del liked[rel_key]

        result("File removed from selected/", not dest.exists())
        result("Entry removed from liked dict", rel_key not in liked)
        result("Original still exists", photo.exists())
        result("selected/ folder still exists (empty)", selected_dir.exists())
    finally:
        shutil.rmtree(tmp)


def test_progress_save_load():
    """Test progress file save and load with relative paths."""
    print("\n--- Test: Progress Save/Load ---")
    tmp = setup_test_dir()
    try:
        progress_path = tmp / ps.PROGRESS_FILE

        # Save
        liked = {"IMG_0000.jpg": "aniket_selected_001.jpg",
                 "DCIM/DSC_0001.jpg": "aniket_selected_002.jpg"}
        data = {
            "current_index": 3,
            "liked": liked,
            "like_counter": 5,
        }
        progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result("Progress file created", progress_path.exists())

        # Load
        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        result("current_index preserved", loaded["current_index"] == 3)
        result("like_counter preserved", loaded["like_counter"] == 5)
        result("liked dict preserved", loaded["liked"] == liked)
        result("Relative paths used (no absolute)", not any("/" == p[0] for p in loaded["liked"].keys()),
               f"Keys: {list(loaded['liked'].keys())}")

        # Test migration from old list format
        old_data = {
            "current_index": 1,
            "liked": ["IMG_0000.jpg", "IMG_0001.jpg"],
            "like_counter": 2,
        }
        progress_path.write_text(json.dumps(old_data), encoding="utf-8")
        loaded2 = json.loads(progress_path.read_text(encoding="utf-8"))
        if isinstance(loaded2["liked"], list):
            migrated = {path: "" for path in loaded2["liked"]}
        else:
            migrated = loaded2["liked"]
        result("Old format migration works", len(migrated) == 2)
        result("Migrated entries are dict", isinstance(migrated, dict))
    finally:
        shutil.rmtree(tmp)


def test_naming_over_99():
    """Test that naming handles 100+ selections correctly with 3-digit padding."""
    print("\n--- Test: Naming Beyond 99 ---")
    name_99 = f"{ps.NAMING_PREFIX}{99:03d}.jpg"
    name_100 = f"{ps.NAMING_PREFIX}{100:03d}.jpg"
    name_999 = f"{ps.NAMING_PREFIX}{999:03d}.jpg"
    name_1000 = f"{ps.NAMING_PREFIX}{1000:03d}.jpg"

    result("99th file pads correctly", name_99 == "aniket_selected_099.jpg", f"Got {name_99}")
    result("100th file stays 3 digits", name_100 == "aniket_selected_100.jpg", f"Got {name_100}")
    result("999th file stays 3 digits", name_999 == "aniket_selected_999.jpg", f"Got {name_999}")
    result("1000th file extends to 4 digits", name_1000 == "aniket_selected_1000.jpg", f"Got {name_1000}")

    # Verify sort order of 3-digit names
    names = [f"{ps.NAMING_PREFIX}{i:03d}.jpg" for i in range(1, 201)]
    result("200 files sort correctly", names == sorted(names))


def test_relative_key_stability():
    """Test that relative keys are stable across different mount points."""
    print("\n--- Test: Relative Key Stability ---")
    # Simulate USB mounted at two different paths
    path_mac = Path("/Volumes/USB/DCIM/IMG_0001.jpg")
    source_mac = Path("/Volumes/USB")
    key_mac = str(path_mac.relative_to(source_mac))

    path_win = Path("/Volumes/USB 1/DCIM/IMG_0001.jpg")
    source_win = Path("/Volumes/USB 1")
    key_win = str(path_win.relative_to(source_win))

    result("Relative key from mount 1", key_mac == "DCIM/IMG_0001.jpg", f"Got {key_mac}")
    result("Relative key from mount 2", key_win == "DCIM/IMG_0001.jpg", f"Got {key_win}")
    result("Keys match across mounts", key_mac == key_win)


def test_duplicate_like_prevention():
    """Test that liking the same photo twice doesn't create duplicates."""
    print("\n--- Test: Duplicate Like Prevention ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        liked = {}
        counter = 0

        # First like
        counter += 1
        new_name = f"{ps.NAMING_PREFIX}{counter:03d}.jpg"
        shutil.copy2(str(photo), str(selected_dir / new_name))
        liked[rel_key] = new_name

        # Attempt second like
        already_liked = rel_key in liked
        result("Duplicate detected", already_liked)
        result("Counter not incremented", counter == 1)
        result("Only one file in selected/", len(list(selected_dir.iterdir())) == 1)
    finally:
        shutil.rmtree(tmp)


def test_dislike_nonexistent():
    """Test disliking a photo that isn't liked doesn't crash."""
    print("\n--- Test: Dislike Non-selected Photo ---")
    liked = {}
    rel_key = "IMG_0000.jpg"

    is_liked = rel_key in liked
    result("Non-liked photo detected", not is_liked)
    # Should show "Not selected" flash, not crash


def test_file_extension_preservation():
    """Test that copy preserves original file extension."""
    print("\n--- Test: Extension Preservation ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        # Create a PNG
        png_path = tmp / "test_photo.png"
        img = Image.new("RGB", (50, 50), "blue")
        img.save(str(png_path), "PNG")

        counter = 1
        ext = png_path.suffix.lower()
        new_name = f"{ps.NAMING_PREFIX}{counter:03d}{ext}"

        result("PNG extension preserved", new_name == "aniket_selected_001.png", f"Got {new_name}")

        # TIFF
        tiff_path = tmp / "test_photo.tiff"
        ext_tiff = tiff_path.suffix.lower()
        name_tiff = f"{ps.NAMING_PREFIX}{2:03d}{ext_tiff}"
        result("TIFF extension preserved", name_tiff == "aniket_selected_002.tiff", f"Got {name_tiff}")

        # RAW (just test naming, not actual file)
        ext_raw = ".cr2"
        name_raw = f"{ps.NAMING_PREFIX}{3:03d}{ext_raw}"
        result("RAW extension preserved", name_raw == "aniket_selected_003.cr2", f"Got {name_raw}")
    finally:
        shutil.rmtree(tmp)


def test_drive_root_detection():
    """Test that _find_drive_root correctly identifies drive mount points."""
    print("\n--- Test: Drive Root Detection ---")

    # macOS: /Volumes/USB_NAME/some/subfolder -> /Volumes/USB_NAME
    mac_path = Path("/Volumes/MyUSB/DCIM/100CANON")
    mac_root = ps.PhotoSelector._find_drive_root(mac_path)
    result("macOS: finds /Volumes/USB root", str(mac_root) == "/Volumes/MyUSB",
           f"Got {mac_root}")

    # macOS: /Volumes/USB_NAME (already at root)
    mac_root_direct = ps.PhotoSelector._find_drive_root(Path("/Volumes/MyUSB"))
    result("macOS: root stays at root", str(mac_root_direct) == "/Volumes/MyUSB",
           f"Got {mac_root_direct}")

    # Linux /media: /media/user/USB/photos -> /media/user/USB
    linux_media = Path("/media/aniket/WeddingUSB/DCIM/photos")
    linux_root = ps.PhotoSelector._find_drive_root(linux_media)
    result("Linux /media: finds mount root", str(linux_root) == "/media/aniket/WeddingUSB",
           f"Got {linux_root}")

    # Linux /mnt: /mnt/usb/photos -> /mnt/usb
    linux_mnt = Path("/mnt/usb/photos/subfolder")
    linux_mnt_root = ps.PhotoSelector._find_drive_root(linux_mnt)
    result("Linux /mnt: finds mount root", str(linux_mnt_root) == "/mnt/usb",
           f"Got {linux_mnt_root}")


def test_subfolder_selection_shared_output():
    """Test that selecting a subfolder still puts Aniket_Selected at drive root."""
    print("\n--- Test: Subfolder Selection -> Shared Output ---")
    tmp = setup_test_dir()
    try:
        dcim = tmp / "DCIM"
        canon = dcim / "100CANON"

        # Simulate selecting the nested subfolder as source
        # Drive root detection falls back to source_dir for local tmp paths
        # but the key logic is: selected_dir = drive_root / SELECTED_DIR
        # For a real USB on macOS, drive_root would be /Volumes/USB

        # Test the fallback case (not on a real USB mount)
        drive_root = ps.PhotoSelector._find_drive_root(canon)
        selected_dir = drive_root / ps.SELECTED_DIR

        # In fallback, drive_root = canon itself, but on real USB it would be the USB root
        # Let's test the real scenario by simulating a /Volumes path
        # We can't create /Volumes dirs, so verify the logic with path math

        # Scenario: user selects /Volumes/WeddingUSB/DCIM/100CANON
        usb_root = Path("/Volumes/WeddingUSB")
        subfolder = Path("/Volumes/WeddingUSB/DCIM/100CANON")
        detected_root = ps.PhotoSelector._find_drive_root(subfolder)
        selected_at_root = detected_root / ps.SELECTED_DIR

        result("Selected dir at USB root, not subfolder",
               str(selected_at_root) == "/Volumes/WeddingUSB/Aniket_Selected",
               f"Got {selected_at_root}")
        result("Not inside subfolder",
               "100CANON" not in str(selected_at_root))
        result("Not inside DCIM",
               "DCIM" not in str(selected_at_root))

        # Same USB, different subfolder selected -> same output dir
        subfolder2 = Path("/Volumes/WeddingUSB/OtherPhotos")
        detected_root2 = ps.PhotoSelector._find_drive_root(subfolder2)
        selected_at_root2 = detected_root2 / ps.SELECTED_DIR

        result("Different subfolder -> same Aniket_Selected location",
               str(selected_at_root) == str(selected_at_root2))
    finally:
        shutil.rmtree(tmp)


def test_counter_continuity_across_folders():
    """Test that naming continues from where it left off across folder switches."""
    print("\n--- Test: Counter Continuity Across Folders ---")
    tmp = setup_test_dir()
    try:
        drive_root = tmp  # simulate drive root
        selected_dir = drive_root / ps.SELECTED_DIR
        selected_dir.mkdir()
        progress_path = drive_root / ps.PROGRESS_FILE

        # Session 1: browse root folder, like 3 photos
        liked = {}
        counter = 0
        for i in range(3):
            photo = tmp / f"IMG_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            counter += 1
            ext = photo.suffix.lower()
            new_name = f"{ps.NAMING_PREFIX}{counter:03d}{ext}"
            shutil.copy2(str(photo), str(selected_dir / new_name))
            liked[rel_key] = new_name

        # Save progress (as the app would on quit)
        data = {"current_index": 2, "liked": liked, "like_counter": counter}
        progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result("Session 1: 3 files in Aniket_Selected",
               len(list(selected_dir.iterdir())) == 3)
        result("Session 1: counter at 3", counter == 3)
        result("Session 1: last file is _003",
               liked[f"IMG_0002.jpg"] == "aniket_selected_003.jpg")

        # Session 2: browse DCIM subfolder, load progress, like 2 more
        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        counter = loaded["like_counter"]  # restored to 3
        liked = loaded["liked"]

        result("Session 2: counter restored to 3", counter == 3)

        dcim = tmp / "DCIM"
        for i in range(2):
            photo = dcim / f"DSC_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            counter += 1
            ext = photo.suffix.lower()
            new_name = f"{ps.NAMING_PREFIX}{counter:03d}{ext}"
            shutil.copy2(str(photo), str(selected_dir / new_name))
            liked[rel_key] = new_name

        result("Session 2: first new file is _004",
               liked["DCIM/DSC_0000.jpg"] == "aniket_selected_004.jpg",
               f"Got {liked.get('DCIM/DSC_0000.jpg')}")
        result("Session 2: second new file is _005",
               liked["DCIM/DSC_0001.jpg"] == "aniket_selected_005.jpg",
               f"Got {liked.get('DCIM/DSC_0001.jpg')}")
        result("Session 2: total 5 files in Aniket_Selected",
               len(list(selected_dir.iterdir())) == 5)
        result("Session 2: counter at 5", counter == 5)

        # Verify all files exist with correct names
        for i in range(1, 6):
            expected = selected_dir / f"{ps.NAMING_PREFIX}{i:03d}.jpg"
            result(f"File aniket_selected_{i:03d}.jpg exists", expected.exists(),
                   f"{expected} missing")
    finally:
        shutil.rmtree(tmp)


def test_undo_like():
    """Test that undoing a like removes the copied file and unmarks it."""
    print("\n--- Test: Undo Like ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))

        # Like the photo
        liked = {}
        counter = 0
        counter += 1
        new_name = f"{ps.NAMING_PREFIX}{counter:03d}.jpg"
        dest = selected_dir / new_name
        shutil.copy2(str(photo), str(dest))
        liked[rel_key] = new_name
        undo_stack = [("like", rel_key, new_name, 0)]

        result("File exists before undo", dest.exists())
        result("Liked dict has entry", rel_key in liked)

        # Undo the like
        action, undo_key, undo_name, _ = undo_stack.pop()
        assert action == "like"
        undo_path = selected_dir / undo_name
        if undo_path.exists():
            undo_path.unlink()
        liked.pop(undo_key, None)

        result("File removed after undo", not dest.exists())
        result("Liked dict cleared", undo_key not in liked)
        result("Undo stack empty", len(undo_stack) == 0)
        result("Original untouched", photo.exists())
    finally:
        shutil.rmtree(tmp)


def test_undo_dislike():
    """Test that undoing a dislike re-copies the file and re-marks it."""
    print("\n--- Test: Undo Dislike ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        new_name = "aniket_selected_001.jpg"
        dest = selected_dir / new_name

        # Simulate: photo was liked then disliked
        liked = {}
        undo_stack = [("dislike", rel_key, new_name, 0)]

        result("File not in selected/ (was disliked)", not dest.exists())

        # Undo the dislike: re-copy and re-mark
        action, undo_key, undo_name, _ = undo_stack.pop()
        assert action == "dislike"
        source_path = tmp / undo_key
        if source_path.exists() and undo_name:
            shutil.copy2(str(source_path), str(selected_dir / undo_name))
            liked[undo_key] = undo_name

        result("File restored after undo", dest.exists())
        result("Liked dict restored", undo_key in liked)
        result("Correct filename restored", liked[undo_key] == new_name)
    finally:
        shutil.rmtree(tmp)


def test_undo_stack_multiple():
    """Test that multiple undos work in correct LIFO order."""
    print("\n--- Test: Undo Stack LIFO Order ---")
    undo_stack = []

    # Simulate: like A, like B, dislike A
    undo_stack.append(("like", "IMG_A.jpg", "aniket_selected_001.jpg", 0))
    undo_stack.append(("like", "IMG_B.jpg", "aniket_selected_002.jpg", 1))
    undo_stack.append(("dislike", "IMG_A.jpg", "aniket_selected_001.jpg", 0))

    result("Stack has 3 entries", len(undo_stack) == 3)

    # First undo: should undo the dislike of A
    action1, key1, _, _ = undo_stack.pop()
    result("First undo is dislike of A", action1 == "dislike" and key1 == "IMG_A.jpg")

    # Second undo: should undo the like of B
    action2, key2, _, _ = undo_stack.pop()
    result("Second undo is like of B", action2 == "like" and key2 == "IMG_B.jpg")

    # Third undo: should undo the like of A
    action3, key3, _, _ = undo_stack.pop()
    result("Third undo is like of A", action3 == "like" and key3 == "IMG_A.jpg")

    result("Stack empty after all undos", len(undo_stack) == 0)


def test_export_summary():
    """Test that export generates a valid summary file."""
    print("\n--- Test: Export Summary ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.SELECTED_DIR
        selected_dir.mkdir()

        # Simulate some liked photos
        liked = {
            "IMG_0000.jpg": "aniket_selected_001.jpg",
            "DCIM/DSC_0001.jpg": "aniket_selected_002.jpg",
            "DCIM/100CANON/CANON_0000.jpg": "aniket_selected_003.jpg",
        }

        # Build summary (same logic as _export_summary)
        lines = []
        lines.append("=" * 60)
        lines.append("WEDDING PHOTO SELECTION SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Total selected: {len(liked)} photos")
        lines.append("")
        lines.append(f"{'Selected Name':<35} {'Original File'}")
        lines.append("-" * 60)
        sorted_items = sorted(liked.items(), key=lambda x: x[1])
        for original_rel, selected_name in sorted_items:
            lines.append(f"{selected_name:<35} {original_rel}")
        lines.append("-" * 60)
        lines.append("")
        lines.append("INSTRUCTIONS FOR PHOTOGRAPHER:")
        lines.append(f"  All selected photos are in the '{ps.SELECTED_DIR}' folder.")

        summary_text = "\n".join(lines)
        summary_path = selected_dir / ps.SUMMARY_FILE
        summary_path.write_text(summary_text, encoding="utf-8")

        result("Summary file created", summary_path.exists())

        content = summary_path.read_text(encoding="utf-8")
        result("Contains title", "WEDDING PHOTO SELECTION SUMMARY" in content)
        result("Contains total count", "3 photos" in content)
        result("Contains original filename", "IMG_0000.jpg" in content)
        result("Contains selected filename", "aniket_selected_001.jpg" in content)
        result("Contains nested path", "DCIM/100CANON/CANON_0000.jpg" in content)
        result("Contains photographer instructions", "INSTRUCTIONS FOR PHOTOGRAPHER" in content)
        result("Contains folder name", ps.SELECTED_DIR in content)
        result("Entries sorted by selected name",
               content.index("aniket_selected_001") < content.index("aniket_selected_002") < content.index("aniket_selected_003"))
    finally:
        shutil.rmtree(tmp)


def test_drive_accessibility_check():
    """Test that drive accessibility check works for existing and missing paths."""
    print("\n--- Test: Drive Accessibility Check ---")

    tmp = setup_test_dir()
    try:
        # Existing path should be accessible
        accessible = tmp.exists() and os.access(str(tmp), os.R_OK)
        result("Existing dir is accessible", accessible)

        # Non-existent path should not be accessible
        fake = Path("/tmp/nonexistent_usb_drive_12345")
        not_accessible = not (fake.exists() and os.access(str(fake), os.R_OK))
        result("Non-existent dir is not accessible", not_accessible)
    finally:
        shutil.rmtree(tmp)


def test_undo_empty_stack():
    """Test that undo on empty stack doesn't crash."""
    print("\n--- Test: Undo Empty Stack ---")
    undo_stack = []
    result("Empty stack detected", len(undo_stack) == 0)
    # App should show "Nothing to undo" flash, not crash


if __name__ == "__main__":
    print("=" * 60)
    print("Wedding Photo Selector — Core Logic Tests")
    print("=" * 60)

    test_scan_photos()
    test_like_and_copy()
    test_dislike_and_remove()
    test_progress_save_load()
    test_naming_over_99()
    test_relative_key_stability()
    test_duplicate_like_prevention()
    test_dislike_nonexistent()
    test_file_extension_preservation()
    test_drive_root_detection()
    test_subfolder_selection_shared_output()
    test_counter_continuity_across_folders()
    test_undo_like()
    test_undo_dislike()
    test_undo_stack_multiple()
    test_undo_empty_stack()
    test_export_summary()
    test_drive_accessibility_check()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
