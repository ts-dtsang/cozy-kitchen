"""Extract recipes and ingredients from the cozy-kitchen Unity WebGL data file.

Pipeline: .data.br -> decompress -> unpack the UnityWebData archive -> find the DataRecipe object
-> parse its Odin-serialized blob -> write recipes.json and game_ingredients.json.

Requirements: pip install brotli UnityPy
"""

import argparse
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

import brotli
import UnityPy

WEB_DATA_MAGIC = b"UnityWebData1.0\x00"
RECIPE_SCRIPT_NAME = "DataRecipe"
BLOB_HEAD_MARKER = "dictIngredientConfigs".encode("utf-16-le")
BLOB_HEAD_SIZE = 64
MONOBEHAVIOUR_HEADER_SIZE = 28  # m_GameObject (12) + m_Enabled (4) + m_Script (12)

# Recipe dictionary field -> category label written to recipes.json
RECIPE_FIELDS = {
    "dicNormalRecipe": "normal",
    "dicDarkCuisineRecipe": "dark_cuisine",
    "dicMessyRecipe": "messy",
}

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
# Step 3: find the DataRecipe ScriptableObject and cut out its serialized blob
# ---------------------------------------------------------------------------
def align4(value: int) -> int:
    """Round up to the next multiple of 4 (Unity pads serialized strings to 4 bytes)."""
    return (value + 3) & ~3


def read_blob(raw: bytes) -> bytes:
    """Skip the MonoBehaviour header and return the large Odin byte array."""
    pos = MONOBEHAVIOUR_HEADER_SIZE
    name_len = struct.unpack_from("<i", raw, pos)[0]
    pos = align4(pos + 4 + name_len)
    _, blob_len = struct.unpack_from("<ii", raw, pos)  # (format field, byte array length)
    pos += 8
    return raw[pos : pos + blob_len]


def find_recipe_blob(asset_dir: Path) -> bytes:
    """Locate the DataRecipe MonoBehaviour by its script class name and return its Odin blob."""
    env = UnityPy.load(str(asset_dir))

    # Map MonoScript path id -> class names (path ids can collide across serialized files)
    script_names: dict[int, set[str]] = {}
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            script_names.setdefault(obj.path_id, set()).add(obj.read().m_ClassName)

    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = obj.get_raw_data()
        if len(raw) < MONOBEHAVIOUR_HEADER_SIZE:
            continue

        # The m_Script PPtr starts at offset 16: int32 file id + int64 path id
        _, script_path_id = struct.unpack_from("<iq", raw, 16)
        if RECIPE_SCRIPT_NAME not in script_names.get(script_path_id, set()):
            continue

        try:
            blob = read_blob(raw)
        except (struct.error, ValueError):
            continue
        # Guard against path id collisions: the real blob starts with this field name
        if BLOB_HEAD_MARKER in blob[:BLOB_HEAD_SIZE]:
            return blob

    raise LookupError(f"No {RECIPE_SCRIPT_NAME} object found. The game may have changed its data format.")


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


# ---------------------------------------------------------------------------
# Step 5: build the output files
# ---------------------------------------------------------------------------
def dict_pairs(data: dict[str, Any], field: str) -> list[tuple[str, Any]]:
    """Return the (key, value) pairs of a serialized Dictionary field."""
    value = data[field]
    items = value["_items"] if isinstance(value, dict) else value
    return [(pair["$k"], pair["$v"]) for pair in items]


def build_outputs(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn the parsed data into (recipes, ingredients) lists."""
    ingredient_configs = dict(dict_pairs(data, "dictIngredientConfigs"))
    ingredients = [
        {"name": name, "tags": config["lstTag"], "auto_unlock": config["autoUnlock"]}
        for name, config in ingredient_configs.items()
    ]

    recipes: list[dict[str, Any]] = []
    for field, category in RECIPE_FIELDS.items():
        for _, recipe in dict_pairs(data, field):
            recipes.append(
                {
                    "name": recipe["name"],
                    "category": category,
                    "dish_type": recipe["dishType"],
                    "ingredients": recipe["lstIngredients"],
                }
            )
    return recipes, ingredients


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_file", type=Path, nargs="?", default=Path("data/br/cozy-kitchen.data.br"))
    parser.add_argument("--work-dir", type=Path, default=Path("unpacked"), help="where the archive is unpacked")
    parser.add_argument("--out-dir", type=Path, default=Path("data/ouput"), help="where the JSON files are written")
    args = parser.parse_args()

    print(f"[1/5] Reading {args.data_file}")
    raw = load_web_data(args.data_file)

    print(f"[2/5] Unpacking into {args.work_dir}")
    unpack_web_data(raw, args.work_dir)

    print(f"[3/5] Looking for the {RECIPE_SCRIPT_NAME} object")
    blob = find_recipe_blob(args.work_dir)
    print(f"      found a {len(blob)} byte blob")

    print("[4/5] Parsing the Odin data")
    data = parse_odin(blob)

    print("[5/5] Writing JSON files")
    recipes, ingredients = build_outputs(data)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "recipes.json", recipes)
    write_json(args.out_dir / "game_ingredients.json", ingredients)

    per_category = Counter(recipe["category"] for recipe in recipes)
    print(f"Done: {len(recipes)} recipes {dict(per_category)}, {len(ingredients)} ingredients -> {args.out_dir}")


if __name__ == "__main__":
    main()
