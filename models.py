import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Self


@dataclass(slots=True, kw_only=True)
class Ingredient:
    """Represents a single ingredient in the wiki."""

    id: int
    vn_name: str
    en_name: str
    description: str
    image: str
    made_from: list[str] = field(default_factory=list)
    vn_made_from: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalize a saved null to an empty list
        if self.made_from is None:
            self.made_from = []
        if self.vn_made_from is None:
            self.vn_made_from = []

    @classmethod
    def build_ingredients(cls, image_dir: Path) -> list[Self]:
        """Scan a folder for .png files and build one Ingredient per file."""
        # Sort for a stable, predictable order
        png_files = sorted(
            (p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"),
            key=lambda p: p.name.lower(),
        )

        return [
            cls(
                id=index,
                vn_name="",  # To be filled in later
                en_name=cls._get_en_name(path),
                description="",  # To be filled in later
                image=path.as_posix(),
                made_from=[],  # To be filled in later
            )
            for index, path in enumerate(png_files, start=1)
        ]

    @classmethod
    def load_ingredients(cls, json_file: Path) -> list[Self]:
        """Load existing ingredients from the JSON file (empty list if missing or blank)."""
        if not json_file.is_file():
            return []

        text = json_file.read_text(encoding="utf-8")
        if not text.strip():
            return []

        try:
            return [cls(**item) for item in json.loads(text)]
        except json.JSONDecodeError as e:
            print(f"JSON parsing failed, rebuilding from scratch: {e.msg}")
            return []

    @classmethod
    def update_ingredients(cls, ingredients: list[Self], output_file: Path) -> None:
        """Add ingredients whose image is not in the JSON file yet, keeping saved data and ids."""
        # Read the current data as raw dicts so nothing already saved is altered
        existing: list[Self] = cls.load_ingredients(output_file)
        existing_map = {item.image: item for item in existing}
        next_id = max((item.id for item in existing), default=0) + 1

        data = []
        for ingredient in ingredients:
            if ingredient.image in existing_map:
                ent = existing_map[ingredient.image]
            else:
                ent = ingredient
                ent.id = next_id
                next_id += 1
            data.append(asdict(ent))

        # Write to a temp file first, then replace, so a crash mid-write cannot corrupt the original
        temp_file = output_file.with_suffix(".json.tmp")
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(output_file)

    @classmethod
    def fill_missing_fields(cls, data: list[dict]) -> list[dict]:
        """Add every model field that is missing from an entry, with a value of None."""
        field_names = [f.name for f in fields(cls)]
        # dict.fromkeys gives each model field a None default; the entry's own values override it
        return [{**dict.fromkeys(field_names), **item} for item in data]

    @classmethod
    def update_fields(cls, input_file: Path) -> None:
        """Update fields"""
        ingredients = cls.load_ingredients(input_file)
        existing = [asdict(item) for item in ingredients]
        data = cls.fill_missing_fields(existing)

        temp_file = input_file.with_suffix(".json.tmp")
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(input_file)

    @staticmethod
    def _get_en_name(filepath: Path) -> str:
        """Get ingredient name from file path, e.g. '01_olive_oil.png' -> 'Olive Oil'."""
        parts = filepath.stem.split("_")
        # Fall back to the whole name when there is no prefix to drop
        return " ".join(parts[1:] or parts).title()
