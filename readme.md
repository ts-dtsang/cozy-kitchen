# Cozy Kitchen Wiki

A toolkit for extracting recipes, ingredients, translations (15 languages), and images from the game **Cozy Kitchen** (Unity WebGL).

* **Demo / Build:** [ts-dtsang.github.io/cozy-kitchen](https://ts-dtsang.github.io/cozy-kitchen/)
* **Local Preview:** `python3 -m http.server 8090`
  * [http://localhost:8090/](http://localhost:8090/)

---

## 📁 Project Structure

```text
.
├── index.html, styles.css, scripts.js   # Web UI
├── run.sh                               # Pipeline runner script
├── build_image_bundles.py               # Step 1: Parse bundle list from catalog
├── download_bundles.py                  # Step 2: Download asset bundles
├── extract_cozy_kitchen.py              # Step 3: Extract JSON data and images
└── data/
    ├── src/                             # [Manual inputs]
    │   ├── catalog.bin                  # Bundle catalog
    │   └── cozy-kitchen.data.br         # Game asset data
    ├── bundles/                         # Downloaded asset bundles (recipes, collections)
    ├── images/                          # Extracted PNG images
    └── ouput/                           # Generated JSON outputs
        ├── recipes.json
        ├── ingredients.json
        ├── translations.json
        └── menu_collections.json
```

---

## ⚙️ Requirements & Installation

- **Python**: `>= 3.10`
- **Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```

---

## 📥 Input Files Preparation

Download the following two files manually via your browser's Developer Tools (Press `F12` → **Network** tab while loading the game):

1. `data/src/cozy-kitchen.data.br`: Main build asset file (`<hash>.data.br`).
2. `data/src/catalog.bin`: Catalog file used to resolve asset bundles.

---

## 🚀 Usage

```bash
chmod +x run.sh

# Run the complete pipeline (Steps 1 → 3)
./run.sh

# Or run individual steps
./run.sh extract
./run.sh build download
```

### Optional Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DATA_FILE` | `data/src/cozy-kitchen.data.br` | Path to the game data file |
| `BUNDLES_DIR` | `data/bundles` | Directory to store/load downloaded bundles |
| `EXTRACT_ARGS` | *(empty)* | Extra arguments passed to the extraction script (e.g., `--out-dir data/output`) |

*Example:*
```bash
EXTRACT_ARGS="--out-dir data/output" ./run.sh extract
```

---

## 📊 Extracted Outputs (`data/ouput/`)

- **`recipes.json`**: Dish recipes (`name`, `category`, `dish_type`, `ingredients`, `image`).
- **`ingredients.json`**: Ingredients & ingredient tags (`name`, `tags`, `auto_unlock`, `image`).
- **`translations.json`**: Multilingual names and descriptions across 15 languages (`en`, `vi`, `id`, `ms`, `th`, `ru`, `hi`, `de`, `fr`, `es`, `it`, `tr`, `ko`, `ja`, `zh`).
- **`menu_collections.json`**: Menu collections data fetched from the game's Google Sheets source.
- **`data/images/`**: Extracted PNG icons for ingredients (`ingredients/`), recipes (`recipes/`), and menu badges/splash art (`menu_collections/`).

---

## ⚠️ Troubleshooting

- **Missing recipe or menu images**: Ensure bundles were downloaded properly into `data/bundles/` via `download_bundles.py`.
- **Google Sheet download error (`could not download...`)**: Save the sheet as a CSV file manually and supply it with `--menu-csv <file.csv>`.
- **Game updates**: Re-download `cozy-kitchen.data.br` and `catalog.bin`, clear or update `data/bundles/`, then rerun `./run.sh`.
