# Cozy Kitchen Wiki

Bộ công cụ trích xuất công thức, nguyên liệu, bản dịch (15 ngôn ngữ) và hình ảnh từ game **Cozy Kitchen** (Unity WebGL).

* **Demo / Build:** [ts-dtsang.github.io/cozy-kitchen](https://ts-dtsang.github.io/cozy-kitchen/)
* **Local:** python3 -m http.server 8090
  * http://localhost:8090/

---

## 📁 Cấu trúc thư mục

```text
.
├── index.html, styles.css, scripts.js   # Giao diện hiển thị
├── run.sh                               # Script chạy toàn bộ pipeline
├── build_image_bundles.py               # B1: Lấy danh sách bundle từ catalog
├── download_bundles.py                  # B2: Tải asset bundles
├── extract_cozy_kitchen.py              # B3: Trích xuất JSON & ảnh
└── data/
    ├── src/                             # [Đầu vào thủ công]
    │   ├── catalog.bin                  # Catalog bundle
    │   └── cozy-kitchen.data.br         # Asset data chính của game
    ├── bundles/                         # Bundle tải về (ảnh recipes, menus)
    ├── images/                          # Ảnh PNG sau trích xuất
    └── ouput/                           # JSON kết quả
        ├── recipes.json
        ├── ingredients.json
        ├── translations.json
        └── menu_collections.json
```

---

## ⚙️ Yêu cầu & Cài đặt

- **Python**: `>= 3.10`
- **Thư viện**:
  ```bash
  pip install -r requirements.txt
  ```

---

## 📥 Chuẩn bị dữ liệu đầu vào

1. `data/src/cozy-kitchen.data.br`: File build chính (`<hash>.data.br`).
2. `data/src/catalog.bin`: File catalog dùng để tải bundle.

---

## 🚀 Hướng dẫn chạy

```bash
chmod +x run.sh

# Chạy toàn bộ quy trình (B1 → B3)
./run.sh

# Hoặc chạy lẻ từng bước
./run.sh extract
./run.sh build download
```

### Biến môi trường tùy chọn

| Biến | Mặc định | Mô tả |
| :--- | :--- | :--- |
| `DATA_FILE` | `data/src/cozy-kitchen.data.br` | Đường dẫn file data |
| `BUNDLES_DIR` | `data/bundles` | Nơi lưu / đọc bundle |
| `EXTRACT_ARGS` | *(trống)* | Tham số thêm cho bước trích xuất (vd: `--out-dir data/output`) |

*Ví dụ:*
```bash
EXTRACT_ARGS="--out-dir data/output" ./run.sh extract
```

---

## 📊 Dữ liệu đầu ra (`data/ouput/`)

- **`recipes.json`**: Món ăn (`name`, `category`, `dish_type`, `ingredients`, `image`).
- **`ingredients.json`**: Nguyên liệu (`name`, `tags`, `auto_unlock`, `image`).
- **`translations.json`**: Bản dịch tên và mô tả bằng 15 ngôn ngữ (`en`, `vi`, `id`, `ms`, `th`, `ru`, `hi`, `de`, `fr`, `es`, `it`, `tr`, `ko`, `ja`, `zh`).
- **`menu_collections.json`**: Thông tin bộ sưu tập món từ Google Sheet.
- **`data/images/`**: Toàn bộ icon nguyên liệu (`ingredients/`), món ăn (`recipes/`) và huy hiệu/ảnh menu (`menu_collections/`).

---

## ⚠️ Xử lý sự cố nhanh

- **Thiếu ảnh món/menu**: Kiểm tra lại bước tải bundle (`download_bundles.py`) vào `data/bundles/`.
- **Lỗi tải Google Sheet (`could not download...`)**: Tải CSV thủ công rồi truyền cờ `--menu-csv <file.csv>` vào script trích xuất.
- **Game cập nhật**: Tải lại `cozy-kitchen.data.br` & `catalog.bin`, dọn thư mục `data/bundles/`, sau đó chạy lại `./run.sh`.
