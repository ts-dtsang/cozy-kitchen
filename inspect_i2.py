import struct
from collections import Counter
from pathlib import Path

import UnityPy

ASSET_DIR = Path("unpacked")
I2_PATH_ID = 3415
OUTPUT_FILE = Path("i2_strings2.txt")
SEARCH_TERMS = (b"boiled egg", b"boiledegg", b"boiled_egg")
LANGUAGE_NAMES = {"English", "Vietnamese", "Tiếng Việt"}
CONTEXT = 12
MAX_OCCURRENCES = 3
SKIP_TYPES = {"Texture2D", "AudioClip", "Mesh", "Shader", "AnimationClip", "Cubemap"}


def extract_strings(raw: bytes) -> list[str]:
    """Find Unity-serialized strings (int32 length + UTF-8 bytes) inside raw object data."""
    found: list[str] = []
    pos = 0
    while pos + 4 <= len(raw):
        length = struct.unpack_from("<i", raw, pos)[0]
        if 1 <= length <= 400 and pos + 4 + length <= len(raw):
            try:
                text = raw[pos + 4 : pos + 4 + length].decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if text and text.isprintable():
                found.append(text)
                pos += 4 + length
                continue
        pos += 1
    return found


def build_script_index(env: UnityPy.Environment) -> dict[int, set[str]]:
    """Map MonoScript path id -> candidate class names (path ids can collide across files)."""
    index: dict[int, set[str]] = {}
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            index.setdefault(obj.path_id, set()).add(obj.read().m_ClassName)
    return index


def main() -> None:
    env = UnityPy.load(str(ASSET_DIR))

    # Part 1 and 2: dump the localization strings and show the layout around the dish
    for obj in env.objects:
        if obj.path_id != I2_PATH_ID or obj.type.name != "MonoBehaviour":
            continue
        strings = extract_strings(obj.get_raw_data())
        OUTPUT_FILE.write_text("\n".join(f"{i}\t{s}" for i, s in enumerate(strings)), encoding="utf-8")
        print(f"Wrote {len(strings)} strings to {OUTPUT_FILE}")

        hits = [i for i, s in enumerate(strings) if "boiled egg" in s.lower()]
        print(f"'boiled egg' appears at string indexes: {hits[:20]}")
        for hit in hits[:MAX_OCCURRENCES]:
            print(f"\n--- around index {hit} ---")
            for i in range(max(0, hit - CONTEXT), min(len(strings), hit + CONTEXT + 1)):
                print(f"{i}\t{strings[i]}")

        language_hits = [(i, s) for i, s in enumerate(strings) if s in LANGUAGE_NAMES]
        print(f"\nLanguage name positions (first 20): {language_hits[:20]}")

    # Part 3: find every object (any type) that contains the dish name
    script_index = build_script_index(env)
    class_counter: Counter[str] = Counter()
    print("\n=== Objects containing the dish name ===")
    for obj in env.objects:
        if obj.type.name in SKIP_TYPES:
            continue
        raw = obj.get_raw_data()

        class_label = obj.type.name
        if obj.type.name == "MonoBehaviour":
            # Layout: m_GameObject PPtr (12) + m_Enabled (4) + m_Script PPtr (int32 file id + int64 path id)
            file_id, script_path_id = struct.unpack_from("<iq", raw, 16)
            names = script_index.get(script_path_id, set())
            class_label = next(iter(names)) if len(names) == 1 else f"<{len(names)} candidates, file_id={file_id}>"
            class_counter[class_label] += 1

        lowered = raw.lower()
        for term in SEARCH_TERMS:
            if term in lowered:
                print(f"{obj.type.name} path_id={obj.path_id} class={class_label} size={len(raw)} term={term!r}")

    print("\n=== MonoBehaviour count per class (top 40) ===")
    for class_label, count in class_counter.most_common(40):
        print(f"{class_label}: {count}")


if __name__ == "__main__":
    main()
