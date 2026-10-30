"""Extract the cozy-kitchen recipe data from the game's Unity WebGL data file.

Input:  data/src/cozy-kitchen.data.br
Output: recipes.json      every recipe: name, category, dish type, ingredients, description, image
        ingredients.json  every ingredient and every tag (a tag is listed like an ingredient, with "is_tag": true)
        translations.json every name -> {"name": {...}, "description": {...}} in the 15 languages of the game
        data/images/      ingredients/*.png (tag icons included), and recipes/*.png when --bundles-dir is given

Pipeline: .data.br -> decompress -> unpack the UnityWebData archive -> read the DataRecipe object (Odin format)
-> read the I2 Localization terms (names and descriptions in 15 languages) -> export the images
-> write the JSON files.

The ingredient images are inside the game data. The dish images are Addressable assets that the game downloads
while it runs: save those bundle files into one folder and pass it with --bundles-dir.
The "image" links look like "images/ingredients/egg.png": they are relative to the parent of the images folder.

Requirements: pip install brotli UnityPy   (UnityPy brings Pillow and the texture decoders)
"""

import argparse
import itertools
import json
import re
import struct
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import brotli
import UnityPy

WEB_DATA_MAGIC = b"UnityWebData1.0\x00"
RECIPE_SCRIPT_NAME = "DataRecipe"
BLOB_HEAD_MARKER = "dictIngredientConfigs".encode("utf-16-le")
BLOB_HEAD_SIZE = 64

# Recipe dictionary field -> category label written to recipes.json
RECIPE_FIELDS = {
    "dicNormalRecipe": "normal",
    "dicDarkCuisineRecipe": "dark_cuisine",
    "dicMessyRecipe": "messy",
}

MONOBEHAVIOUR_HEADER_SIZE = 28  # m_GameObject (12) + m_Enabled (4) + m_Script (12)
LOCALIZATION_SCRIPT_NAME = "LanguageSourceAsset"
DESCRIPTION_SUFFIX = " desc"  # the game stores the description of "<name>" under the key "<name> desc"

# Language of each translation column, in the order the game stores them (cross-checked with the Vietnamese column).
# The two "Telur" columns are Indonesian and Malay; their order is a guess, swap them here if it is wrong.
LANGUAGE_CODES = [
    ("English", "en"),
    ("Vietnamese", "vi"),
    ("Indonesian", "id"),
    ("Malay", "ms"),
    ("Thai", "th"),
    ("Russian", "ru"),
    ("Hindi", "hi"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Turkish", "tr"),
    ("Korean", "ko"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
]

MAX_EXAMPLES = 10
IMAGE_TYPES = ("Texture2D", "Sprite")  # a Texture2D is preferred when both carry the same name

# Limits used to recognise I2 Localization term records
MAX_TERM_BYTES = 200  # must stay below 256: the scan checks the length with a single byte
MAX_STRING_BYTES = 5000
MAX_ARRAY_LENGTH = 64
MIN_LANGUAGES = 2
MIN_CHAIN = 20  # consecutive valid records needed to trust a layout
MAX_SCAN_BYTES = 1_000_000
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Letters that only Vietnamese uses (not French, Spanish, Italian, Turkish, ...)
VIETNAMESE_CHARS = frozenset("ăơưđạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ")

# Odin binary entry types (the unnamed variant of a primitive is the named code + 1)
NAMED_REF_NODE = 0x01
UNNAMED_REF_NODE = 0x02
NAMED_STRUCT_NODE = 0x03
UNNAMED_STRUCT_NODE = 0x04
END_OF_NODE = 0x05
START_OF_ARRAY = 0x06
END_OF_ARRAY = 0x07
PRIMITIVE_ARRAY = 0x08
UNNAMED_NULL = 0x2E
TYPE_NAME = 0x2F
TYPE_ID = 0x30
END_OF_STREAM = 0x31

# Leaf entries that carry a leading name string, and their unnamed counterparts
NAMED_LEAF = {0x09, 0x0B, 0x0D, 0x32} | set(range(0x0F, 0x2E, 2))
UNNAMED_LEAF = {0x0A, 0x0C, 0x0E, 0x33} | set(range(0x10, 0x2F, 2))

# Named primitive entry -> struct format
PRIMITIVES = {
    0x0F: "<b",
    0x11: "<B",
    0x13: "<h",
    0x15: "<H",
    0x17: "<i",
    0x19: "<I",
    0x1B: "<q",
    0x1D: "<Q",
    0x1F: "<f",
    0x21: "<d",
    0x25: "<H",
    0x2B: "<?",
}


# ---------------------------------------------------------------------------
# Step 1: read and decompress the .data file
# ---------------------------------------------------------------------------
def load_web_data(data_file: Path) -> bytes:
    """Read the .data file and decompress it with Brotli unless the browser already did."""
    raw = data_file.read_bytes()
    if not raw.startswith(WEB_DATA_MAGIC):
        raw = brotli.decompress(raw)
    if not raw.startswith(WEB_DATA_MAGIC):
        raise ValueError("Not a Unity WebGL .data file (missing UnityWebData1.0 header)")
    return raw


# ---------------------------------------------------------------------------
# Step 2: unpack the UnityWebData archive into a folder
# ---------------------------------------------------------------------------
def unpack_web_data(raw: bytes, output_dir: Path) -> None:
    """Split a Unity WebGL .data archive into the files it contains."""
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()

    # Header: magic (16 bytes) + uint32 total header length
    head_length = struct.unpack_from("<I", raw, len(WEB_DATA_MAGIC))[0]
    pos = len(WEB_DATA_MAGIC) + 4

    while pos < head_length:
        # Each entry: offset, size, name length, then the name itself
        offset, size, name_len = struct.unpack_from("<III", raw, pos)
        name = raw[pos + 12 : pos + 12 + name_len].decode("utf-8")
        pos += 12 + name_len

        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Unsafe path in archive: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw[offset : offset + size])


# ---------------------------------------------------------------------------
# Step 3: find ScriptableObjects by script class name and cut out the DataRecipe blob
# ---------------------------------------------------------------------------
def align4(value: int) -> int:
    """Round up to the next multiple of 4 (Unity pads serialized strings to 4 bytes)."""
    return (value + 3) & ~3


class GameAssets:
    """The unpacked Unity assets, with a MonoScript index to find object data by class name."""

    def __init__(self, asset_dir: Path) -> None:
        self.env = UnityPy.load(str(asset_dir))

        # Map MonoScript path id -> class names (path ids can collide across serialized files)
        self.script_names: dict[int, set[str]] = {}
        for obj in self.env.objects:
            if obj.type.name == "MonoScript":
                self.script_names.setdefault(obj.path_id, set()).add(obj.read().m_ClassName)

    def script_objects(self, class_name: str) -> Iterator[bytes]:
        """Yield the raw data of every MonoBehaviour whose script class is class_name."""
        for _, raw in self.script_object_list(class_name):
            yield raw

    def script_object_list(self, class_name: str) -> Iterator[tuple[Any, bytes]]:
        """Yield (object, raw data) of every MonoBehaviour whose script class is class_name."""
        for obj in self.env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            raw = obj.get_raw_data()
            if len(raw) < MONOBEHAVIOUR_HEADER_SIZE:
                continue
            # The m_Script PPtr starts at offset 16: int32 file id + int64 path id
            _, script_path_id = struct.unpack_from("<iq", raw, 16)
            if class_name in self.script_names.get(script_path_id, set()):
                yield obj, raw


def read_blob(raw: bytes) -> bytes:
    """Skip the MonoBehaviour header and return the large Odin byte array."""
    pos = MONOBEHAVIOUR_HEADER_SIZE
    name_len = struct.unpack_from("<i", raw, pos)[0]
    pos = align4(pos + 4 + name_len)
    _, blob_len = struct.unpack_from("<ii", raw, pos)  # (format field, byte array length)
    pos += 8
    return raw[pos : pos + blob_len]


def find_recipe_blob(assets: GameAssets) -> bytes:
    """Locate the DataRecipe object and return its Odin blob."""
    for raw in assets.script_objects(RECIPE_SCRIPT_NAME):
        try:
            blob = read_blob(raw)
        except (struct.error, ValueError):
            continue
        # Guard against path id collisions: the real blob starts with this field name
        if BLOB_HEAD_MARKER in blob[:BLOB_HEAD_SIZE]:
            return blob

    raise LookupError(f"No {RECIPE_SCRIPT_NAME} object found. The game may have changed its data format.")


TAG_FIELD = "dicTagIngredients"  # tag -> ingredients that carry it
TAG_ICON_FIELD = "dicTagIcon"  # tag -> {"$ext": n}, the n-th Unity object referenced by the DataRecipe object
TAG_PRIORITY_FIELD = "dicTagPriority"
MAX_REFERENCES = 10_000


def read_references(raw: bytes) -> list[tuple[int, int]]:
    """Return the Unity objects an Odin object points to, as (file id, path id) in {"$ext": n} order.

    They are stored after the Odin byte array: int32 count, then one PPtr (int32 file id + int64 path id) each.
    """
    pos = MONOBEHAVIOUR_HEADER_SIZE
    name_len = struct.unpack_from("<i", raw, pos)[0]
    pos = align4(pos + 4 + name_len)
    _, blob_len = struct.unpack_from("<ii", raw, pos)
    pos = align4(pos + 8 + blob_len)
    count = struct.unpack_from("<i", raw, pos)[0]
    if not 0 <= count <= MAX_REFERENCES:
        raise ValueError(f"Bad reference count {count} at offset {pos}")
    pos += 4
    return [struct.unpack_from("<iq", raw, pos + 12 * index) for index in range(count)]


def find_tag_icons(assets: GameAssets, data: dict[str, Any]) -> dict[str, Any]:
    """Map each tag to the Sprite object the game itself shows for it (DataRecipe.dicTagIcon)."""
    for obj, raw in assets.script_object_list(RECIPE_SCRIPT_NAME):
        try:
            blob = read_blob(raw)
            references = read_references(raw)
        except (struct.error, ValueError):
            continue
        if BLOB_HEAD_MARKER not in blob[:BLOB_HEAD_SIZE]:
            continue

        icons: dict[str, Any] = {}
        for tag, reference in dict_pairs(data, TAG_ICON_FIELD):
            if not isinstance(reference, dict) or "$ext" not in reference:
                continue
            try:
                file_id, path_id = references[reference["$ext"]]
            except IndexError:
                continue
            if file_id != 0:  # 0 = the same file as the DataRecipe object, which is where the sprites are
                continue
            target = obj.assets_file.objects.get(path_id)
            if target is not None and target.type.name in IMAGE_TYPES:
                icons[tag] = target
        return icons

    raise LookupError(f"No {RECIPE_SCRIPT_NAME} object found. The game may have changed its data format.")


MENU_SCRIPT_NAME = "DataMenuCollections"
MENU_FIELD = "dicMenuCollectionConfigs"


def find_menu_blob(assets: GameAssets) -> bytes:
    """Locate the DataMenuCollections object and return its Odin blob."""
    marker = MENU_FIELD.encode("utf-16-le")
    for raw in assets.script_objects(MENU_SCRIPT_NAME):
        try:
            blob = read_blob(raw)
        except (struct.error, ValueError):
            continue
        if marker in blob[:BLOB_HEAD_SIZE]:
            return blob
    raise LookupError(f"No {MENU_SCRIPT_NAME} object found.")


def build_menu_collections(menu_data: dict[str, Any], lookup: "TermLookup") -> list[dict[str, Any]]:
    result = []
    for _, menu in dict_pairs(menu_data, MENU_FIELD):
        name = language_map(lookup.find(menu["name"]))
        description = language_map(lookup.find(menu["description"]))
        result.append(
            {
                "id": menu["id"],
                "sort_order": menu["sortOrder"],
                "name": name["en"],
                "description": description["en"],
                "available_quest": menu["availableQuest"],
                "quest_phase": menu["questPhase"],
                "story_unlock": menu["storyUnlock"],
                "reward_type": menu["rewardType"],
                "required_ingredients": menu["requiredIngredients"],
                "recipes": menu["recipes"],
                "image": None,
                "translations": {"name": name, "description": description},
            }
        )
    return result


# ---------------------------------------------------------------------------
# Step 4: parse the Odin binary format
# ---------------------------------------------------------------------------
class OdinReader:
    """Minimal reader for the Odin Serializer binary format."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.types: dict[int, str] = {}
        self.nodes: dict[int, Any] = {}
        self.result: dict[str, Any] = {}

    def take(self, fmt: str) -> Any:
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += struct.calcsize(fmt)
        return value

    def read_bytes(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError(f"Cannot read {count} bytes at offset {self.pos}")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def read_string(self) -> str:
        """Read a string stored as: width flag (0 = 8-bit, 1 = 16-bit) + int32 length + characters."""
        wide = self.take("<B")
        length = self.take("<i")
        if wide not in (0, 1) or not 0 <= length <= 100_000:
            raise ValueError(f"Bad string header (wide={wide}, length={length}) at offset {self.pos - 5}")
        raw = self.read_bytes(length * 2 if wide else length)
        return raw.decode("utf-16-le" if wide else "latin-1")

    def read_type(self) -> str | None:
        """Read the type marker that follows a node start."""
        marker = self.take("<B")
        if marker == TYPE_NAME:
            type_id = self.take("<i")
            name = self.read_string()
            self.types[type_id] = name
            return name
        if marker == TYPE_ID:
            return self.types.get(self.take("<i"))
        if marker == UNNAMED_NULL:
            return None
        raise ValueError(f"Unexpected type marker 0x{marker:02x} at offset {self.pos - 1}")

    def read_node(self, entry: int) -> Any:
        """Read a node body: named children become a dict, a lone array becomes a list."""
        self.read_type()
        node_id = None
        if entry in (NAMED_REF_NODE, UNNAMED_REF_NODE):
            node_id = self.take("<i")

        fields: dict[str, Any] = {}
        items: list[Any] = []
        while True:
            child = self.take("<B")
            if child == END_OF_NODE:
                break
            name, value = self.read_entry(child)
            if name is None:
                items.append(value)
            else:
                fields[name] = value

        result: Any
        if not fields and len(items) == 1 and isinstance(items[0], list):
            result = items[0]  # A List<T> node is just its array
        else:
            result = fields
            if items:
                result["_items"] = items[0] if len(items) == 1 else items

        if node_id is not None:
            self.nodes[node_id] = result
        return result

    def read_array(self) -> list[Any]:
        length = self.take("<q")
        items: list[Any] = []
        for _ in range(length):
            _, value = self.read_entry(self.take("<B"))
            items.append(value)
        end = self.take("<B")
        if end != END_OF_ARRAY:
            raise ValueError(f"Expected EndOfArray, got 0x{end:02x} at offset {self.pos - 1}")
        return items

    def read_primitive_array(self) -> list[int]:
        count = self.take("<i")
        size = self.take("<i")
        raw = self.read_bytes(count * size)
        return [int.from_bytes(raw[i * size : (i + 1) * size], "little") for i in range(count)]

    def read_entry(self, entry: int) -> tuple[str | None, Any]:
        """Read one entry whose type byte was already consumed; return (name, value)."""
        if entry in (NAMED_REF_NODE, NAMED_STRUCT_NODE):
            name = self.read_string()
            return name, self.read_node(entry)
        if entry in (UNNAMED_REF_NODE, UNNAMED_STRUCT_NODE):
            return None, self.read_node(entry)
        if entry == START_OF_ARRAY:
            return None, self.read_array()
        if entry == PRIMITIVE_ARRAY:
            return None, self.read_primitive_array()

        if entry in NAMED_LEAF:
            name, base = self.read_string(), entry
        elif entry in UNNAMED_LEAF:
            name, base = None, entry - 1
        else:
            raise ValueError(f"Unknown entry type 0x{entry:02x} at offset {self.pos - 1}")

        value: Any
        if base in PRIMITIVES:
            value = self.take(PRIMITIVES[base])
        elif base in (0x23, 0x29):  # Decimal, Guid
            value = self.read_bytes(16).hex()
        elif base in (0x27, 0x32):  # String, external reference by string
            value = self.read_string()
        elif base == 0x2D:  # Null
            value = None
        elif base == 0x09:  # Internal reference
            value = {"$ref": self.take("<i")}
        elif base == 0x0B:  # External reference by index
            value = {"$ext": self.take("<i")}
        else:  # 0x0D: external reference by guid
            value = {"$guid": self.read_bytes(16).hex()}
        return name, value

    def parse(self) -> None:
        """Read the top-level fields into self.result."""
        while self.pos < len(self.data):
            entry = self.take("<B")
            if entry == END_OF_STREAM:
                break
            name, value = self.read_entry(entry)
            self.result[name or f"_unnamed_{len(self.result)}"] = value


def resolve_refs(value: Any, nodes: dict[int, Any], depth: int = 0) -> Any:
    """Replace {"$ref": id} placeholders with the node they point to."""
    if depth > 50:
        return value
    if isinstance(value, dict):
        if set(value) == {"$ref"} and value["$ref"] in nodes:
            return nodes[value["$ref"]]
        return {key: resolve_refs(child, nodes, depth + 1) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_refs(child, nodes, depth + 1) for child in value]
    return value


def parse_odin(blob: bytes) -> dict[str, Any]:
    """Parse the whole Odin blob into plain Python data."""
    reader = OdinReader(blob)
    try:
        reader.parse()
    except Exception as error:
        raise RuntimeError(f"Odin parse failed at offset {reader.pos} of {len(blob)}: {error!r}") from error
    return resolve_refs(reader.result, reader.nodes)


def dict_pairs(data: dict[str, Any], field: str) -> list[tuple[str, Any]]:
    """Return the (key, value) pairs of a serialized Dictionary field."""
    value = data[field]
    items = value["_items"] if isinstance(value, dict) else value
    return [(pair["$k"], pair["$v"]) for pair in items]


# ---------------------------------------------------------------------------
# Step 5: read the I2 Localization terms (names, descriptions and their translations)
# ---------------------------------------------------------------------------
# Every term record is Unity-serialized in this order (the layout flags below cover the optional parts):
#   string Term, int32 TermType, [string Description], string[] Languages, [byte[] Flags], [string[] Languages_Touch]
@dataclass(frozen=True)
class TermLayout:
    """Which optional fields each I2 term record contains."""

    has_description: bool
    has_flags: bool
    has_touch: bool


Term = tuple[str, list[str]]  # (English key, translation per language)


def read_int32(raw: bytes, pos: int) -> int:
    return struct.unpack_from("<i", raw, pos)[0]


def read_unity_string(raw: bytes, pos: int, max_length: int = MAX_STRING_BYTES) -> tuple[str, int]:
    """Read a Unity-serialized string (int32 length + UTF-8 bytes, padded to 4); return (text, next position)."""
    length = read_int32(raw, pos)
    end = pos + 4 + length
    if not 0 <= length <= max_length or end > len(raw):
        raise ValueError(f"Bad string length {length} at offset {pos}")
    text = raw[pos + 4 : end].decode("utf-8")
    if CONTROL_CHARS.search(text):
        raise ValueError(f"Control characters in string at offset {pos}")
    return text, align4(end)


def read_string_array(raw: bytes, pos: int) -> tuple[list[str], int]:
    """Read a Unity string[] (int32 count + strings); return (items, next position)."""
    count = read_int32(raw, pos)
    if not 0 <= count <= MAX_ARRAY_LENGTH:
        raise ValueError(f"Bad array length {count} at offset {pos}")
    pos += 4
    items: list[str] = []
    for _ in range(count):
        text, pos = read_unity_string(raw, pos)
        items.append(text)
    return items, pos


def read_term(raw: bytes, pos: int, layout: TermLayout) -> tuple[Term, int]:
    """Read one term record starting at pos; return (term, next position)."""
    key, pos = read_unity_string(raw, pos, MAX_TERM_BYTES)
    if not key:
        raise ValueError(f"Empty term at offset {pos}")
    pos += 4  # TermType enum (int32)
    if layout.has_description:
        _, pos = read_unity_string(raw, pos)
    translations, pos = read_string_array(raw, pos)
    if len(translations) < MIN_LANGUAGES:
        raise ValueError(f"Too few languages at offset {pos}")
    if layout.has_flags:
        flags_length = read_int32(raw, pos)
        if not 0 <= flags_length <= MAX_ARRAY_LENGTH:
            raise ValueError(f"Bad flags length {flags_length} at offset {pos}")
        pos = align4(pos + 4 + flags_length)
    if layout.has_touch:
        _, pos = read_string_array(raw, pos)
    return (key, translations), pos


def read_term_chain(raw: bytes, start: int, layout: TermLayout, limit: int | None = None) -> list[Term]:
    """Read consecutive term records from start until one fails to parse (or limit is reached)."""
    terms: list[Term] = []
    pos = start
    while limit is None or len(terms) < limit:
        try:
            term, pos = read_term(raw, pos, layout)
        except (ValueError, struct.error):
            break
        terms.append(term)
    return terms


def find_chain_start(raw: bytes, layout: TermLayout) -> int | None:
    """Find the first offset where MIN_CHAIN valid term records follow each other."""
    for pos in range(min(len(raw), MAX_SCAN_BYTES)):
        # Cheap pre-filter: a plausible string length is a small int32 (high three bytes are zero)
        if not 0 < raw[pos] <= MAX_TERM_BYTES or raw[pos + 1 : pos + 4] != b"\x00\x00\x00":
            continue
        chain = read_term_chain(raw, pos, layout, limit=MIN_CHAIN)
        if len(chain) == MIN_CHAIN and len({len(translations) for _, translations in chain}) == 1:
            return pos
    return None


def detect_terms(raw: bytes) -> tuple[TermLayout, list[Term]] | None:
    """Try every layout and keep the one that reads the most terms."""
    best: tuple[TermLayout, list[Term]] | None = None
    for flags in itertools.product((True, False), repeat=3):
        layout = TermLayout(*flags)
        start = find_chain_start(raw, layout)
        if start is None:
            continue
        terms = read_term_chain(raw, start, layout)
        if best is None or len(terms) > len(best[1]):
            best = (layout, terms)
    return best


def hexdump_around(raw: bytes, anchor: str) -> str:
    """Hexdump of the raw data around the first occurrence of anchor, to help work out the layout."""
    encoded = anchor.encode("utf-8")
    position = raw.find(struct.pack("<i", len(encoded)) + encoded)
    if position < 0:
        return f"'{anchor}' was not found in the localization data."

    start = max(0, position - 64)
    lines: list[str] = []
    for offset in range(start - start % 16, min(len(raw), position + 512), 16):
        chunk = raw[offset : offset + 16]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"{offset:08x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def find_localization_terms(assets: GameAssets, anchor: str) -> tuple[TermLayout, list[Term]]:
    """Parse the I2 Localization terms; anchor is a known term used for the failure report."""
    raws = list(assets.script_objects(LOCALIZATION_SCRIPT_NAME))
    best: tuple[TermLayout, list[Term]] | None = None
    for raw in raws:
        result = detect_terms(raw)
        if result is not None and (best is None or len(result[1]) > len(best[1])):
            best = result

    if best is None:
        if raws:
            report = hexdump_around(max(raws, key=len), anchor)
        else:
            report = f"No {LOCALIZATION_SCRIPT_NAME} object found."
        raise LookupError(f"Could not read the I2 Localization terms. Please share this dump:\n{report}")
    return best


def find_vietnamese_index(terms: list[Term]) -> int:
    """Return the language column whose translations most often contain Vietnamese-only letters."""
    hits: Counter[int] = Counter()
    for _, translations in terms:
        for index, text in enumerate(translations):
            if VIETNAMESE_CHARS & set(text.lower()):
                hits[index] += 1
    if not hits:
        raise LookupError("No Vietnamese translations found in the localization terms.")
    return hits.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Step 6: export the images
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Lower-case a name and drop everything except letters and digits, so 'Boiled_Egg' == 'boiled egg'."""
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def slugify(name: str) -> str:
    """Make a safe file name: 'Sautéed Bell Peppers & Onions' -> 'sauteed_bell_peppers_onions'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_") or "image"


def unique_file_name(slug: str, used: set[str]) -> str:
    """Return '<slug>.png', or '<slug>_2.png' and so on when that name is already taken."""
    candidate, number = f"{slug}.png", 2
    while candidate in used:
        candidate = f"{slug}_{number}.png"
        number += 1
    used.add(candidate)
    return candidate


def index_images(env: Any) -> dict[str, list[Any]]:
    """Map each normalized image name to its Texture2D / Sprite objects (Texture2D first)."""
    index: dict[str, list[Any]] = {}
    for type_name in IMAGE_TYPES:
        for obj in env.objects:
            if obj.type.name != type_name:
                continue
            try:
                name = obj.read().m_Name
            except Exception:  # an object that cannot be parsed is simply not available as an image
                continue
            index.setdefault(normalize(name), []).append(obj)
    return index


def export_images(index: dict[str, list[Any]], names: list[str], images_dir: Path, folder: str) -> dict[str, str]:
    """Save one PNG per name into images_dir/folder; return {name: link} for the names that have an image."""
    target_dir = images_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    links: dict[str, str] = {}
    used: set[str] = set()
    failed: list[str] = []
    for name in dict.fromkeys(names):
        objects = index.get(normalize(name))
        if not objects:
            continue
        file_name = unique_file_name(slugify(name), used)
        try:
            objects[0].read().image.save(target_dir / file_name)
        except Exception as error:  # a texture that cannot be decoded must not stop the export
            failed.append(f"{name} ({error})")
            continue
        links[name] = f"{images_dir.name}/{folder}/{file_name}"
    if failed:
        print(f"      could not decode {len(failed)} images, e.g. {failed[:MAX_EXAMPLES]}")
    return links


# ---------------------------------------------------------------------------
# Step 7: build and write the output files
# ---------------------------------------------------------------------------
class TermLookup:
    """Find the translations of a key (exact match first, then ignoring case)."""

    def __init__(self, terms: list[Term]) -> None:
        self.table: dict[str, list[str]] = {}
        for key, translations in terms:
            self.table.setdefault(key, translations)
        self.lower_table: dict[str, list[str]] = {}
        for key, translations in self.table.items():
            self.lower_table.setdefault(key.lower(), translations)

    def find(self, key: str) -> list[str] | None:
        return self.table.get(key) or self.lower_table.get(key.lower())

    def description_keys(self) -> list[str]:
        return [key for key in self.table if key.lower().endswith(DESCRIPTION_SUFFIX)]


def language_map(translations: list[str] | None) -> dict[str, str | None]:
    """Return {language code: text} for the 15 languages; a missing or empty text becomes None."""
    values = translations or []
    result: dict[str, str | None] = {}
    for index, (_, code) in enumerate(LANGUAGE_CODES):
        text = values[index] if index < len(values) else None
        result[code] = text or None
    return result


def build_outputs(
    data: dict[str, Any],
    lookup: TermLookup,
    ingredient_images: dict[str, str],
    recipe_images: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, dict[str, str | None]]]]:
    """Turn the parsed data into (recipes, ingredients, translations).

    translations maps every name to {"name": {language code: text}, "description": {language code: text}}.
    """

    def english_description(name: str) -> str | None:
        return language_map(lookup.find(name + DESCRIPTION_SUFFIX))["en"]

    ingredient_configs = dict(dict_pairs(data, "dictIngredientConfigs"))
    ingredients = [
        {
            "name": name,
            "is_tag": False,
            "tags": config["lstTag"],
            "auto_unlock": config["autoUnlock"],
            "description": english_description(name),
            "image": ingredient_images.get(name),
        }
        for name, config in ingredient_configs.items()
    ]

    # A tag means "any ingredient that carries it" and recipes list it like an ingredient, so it gets its own entry
    tag_members = dict_pairs(data, TAG_FIELD)
    clash = sorted(set(ingredient_configs) & {tag for tag, _ in tag_members})
    if clash:
        raise ValueError(f"These names are both an ingredient and a tag: {clash}")
    tag_priorities = dict(dict_pairs(data, TAG_PRIORITY_FIELD))
    for tag, members in tag_members:
        ingredients.append(
            {
                "name": tag,
                "is_tag": True,
                "tags": [],
                "auto_unlock": None,  # tags have no unlock setting of their own
                "description": english_description(tag),
                "image": ingredient_images.get(tag),
                "members": members,
                "priority": tag_priorities.get(tag),
            }
        )

    recipes: list[dict[str, Any]] = []
    for field, category in RECIPE_FIELDS.items():
        for _, recipe in dict_pairs(data, field):
            recipes.append(
                {
                    "name": recipe["name"],
                    "category": category,
                    "dish_type": recipe["dishType"],
                    "ingredients": recipe["lstIngredients"],
                    "description": english_description(recipe["name"]),
                    "image": recipe_images.get(recipe["name"]),
                }
            )

    # Every name the data refers to: ingredients, tags, recipes and the entries of each recipe
    names: list[str] = list(ingredient_configs)
    names += [tag for config in ingredient_configs.values() for tag in config["lstTag"]]
    names += [tag for tag, _ in dict_pairs(data, "dicTagIngredients")]
    for recipe in recipes:
        names.append(recipe["name"])
        names += recipe["ingredients"]

    # Both parts always have the 15 language codes; a missing text is None
    translations = {
        name: {
            "name": language_map(lookup.find(name)),
            "description": language_map(lookup.find(name + DESCRIPTION_SUFFIX)),
        }
        for name in dict.fromkeys(names)
    }
    return recipes, ingredients, translations


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_file", type=Path, nargs="?", default=Path("data/src/cozy-kitchen.data.br"))
    # The default folder name "ouput" matches the existing project folder
    parser.add_argument("--out-dir", type=Path, default=Path("data/ouput"), help="where the JSON files are written")
    parser.add_argument("--images-dir", type=Path, default=Path("data/images"), help="where the PNG images are written")
    parser.add_argument(
        "--bundles-dir",
        type=Path,
        default=Path("data/bundles"),
        help="folder with the downloaded Addressable bundles (dish images)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("data/unpacked"),
        help="keep the unpacked game files here (default: a temporary folder)",
    )
    args = parser.parse_args()

    print(f"[1/7] Reading {args.data_file}")
    raw = load_web_data(args.data_file)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        work_dir = args.work_dir or Path(temp_dir)
        print(f"[2/7] Unpacking into {work_dir}")
        unpack_web_data(raw, work_dir)

        print(f"[3/7] Looking for the {RECIPE_SCRIPT_NAME} object")
        assets = GameAssets(work_dir)
        blob = find_recipe_blob(assets)
        print(f"      found a {len(blob)} byte blob")

        print("[4/7] Parsing the Odin data")
        data = parse_odin(blob)

        # Collections
        menu_data = parse_odin(find_menu_blob(assets))

        print("[5/7] Reading the I2 Localization terms")
        anchor = dict_pairs(data, "dicNormalRecipe")[0][0]
        layout, terms = find_localization_terms(assets, anchor)

        print("[6/7] Exporting the images")
        ingredient_names = [name for name, _ in dict_pairs(data, "dictIngredientConfigs")]
        tag_names = [tag for tag, _ in dict_pairs(data, TAG_FIELD)]
        recipe_names = [recipe["name"] for field in RECIPE_FIELDS for _, recipe in dict_pairs(data, field)]
        # Tags are listed like ingredients, so their icons are exported into the same folder in the same pass
        game_index = index_images(assets.env)
        game_index.update({normalize(tag): [icon] for tag, icon in find_tag_icons(assets, data).items()})
        ingredient_images = export_images(game_index, ingredient_names + tag_names, args.images_dir, "ingredients")
        recipe_images: dict[str, str] = {}
        if args.bundles_dir:
            bundles = UnityPy.load(str(args.bundles_dir))
            recipe_images = export_images(index_images(bundles), recipe_names, args.images_dir, "recipes")
        else:
            print("      no --bundles-dir given: the recipe images are skipped")
        del assets  # release the unpacked files before the temporary folder is removed

    vietnamese_index = find_vietnamese_index(terms)
    print(f"      {len(terms)} terms, Vietnamese is language #{vietnamese_index}, record layout {layout}")
    expected_index = [code for _, code in LANGUAGE_CODES].index("vi")
    if vietnamese_index != expected_index:
        raise LookupError(
            f"Vietnamese was found in column {vietnamese_index}, but LANGUAGE_CODES expects it in column "
            f"{expected_index}. Fix the order of LANGUAGE_CODES."
        )
    column_counts = Counter(len(translations) for _, translations in terms)
    if set(column_counts) != {len(LANGUAGE_CODES)}:
        print(f"      WARNING: expected {len(LANGUAGE_CODES)} languages per term, got {dict(column_counts)}")

    print("[7/7] Writing the JSON files")
    lookup = TermLookup(terms)
    recipes, ingredients, translations = build_outputs(data, lookup, ingredient_images, recipe_images)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "recipes.json", recipes)
    write_json(args.out_dir / "ingredients.json", ingredients)
    write_json(args.out_dir / "translations.json", translations)
    write_json(args.out_dir / "collections.json", build_menu_collections(menu_data, lookup))

    per_category = Counter(recipe["category"] for recipe in recipes)
    print(f"Done -> {args.out_dir}")
    print(f"  recipes.json: {len(recipes)} recipes {dict(per_category)}")
    tag_count = sum(1 for ingredient in ingredients if ingredient["is_tag"])
    print(f"  ingredients.json: {len(ingredients) - tag_count} ingredients + {tag_count} tags")
    described_names = sum(1 for entry in translations.values() if any(entry["description"].values()))
    print(f"  translations.json: {len(translations)} entries, {described_names} with a description")
    print(
        f"  images in {args.images_dir}: {len(ingredient_images)}/{len(ingredients)} ingredients and tags, "
        f"{len(recipe_images)}/{len(recipes)} recipes"
    )
    no_image = [name for name in ingredient_names + tag_names if name not in ingredient_images]
    if no_image:
        print(f"  ingredients and tags without an image: {no_image[:MAX_EXAMPLES]}")
    if args.bundles_dir:
        no_image = [name for name in dict.fromkeys(recipe_names) if name not in recipe_images]
        if no_image:
            print(f"  recipes without an image ({len(no_image)}): {no_image[:MAX_EXAMPLES]}")

    missing = [name for name, entry in translations.items() if not any(entry["name"].values())]
    if missing:
        print(f"  {len(missing)} names have no translation (all null), e.g. {missing[:MAX_EXAMPLES]}")
    described_recipes = sum(1 for recipe in recipes if recipe["description"])
    described_ingredients = sum(1 for ingredient in ingredients if ingredient["description"])
    print(
        f"  descriptions found: {described_recipes}/{len(recipes)} recipes, "
        f"{described_ingredients}/{len(ingredients)} ingredients"
    )
    known = {name.lower() for name in translations}
    unmatched = [key for key in lookup.description_keys() if key[: -len(DESCRIPTION_SUFFIX)].lower() not in known]
    print(f"  {len(lookup.description_keys())} description keys in the game, {len(unmatched)} not matching any name")
    if unmatched:
        print(f"  e.g. {unmatched[:MAX_EXAMPLES]}")


if __name__ == "__main__":
    main()
