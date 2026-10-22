from pathlib import Path

from models import Ingredient

# Folder containing the ingredient images
IMAGE_DIR = Path("data/ingredients")
# Output file for the generated data
INGREDIENT_JSON_FILE = Path("data/json/ingredients.json")


def main() -> None:
    """Main function"""
    if not IMAGE_DIR.is_dir():
        raise SystemExit(f"Folder not found: {IMAGE_DIR}")

    ingredients = Ingredient.build_ingredients(IMAGE_DIR)
    Ingredient.update_ingredients(ingredients, INGREDIENT_JSON_FILE)
    # Ingredient.update_fields(INGREDIENT_JSON_FILE, INGREDIENT_JSON_UPDATE_FILE)
    print(f"Saved {len(ingredients)} ingredients to {INGREDIENT_JSON_FILE}")


if __name__ == "__main__":
    main()
