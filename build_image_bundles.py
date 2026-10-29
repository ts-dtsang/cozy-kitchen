"""Build image-bundles.json from an Addressables binary catalog (catalog.bin).

Input : catalog.bin   (StreamingAssets/aa/catalog.bin, Addressables 2.x binary format)
Output: image-bundles.json
        {"base_url": ..., "bundles": [...], "assets": {name: {folder, key, bundles}}}

Only the Python standard library is needed.
Usage : python build_image_bundles.py [catalog.bin] [--out image-bundles.json] [--base URL]

The catalog format is not documented by Unity, so the layout below was worked out from the file itself:

  header   : 9 x uint32 = magic, version, then 7 offsets (keys, ids, types, providers..., build hash)
  keys     : pairs (keyOffset, locationsOffset) from the keys offset up to the first string (offset 3 minus 4)
  array    : the element count is stored in the 4 bytes BEFORE the offset (byte size, 4 bytes per item)
  location : 7 x uint32 = primaryKey, internalId, provider, dependencies, data, depHash, resourceType
  string   : a pointer whose bits mean: 0x80000000 = UTF-16, 0x40000000 = "dynamic" string
             a plain string has its byte length in the 4 bytes before the characters
             a dynamic string is a chain of (partPointer, parentOffset) joined by "/"
"""

import argparse
import json
import re
import struct
from collections import defaultdict
from pathlib import Path

MAGIC = 0x0DE38942
UNICODE_FLAG = 0x80000000
DYNAMIC_FLAG = 0x40000000
OFFSET_MASK = 0x3FFFFFFF
NO_PARENT = 0xFFFFFFFF
MAX_CHAIN = 12  # a dynamic string is never this deep, it only guards against loops

BASE_URL = "https://files.crazygames.com/cozy-kitchen/33/StreamingAssets/aa/WebGL/"
RUNTIME_PATH_PREFIX = "{UnityEngine.AddressableAssets.Addressables.RuntimePath}/WebGL/"
BUNDLE_PROVIDER = "BundledAssetProvider"
IMAGE_KEY = re.compile(r"^Assets/Resource Addressable/(Dish|FirstDish|Menu Collections)/(.+)\.png$")


class Catalog:
    def __init__(self, data: bytes) -> None:
        self.data = data
        header = struct.unpack_from("<9I", data, 0)
        if header[0] != MAGIC:
            raise ValueError(f"Not an Addressables binary catalog (magic 0x{header[0]:08x})")
        self.version = header[1]
        self.keys_offset = header[2]
        # The keys table ends right before the first string (its length prefix is 4 bytes before the text).
        # header[8] looks like the end of the table but it points into the middle of it.
        self.keys_end = header[3] - 4

    def uint(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def text(self, pointer: int) -> str:
        offset = pointer & OFFSET_MASK
        length = self.uint(offset - 4)
        encoding = "utf-16-le" if pointer & UNICODE_FLAG else "utf-8"
        return self.data[offset : offset + length].decode(encoding)

    def dynamic_chain(self, offset: int, depth: int = 0) -> str:
        part, parent = self.uint(offset), self.uint(offset + 4)
        text = self.text(part)
        if parent == NO_PARENT or depth > MAX_CHAIN:
            return text
        return self.dynamic_chain(parent, depth + 1) + "/" + text

    def string(self, pointer: int) -> str:
        if pointer & DYNAMIC_FLAG:
            return self.dynamic_chain(pointer & OFFSET_MASK)
        return self.text(pointer)

    def array(self, offset: int) -> list[int]:
        if offset == NO_PARENT:
            return []
        count = self.uint(offset - 4) // 4
        return [self.uint(offset + 4 * index) for index in range(count)]

    def location(self, offset: int) -> dict[str, int]:
        names = ("primary_key", "internal_id", "provider", "dependencies", "data", "dep_hash", "resource_type")
        return dict(zip(names, struct.unpack_from("<7I", self.data, offset)))

    def location_offsets(self) -> set[int]:
        """Every location record reachable from the keys table."""
        found: set[int] = set()
        for position in range(self.keys_offset, self.keys_end, 8):
            _, locations = struct.unpack_from("<II", self.data, position)
            try:
                found.update(offset for offset in self.array(locations) if 0 < offset < len(self.data) - 28)
            except (struct.error, IndexError):
                continue  # not every pair points to a location array
        return found


def collect_image_bundles(catalog: Catalog) -> dict[str, dict]:
    """Map image name -> {folder, key, bundles} for dishes and menu collections."""
    images: dict[str, dict] = {}
    bundles_of: dict[str, set[str]] = defaultdict(set)

    for offset in sorted(catalog.location_offsets()):
        record = catalog.location(offset)
        try:
            if not catalog.string(record["provider"]).endswith(BUNDLE_PROVIDER):
                continue
            key = catalog.string(record["primary_key"])
            match = IMAGE_KEY.match(key)
            if not match:
                continue
            for dependency in catalog.array(record["dependencies"]):
                bundle = catalog.string(catalog.location(dependency)["internal_id"])
                if "monoscripts" not in bundle:  # script bundle, no images in it
                    bundles_of[key].add(bundle.removeprefix(RUNTIME_PATH_PREFIX))
        except (struct.error, UnicodeDecodeError, ValueError):
            continue
        images[match.group(2)] = {"folder": match.group(1), "key": key}

    for name, info in images.items():
        info["bundles"] = sorted(bundles_of[info["key"]])
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalog", type=Path, nargs="?", default=Path("data/src/catalog.bin"))
    parser.add_argument("--out", type=Path, default=Path("data/ouput/image-bundles.json"))
    parser.add_argument("--base", default=BASE_URL, help="url of the WebGL bundle folder (must end with /)")
    args = parser.parse_args()

    catalog = Catalog(args.catalog.read_bytes())
    print(f"catalog version {catalog.version}, {len(catalog.location_offsets())} locations")

    images = collect_image_bundles(catalog)
    bundles = sorted({bundle for info in images.values() for bundle in info["bundles"]})
    missing = [name for name, info in images.items() if not info["bundles"]]

    args.out.write_text(
        json.dumps({"base_url": args.base, "bundles": bundles, "assets": images}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{len(images)} images in {len(bundles)} bundles -> {args.out}")
    if missing:
        print(f"WARNING: {len(missing)} images have no bundle, e.g. {missing[:5]}")


if __name__ == "__main__":
    main()
