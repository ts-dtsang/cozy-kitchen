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
    # Ingredient.update_ingredients(ingredients, INGREDIENT_JSON_FILE)
    # Ingredient.update_fields(INGREDIENT_JSON_FILE, INGREDIENT_JSON_UPDATE_FILE)
    ingredients = Ingredient.load_ingredients(INGREDIENT_JSON_FILE)
    names = {i.id: i.en_name for i in ingredients if i.id not in [59, 60]}
    print(names)
    print(f"Saved {len(ingredients)} ingredients to {INGREDIENT_JSON_FILE}")


if __name__ == "__main__":
    main()
