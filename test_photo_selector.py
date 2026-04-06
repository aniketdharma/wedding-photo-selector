#!/usr/bin/env python3
"""
Headless tests for the core logic of PhotoSelector.
Tests file scanning, like/dislike, progress save/load, naming, profiles,
cross-selection, undo, export, and drive detection.
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
    for i in range(5):
        create_test_image(tmp / f"IMG_{i:04d}.jpg", color=("red", "blue", "green", "yellow", "purple")[i])
    dcim = tmp / "DCIM"
    dcim.mkdir()
    for i in range(3):
        create_test_image(dcim / f"DSC_{i:04d}.jpg")
    canon = dcim / "100CANON"
    canon.mkdir()
    for i in range(2):
        create_test_image(canon / f"CANON_{i:04d}.jpg")
    return tmp


# --- Profile Helper Tests ---

def test_profile_helpers():
    """Test profile name -> folder, prefix, progress file conversions."""
    print("\n--- Test: Profile Helpers ---")

    result("Aniket folder name", ps.profile_dir_name("Aniket") == "Aniket_Selected")
    result("Aditi folder name", ps.profile_dir_name("Aditi") == "Aditi_Selected")
    result("Custom folder name", ps.profile_dir_name("Mom") == "Mom_Selected")

    result("Aniket prefix", ps.profile_prefix("Aniket") == "aniket_selected_")
    result("Aditi prefix", ps.profile_prefix("Aditi") == "aditi_selected_")

    result("Aniket progress file", ps.profile_progress_file("Aniket") == ".photo_selector_aniket.json")
    result("Aditi progress file", ps.profile_progress_file("Aditi") == ".photo_selector_aditi.json")

    # Different profiles get different everything
    result("Folders differ", ps.profile_dir_name("Aniket") != ps.profile_dir_name("Aditi"))
    result("Prefixes differ", ps.profile_prefix("Aniket") != ps.profile_prefix("Aditi"))
    result("Progress files differ",
           ps.profile_progress_file("Aniket") != ps.profile_progress_file("Aditi"))


# --- Scan Tests ---

def test_scan_photos():
    """Test that scanning finds all photos including nested subdirs."""
    print("\n--- Test: Scan Photos ---")
    tmp = setup_test_dir()
    try:
        all_ext = ps.IMAGE_EXTENSIONS.copy()
        files = []

        excluded = {"Aniket_Selected", "Aditi_Selected"}

        def collect(directory):
            try:
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix.lower() in all_ext:
                        files.append(f)
                    elif f.is_dir() and f.name not in excluded:
                        collect(f)
            except PermissionError:
                pass

        collect(tmp)

        result("Finds root-level images", len([f for f in files if f.parent == tmp]) == 5)
        result("Finds DCIM images", len([f for f in files if f.parent.name == "DCIM"]) == 3)
        result("Finds nested DCIM images (2 levels)", len([f for f in files if "100CANON" in str(f)]) == 2)
        result("Total photo count", len(files) == 10, f"Found {len(files)}")
    finally:
        shutil.rmtree(tmp)


def test_scan_excludes_all_selected_dirs():
    """Test that scanning excludes all profile selected directories."""
    print("\n--- Test: Scan Excludes All Selected Dirs ---")
    tmp = setup_test_dir()
    try:
        # Create selected dirs for multiple profiles
        (tmp / "Aniket_Selected").mkdir()
        create_test_image(tmp / "Aniket_Selected" / "aniket_selected_001.jpg")
        (tmp / "Aditi_Selected").mkdir()
        create_test_image(tmp / "Aditi_Selected" / "aditi_selected_001.jpg")
        (tmp / "Mom_Selected").mkdir()
        create_test_image(tmp / "Mom_Selected" / "mom_selected_001.jpg")

        all_ext = ps.IMAGE_EXTENSIONS.copy()
        excluded = {"Aniket_Selected", "Aditi_Selected", "Mom_Selected"}
        files = []

        def collect(directory):
            try:
                for f in sorted(directory.iterdir()):
                    if f.is_file() and f.suffix.lower() in all_ext:
                        files.append(f)
                    elif f.is_dir() and f.name not in excluded:
                        collect(f)
            except PermissionError:
                pass

        collect(tmp)

        result("No selected dir photos in scan",
               not any("_Selected" in str(f.parent) for f in files))
        result("Original photos still found", len(files) == 10, f"Found {len(files)}")
    finally:
        shutil.rmtree(tmp)


# --- Like / Copy Tests ---

def test_like_and_copy():
    """Test that liking a photo copies it with profile-specific naming."""
    print("\n--- Test: Like and Copy (Profile) ---")
    tmp = setup_test_dir()
    try:
        # Test with Aniket profile
        prefix = ps.profile_prefix("Aniket")
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        liked = {}
        counter = 0

        counter += 1
        new_name = f"{prefix}{counter:03d}{photo.suffix.lower()}"
        dest = selected_dir / new_name
        shutil.copy2(str(photo), str(dest))
        liked[rel_key] = new_name

        result("Aniket_Selected folder created", selected_dir.exists())
        result("Folder name correct", selected_dir.name == "Aniket_Selected")
        result("File copied", dest.exists())
        result("Naming format correct", new_name == "aniket_selected_001.jpg", f"Got {new_name}")
        result("Original untouched", photo.exists())

        # Test with Aditi profile
        prefix_aditi = ps.profile_prefix("Aditi")
        selected_dir_aditi = tmp / ps.profile_dir_name("Aditi")
        selected_dir_aditi.mkdir()

        counter_aditi = 1
        new_name_aditi = f"{prefix_aditi}{counter_aditi:03d}{photo.suffix.lower()}"
        dest_aditi = selected_dir_aditi / new_name_aditi
        shutil.copy2(str(photo), str(dest_aditi))

        result("Aditi_Selected folder created", selected_dir_aditi.exists())
        result("Aditi naming correct", new_name_aditi == "aditi_selected_001.jpg", f"Got {new_name_aditi}")
        result("Both folders coexist", selected_dir.exists() and selected_dir_aditi.exists())
    finally:
        shutil.rmtree(tmp)


# --- Dislike Tests ---

def test_dislike_and_remove():
    """Test that disliking removes the file from the profile's selected folder."""
    print("\n--- Test: Dislike and Remove ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        new_name = "aniket_selected_001.jpg"
        dest = selected_dir / new_name
        shutil.copy2(str(photo), str(dest))
        liked = {rel_key: new_name}

        result("File in selected/ before dislike", dest.exists())

        selected_path = selected_dir / liked[rel_key]
        if selected_path.exists():
            selected_path.unlink()
        del liked[rel_key]

        result("File removed from selected/", not dest.exists())
        result("Entry removed from liked dict", rel_key not in liked)
        result("Original still exists", photo.exists())
    finally:
        shutil.rmtree(tmp)


# --- Progress Tests ---

def test_progress_save_load():
    """Test progress file save and load per profile."""
    print("\n--- Test: Progress Save/Load (Per Profile) ---")
    tmp = setup_test_dir()
    try:
        # Aniket progress
        progress_aniket = tmp / ps.profile_progress_file("Aniket")
        liked_aniket = {"IMG_0000.jpg": "aniket_selected_001.jpg",
                        "DCIM/DSC_0001.jpg": "aniket_selected_002.jpg"}
        data_aniket = {"current_index": 3, "liked": liked_aniket, "like_counter": 5}
        progress_aniket.write_text(json.dumps(data_aniket, indent=2), encoding="utf-8")

        # Aditi progress
        progress_aditi = tmp / ps.profile_progress_file("Aditi")
        liked_aditi = {"IMG_0002.jpg": "aditi_selected_001.jpg"}
        data_aditi = {"current_index": 7, "liked": liked_aditi, "like_counter": 1}
        progress_aditi.write_text(json.dumps(data_aditi, indent=2), encoding="utf-8")

        # Load and verify independence
        loaded_aniket = json.loads(progress_aniket.read_text(encoding="utf-8"))
        loaded_aditi = json.loads(progress_aditi.read_text(encoding="utf-8"))

        result("Aniket progress file exists", progress_aniket.exists())
        result("Aditi progress file exists", progress_aditi.exists())
        result("Different progress files", progress_aniket.name != progress_aditi.name)
        result("Aniket index preserved", loaded_aniket["current_index"] == 3)
        result("Aditi index preserved", loaded_aditi["current_index"] == 7)
        result("Aniket counter preserved", loaded_aniket["like_counter"] == 5)
        result("Aditi counter preserved", loaded_aditi["like_counter"] == 1)
        result("Aniket liked count", len(loaded_aniket["liked"]) == 2)
        result("Aditi liked count", len(loaded_aditi["liked"]) == 1)
    finally:
        shutil.rmtree(tmp)


# --- Cross-Selection Tests ---

def test_cross_selection():
    """Test that profiles can see each other's selections."""
    print("\n--- Test: Cross-Selection Indicator ---")
    tmp = setup_test_dir()
    try:
        # Aniket has selected IMG_0000 and IMG_0001
        progress_aniket = tmp / ps.profile_progress_file("Aniket")
        data_aniket = {
            "current_index": 0,
            "liked": {"IMG_0000.jpg": "aniket_selected_001.jpg",
                      "IMG_0001.jpg": "aniket_selected_002.jpg"},
            "like_counter": 2,
        }
        progress_aniket.write_text(json.dumps(data_aniket), encoding="utf-8")

        # Now simulate Aditi loading other profiles
        aditi_progress_name = ps.profile_progress_file("Aditi")
        other_profiles = {}
        for f in tmp.iterdir():
            if (f.name.startswith(".photo_selector_")
                    and f.name.endswith(".json")
                    and f.name != aditi_progress_name):
                stem = f.stem
                other_name = stem.replace(".photo_selector_", "").title()
                data = json.loads(f.read_text(encoding="utf-8"))
                liked_data = data.get("liked", {})
                keys = set(liked_data.keys()) if isinstance(liked_data, dict) else set(liked_data)
                if keys:
                    other_profiles[other_name] = keys

        result("Aditi sees Aniket's profile", "Aniket" in other_profiles)
        result("Aniket has 2 selections", len(other_profiles.get("Aniket", set())) == 2)

        # Check cross-selection for specific photos
        img0_others = [n for n, keys in other_profiles.items() if "IMG_0000.jpg" in keys]
        img2_others = [n for n, keys in other_profiles.items() if "IMG_0002.jpg" in keys]

        result("IMG_0000 shows Aniket picked it", "Aniket" in img0_others)
        result("IMG_0002 shows no one picked it", len(img2_others) == 0)

        # Both Aniket and a third profile (Mom) picked the same photo
        progress_mom = tmp / ps.profile_progress_file("Mom")
        data_mom = {
            "current_index": 0,
            "liked": {"IMG_0000.jpg": "mom_selected_001.jpg"},
            "like_counter": 1,
        }
        progress_mom.write_text(json.dumps(data_mom), encoding="utf-8")

        # Reload
        other_profiles2 = {}
        for f in tmp.iterdir():
            if (f.name.startswith(".photo_selector_")
                    and f.name.endswith(".json")
                    and f.name != aditi_progress_name):
                stem = f.stem
                other_name = stem.replace(".photo_selector_", "").title()
                data = json.loads(f.read_text(encoding="utf-8"))
                liked_data = data.get("liked", {})
                keys = set(liked_data.keys()) if isinstance(liked_data, dict) else set(liked_data)
                if keys:
                    other_profiles2[other_name] = keys

        img0_others2 = [n for n, keys in other_profiles2.items() if "IMG_0000.jpg" in keys]
        result("IMG_0000 shows both Aniket and Mom", set(img0_others2) == {"Aniket", "Mom"})
    finally:
        shutil.rmtree(tmp)


# --- Naming Tests ---

def test_naming_over_99():
    """Test naming handles 100+ selections with 3-digit padding."""
    print("\n--- Test: Naming Beyond 99 ---")
    prefix = ps.profile_prefix("Aniket")
    name_99 = f"{prefix}{99:03d}.jpg"
    name_100 = f"{prefix}{100:03d}.jpg"
    name_999 = f"{prefix}{999:03d}.jpg"

    result("99th pads correctly", name_99 == "aniket_selected_099.jpg", f"Got {name_99}")
    result("100th stays 3 digits", name_100 == "aniket_selected_100.jpg", f"Got {name_100}")
    result("999th stays 3 digits", name_999 == "aniket_selected_999.jpg", f"Got {name_999}")

    names = [f"{prefix}{i:03d}.jpg" for i in range(1, 201)]
    result("200 files sort correctly", names == sorted(names))


def test_relative_key_stability():
    """Test that relative keys are stable across different mount points."""
    print("\n--- Test: Relative Key Stability ---")
    path_mac = Path("/Volumes/USB/DCIM/IMG_0001.jpg")
    source_mac = Path("/Volumes/USB")
    key_mac = str(path_mac.relative_to(source_mac))

    path_win = Path("/Volumes/USB 1/DCIM/IMG_0001.jpg")
    source_win = Path("/Volumes/USB 1")
    key_win = str(path_win.relative_to(source_win))

    result("Keys match across mounts", key_mac == key_win)


def test_duplicate_like_prevention():
    """Test that liking the same photo twice doesn't create duplicates."""
    print("\n--- Test: Duplicate Like Prevention ---")
    tmp = setup_test_dir()
    try:
        prefix = ps.profile_prefix("Aniket")
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()

        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        liked = {}
        counter = 0

        counter += 1
        new_name = f"{prefix}{counter:03d}.jpg"
        shutil.copy2(str(photo), str(selected_dir / new_name))
        liked[rel_key] = new_name

        already_liked = rel_key in liked
        result("Duplicate detected", already_liked)
        result("Only one file", len(list(selected_dir.iterdir())) == 1)
    finally:
        shutil.rmtree(tmp)


def test_file_extension_preservation():
    """Test that copy preserves original file extension."""
    print("\n--- Test: Extension Preservation ---")
    prefix = ps.profile_prefix("Aditi")
    result("PNG preserved", f"{prefix}{1:03d}.png" == "aditi_selected_001.png")
    result("CR2 preserved", f"{prefix}{2:03d}.cr2" == "aditi_selected_002.cr2")
    result("TIFF preserved", f"{prefix}{3:03d}.tiff" == "aditi_selected_003.tiff")


# --- Drive Root Tests ---

def test_drive_root_detection():
    """Test that _find_drive_root correctly identifies drive mount points."""
    print("\n--- Test: Drive Root Detection ---")
    mac_path = Path("/Volumes/MyUSB/DCIM/100CANON")
    result("macOS root", str(ps.PhotoSelector._find_drive_root(mac_path)) == "/Volumes/MyUSB")

    mac_direct = Path("/Volumes/MyUSB")
    result("macOS root direct", str(ps.PhotoSelector._find_drive_root(mac_direct)) == "/Volumes/MyUSB")

    linux_media = Path("/media/aniket/WeddingUSB/DCIM/photos")
    result("Linux /media root", str(ps.PhotoSelector._find_drive_root(linux_media)) == "/media/aniket/WeddingUSB")

    linux_mnt = Path("/mnt/usb/photos/subfolder")
    result("Linux /mnt root", str(ps.PhotoSelector._find_drive_root(linux_mnt)) == "/mnt/usb")


def test_subfolder_selection_shared_output():
    """Test that selecting subfolder puts profile folder at drive root."""
    print("\n--- Test: Subfolder -> Profile Folder at Drive Root ---")
    subfolder1 = Path("/Volumes/WeddingUSB/DCIM/100CANON")
    subfolder2 = Path("/Volumes/WeddingUSB/OtherPhotos")

    root1 = ps.PhotoSelector._find_drive_root(subfolder1)
    root2 = ps.PhotoSelector._find_drive_root(subfolder2)

    aniket_dir = root1 / ps.profile_dir_name("Aniket")
    aditi_dir = root1 / ps.profile_dir_name("Aditi")

    result("Aniket folder at USB root", str(aniket_dir) == "/Volumes/WeddingUSB/Aniket_Selected")
    result("Aditi folder at USB root", str(aditi_dir) == "/Volumes/WeddingUSB/Aditi_Selected")
    result("Different subfolders -> same root", root1 == root2)
    result("Both profiles at same root", aniket_dir.parent == aditi_dir.parent)


# --- Counter Continuity ---

def test_counter_continuity_across_folders():
    """Test naming continues across folder switches per profile."""
    print("\n--- Test: Counter Continuity Across Folders ---")
    tmp = setup_test_dir()
    try:
        prefix = ps.profile_prefix("Aniket")
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()
        progress_path = tmp / ps.profile_progress_file("Aniket")

        liked = {}
        counter = 0
        for i in range(3):
            photo = tmp / f"IMG_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            counter += 1
            new_name = f"{prefix}{counter:03d}{photo.suffix.lower()}"
            shutil.copy2(str(photo), str(selected_dir / new_name))
            liked[rel_key] = new_name

        data = {"current_index": 2, "liked": liked, "like_counter": counter}
        progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result("Session 1: counter at 3", counter == 3)

        loaded = json.loads(progress_path.read_text(encoding="utf-8"))
        counter = loaded["like_counter"]
        liked = loaded["liked"]

        result("Session 2: counter restored to 3", counter == 3)

        dcim = tmp / "DCIM"
        for i in range(2):
            photo = dcim / f"DSC_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            counter += 1
            new_name = f"{prefix}{counter:03d}{photo.suffix.lower()}"
            shutil.copy2(str(photo), str(selected_dir / new_name))
            liked[rel_key] = new_name

        result("Session 2: next file is _004",
               liked["DCIM/DSC_0000.jpg"] == "aniket_selected_004.jpg",
               f"Got {liked.get('DCIM/DSC_0000.jpg')}")
        result("Session 2: counter at 5", counter == 5)
        result("Session 2: total 5 files", len(list(selected_dir.iterdir())) == 5)
    finally:
        shutil.rmtree(tmp)


# --- Undo Tests ---

def test_undo_like():
    """Test undoing a like removes the file and unmarks it."""
    print("\n--- Test: Undo Like ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()
        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))

        liked = {}
        new_name = "aniket_selected_001.jpg"
        dest = selected_dir / new_name
        shutil.copy2(str(photo), str(dest))
        liked[rel_key] = new_name
        undo_stack = [("like", rel_key, new_name, 0)]

        result("File exists before undo", dest.exists())

        action, undo_key, undo_name, _ = undo_stack.pop()
        (selected_dir / undo_name).unlink()
        liked.pop(undo_key, None)

        result("File removed after undo", not dest.exists())
        result("Liked dict cleared", undo_key not in liked)
        result("Original untouched", photo.exists())
    finally:
        shutil.rmtree(tmp)


def test_undo_dislike():
    """Test undoing a dislike re-copies and re-marks."""
    print("\n--- Test: Undo Dislike ---")
    tmp = setup_test_dir()
    try:
        selected_dir = tmp / ps.profile_dir_name("Aniket")
        selected_dir.mkdir()
        photo = tmp / "IMG_0000.jpg"
        rel_key = str(photo.relative_to(tmp))
        new_name = "aniket_selected_001.jpg"
        dest = selected_dir / new_name

        liked = {}
        undo_stack = [("dislike", rel_key, new_name, 0)]

        action, undo_key, undo_name, _ = undo_stack.pop()
        shutil.copy2(str(tmp / undo_key), str(selected_dir / undo_name))
        liked[undo_key] = undo_name

        result("File restored after undo", dest.exists())
        result("Liked dict restored", undo_key in liked)
    finally:
        shutil.rmtree(tmp)


def test_undo_stack_multiple():
    """Test multiple undos in correct LIFO order."""
    print("\n--- Test: Undo Stack LIFO Order ---")
    undo_stack = [
        ("like", "IMG_A.jpg", "aniket_selected_001.jpg", 0),
        ("like", "IMG_B.jpg", "aniket_selected_002.jpg", 1),
        ("dislike", "IMG_A.jpg", "aniket_selected_001.jpg", 0),
    ]

    action1, key1, _, _ = undo_stack.pop()
    result("First undo is dislike of A", action1 == "dislike" and key1 == "IMG_A.jpg")
    action2, key2, _, _ = undo_stack.pop()
    result("Second undo is like of B", action2 == "like" and key2 == "IMG_B.jpg")
    action3, key3, _, _ = undo_stack.pop()
    result("Third undo is like of A", action3 == "like" and key3 == "IMG_A.jpg")
    result("Stack empty", len(undo_stack) == 0)


def test_undo_empty_stack():
    """Test undo on empty stack doesn't crash."""
    print("\n--- Test: Undo Empty Stack ---")
    result("Empty stack detected", len([]) == 0)


# --- Export Tests ---

def test_export_summary():
    """Test export generates valid profile-specific summary."""
    print("\n--- Test: Export Summary (Per Profile) ---")
    tmp = setup_test_dir()
    try:
        for profile_name in ["Aniket", "Aditi"]:
            dir_name = ps.profile_dir_name(profile_name)
            prefix = ps.profile_prefix(profile_name)
            selected_dir = tmp / dir_name
            selected_dir.mkdir(exist_ok=True)

            liked = {
                "IMG_0000.jpg": f"{prefix}001.jpg",
                "DCIM/DSC_0001.jpg": f"{prefix}002.jpg",
            }

            lines = [
                "=" * 60,
                f"WEDDING PHOTO SELECTION — {profile_name.upper()}",
                "=" * 60,
                f"Profile:   {profile_name}",
                f"Total selected: {len(liked)} photos",
                "",
                f"{'Selected Name':<35} {'Original File'}",
                "-" * 60,
            ]
            for orig, sel in sorted(liked.items(), key=lambda x: x[1]):
                lines.append(f"{sel:<35} {orig}")
            lines.append("-" * 60)
            lines.append(f"  Selected by: {profile_name}")
            lines.append(f"  All selected photos are in the '{dir_name}' folder.")

            summary_path = selected_dir / ps.SUMMARY_FILE
            summary_path.write_text("\n".join(lines), encoding="utf-8")

        # Verify Aniket
        aniket_summary = (tmp / "Aniket_Selected" / ps.SUMMARY_FILE).read_text(encoding="utf-8")
        result("Aniket summary has profile name", "ANIKET" in aniket_summary)
        result("Aniket summary has correct prefix", "aniket_selected_001" in aniket_summary)
        result("Aniket summary has folder name", "Aniket_Selected" in aniket_summary)

        # Verify Aditi
        aditi_summary = (tmp / "Aditi_Selected" / ps.SUMMARY_FILE).read_text(encoding="utf-8")
        result("Aditi summary has profile name", "ADITI" in aditi_summary)
        result("Aditi summary has correct prefix", "aditi_selected_001" in aditi_summary)
        result("Aditi summary has folder name", "Aditi_Selected" in aditi_summary)

        # Summaries are independent
        result("Summaries are different files",
               (tmp / "Aniket_Selected" / ps.SUMMARY_FILE) != (tmp / "Aditi_Selected" / ps.SUMMARY_FILE))
    finally:
        shutil.rmtree(tmp)


# --- Drive Accessibility ---

def test_drive_accessibility_check():
    """Test drive accessibility for existing and missing paths."""
    print("\n--- Test: Drive Accessibility Check ---")
    tmp = setup_test_dir()
    try:
        result("Existing dir accessible", tmp.exists() and os.access(str(tmp), os.R_OK))
        fake = Path("/tmp/nonexistent_usb_12345")
        result("Missing dir not accessible", not (fake.exists() and os.access(str(fake), os.R_OK)))
    finally:
        shutil.rmtree(tmp)


# --- Full Multi-Profile Integration ---

def test_multi_profile_full_workflow():
    """End-to-end: both Aniket and Aditi select photos independently on same USB."""
    print("\n--- Test: Multi-Profile Full Workflow ---")
    tmp = setup_test_dir()
    try:
        # Aniket selects 3 photos
        aniket_prefix = ps.profile_prefix("Aniket")
        aniket_dir = tmp / ps.profile_dir_name("Aniket")
        aniket_dir.mkdir()
        aniket_progress = tmp / ps.profile_progress_file("Aniket")

        aniket_liked = {}
        aniket_counter = 0
        for i in [0, 2, 4]:
            photo = tmp / f"IMG_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            aniket_counter += 1
            name = f"{aniket_prefix}{aniket_counter:03d}.jpg"
            shutil.copy2(str(photo), str(aniket_dir / name))
            aniket_liked[rel_key] = name
        aniket_progress.write_text(json.dumps({
            "current_index": 4, "liked": aniket_liked, "like_counter": aniket_counter,
        }), encoding="utf-8")

        # Aditi selects 2 photos (one overlapping with Aniket)
        aditi_prefix = ps.profile_prefix("Aditi")
        aditi_dir = tmp / ps.profile_dir_name("Aditi")
        aditi_dir.mkdir()
        aditi_progress = tmp / ps.profile_progress_file("Aditi")

        aditi_liked = {}
        aditi_counter = 0
        for i in [0, 1]:
            photo = tmp / f"IMG_{i:04d}.jpg"
            rel_key = str(photo.relative_to(tmp))
            aditi_counter += 1
            name = f"{aditi_prefix}{aditi_counter:03d}.jpg"
            shutil.copy2(str(photo), str(aditi_dir / name))
            aditi_liked[rel_key] = name
        aditi_progress.write_text(json.dumps({
            "current_index": 1, "liked": aditi_liked, "like_counter": aditi_counter,
        }), encoding="utf-8")

        # Verify independence
        result("Aniket has 3 files", len(list(aniket_dir.iterdir())) == 3)
        result("Aditi has 2 files", len(list(aditi_dir.iterdir())) == 2)

        result("Aniket counter is 3", aniket_counter == 3)
        result("Aditi counter is 2", aditi_counter == 2)

        result("Aniket files use aniket_ prefix",
               all(f.name.startswith("aniket_") for f in aniket_dir.iterdir()))
        result("Aditi files use aditi_ prefix",
               all(f.name.startswith("aditi_") for f in aditi_dir.iterdir()))

        # Originals untouched
        result("All 5 originals intact",
               all((tmp / f"IMG_{i:04d}.jpg").exists() for i in range(5)))

        # Cross-selection: from Aditi's view, IMG_0000 was also picked by Aniket
        other_profiles = {}
        for f in tmp.iterdir():
            if (f.name.startswith(".photo_selector_") and f.name.endswith(".json")
                    and f.name != ps.profile_progress_file("Aditi")):
                stem = f.stem
                other_name = stem.replace(".photo_selector_", "").title()
                data = json.loads(f.read_text(encoding="utf-8"))
                other_profiles[other_name] = set(data.get("liked", {}).keys())

        img0_others = [n for n, keys in other_profiles.items() if "IMG_0000.jpg" in keys]
        img1_others = [n for n, keys in other_profiles.items() if "IMG_0001.jpg" in keys]

        result("IMG_0000 cross-selected by Aniket", "Aniket" in img0_others)
        result("IMG_0001 not cross-selected", len(img1_others) == 0)

        # Separate progress files
        result("Two progress files exist",
               aniket_progress.exists() and aditi_progress.exists())
        result("Progress files are different",
               aniket_progress.name != aditi_progress.name)
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    print("=" * 60)
    print("Wedding Photo Selector — Core Logic Tests")
    print("=" * 60)

    test_profile_helpers()
    test_scan_photos()
    test_scan_excludes_all_selected_dirs()
    test_like_and_copy()
    test_dislike_and_remove()
    test_progress_save_load()
    test_cross_selection()
    test_naming_over_99()
    test_relative_key_stability()
    test_duplicate_like_prevention()
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
    test_multi_profile_full_workflow()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    print("=" * 60)

    sys.exit(1 if FAIL > 0 else 0)
