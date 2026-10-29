# cozy-kitchen wiki data

Bộ script trích xuất dữ liệu của game **cozy-kitchen** (Unity 6 WebGL, chơi trên CrazyGames) để làm wiki công thức:
công thức, nguyên liệu, tên và mô tả bằng 15 ngôn ngữ, các bộ sưu tập menu và hình ảnh.

> **Bản quyền:** dữ liệu và hình ảnh thuộc về nhà phát triển game. Nếu đăng wiki công khai, hãy ghi rõ nguồn
> và cân nhắc xin phép nhà phát triển.

## Cấu trúc dự án

```
.
├── index.html                  giao diện chính
├── styles.css
├── scripts.js
├── run.sh                      chạy cả quy trình
├── build_image_bundles.py      bước 1: build các image bundle từ catalog.bin
├── download_bundles.py         bước 2: tải các bundle
├── extract_cozy_kitchen.py     bước 3: trích xuất dữ liệu ra JSON và ảnh
├── README.md
└── data/
    ├── src/
    │   └── catalog.bin    đầu vào, file catalog dùng để lấy bundles
    │   └── cozy-kitchen.data.br    đầu vào, tự tải từ game (xem bên dưới)
    ├── bundles/                    các bundle ảnh đã tải
    ├── images/
    │   ├── ingredients/            ảnh nguyên liệu
    │   ├── recipes/                ảnh món ăn
    │   └── menu_collections/       ảnh huy hiệu và ảnh splash của từng menu
    └── ouput/                      các file JSON đầu ra
        ├── recipes.json
        ├── ingredients.json
        ├── translations.json
        └── menu_collections.json
```

Tên thư mục đầu ra là `ouput` (đúng như mặc định hiện tại của `extract_cozy_kitchen.py`). Muốn đổi, dùng `--out-dir`.

## Yêu cầu

- Python **3.10 trở lên**.
- `pip install brotli UnityPy` (UnityPy kéo theo Pillow và các thư viện giải mã texture).
- `build_image_bundles.py` và `download_bundles.py` có thể cần thêm thư viện: xem các dòng `import` ở đầu mỗi file.
- Có kết nối mạng: để tải bundle (bước 2) và để tải bảng menu từ Google Sheets (bước 3).

## Chuẩn bị đầu vào

Hai file sau không tự tải được, bạn lấy thủ công từ trình duyệt:

1. **`data/src/cozy-kitchen.data.br`**: mở game, F12 → tab **Network**, tải lại trang, tìm file `<hash>.data.br` trong
   thư mục `Build` của game rồi lưu vào đường dẫn trên. File này có thể đã được trình duyệt giải nén sẵn, script xử lý
   được cả hai trường hợp. Khi game cập nhật, tên file (hash) đổi và nội dung cũng đổi, nên cần tải lại.
2. **`catalog.bin`**: file catalog mà `build_image_bundles.py` đọc. Vị trí và tên file theo cách script đó được viết.

## Cách chạy

```bash
chmod +x run.sh      # chỉ cần làm một lần

./run.sh             # chạy cả 3 bước: build, download, extract
./run.sh extract     # chỉ chạy bước 3
./run.sh build download
./run.sh --help
```

`run.sh` kiểm tra từng bước trước khi chạy và dừng ngay khi có lỗi. Nếu thư mục bundle chưa có hoặc đang trống, bước
`extract` vẫn chạy nhưng bỏ qua ảnh món ăn và ảnh menu (field `image` là `null`).

Cấu hình bằng biến môi trường (đều không bắt buộc):

| Biến            | Ý nghĩa                                                     | Mặc định                       |
| --------------- | ----------------------------------------------------------- | ------------------------------ |
| `PYTHON`        | lệnh Python dùng để chạy                                    | `python3`                      |
| `DATA_FILE`     | file `.data.br` của game                                    | `data/src/cozy-kitchen.data.br` |
| `BUNDLES_DIR`   | thư mục bundle, truyền cho `extract` qua `--bundles-dir`    | `data/bundles`                 |
| `BUILD_ARGS`    | tham số thêm cho `build_image_bundles.py`                   | (trống)                        |
| `DOWNLOAD_ARGS` | tham số thêm cho `download_bundles.py`                      | (trống)                        |
| `EXTRACT_ARGS`  | tham số thêm cho `extract_cozy_kitchen.py`                  | (trống)                        |

Ví dụ:

```bash
EXTRACT_ARGS="--out-dir data/output" ./run.sh extract
```

`BUNDLES_DIR` phải trùng với thư mục mà `download_bundles.py` lưu bundle. Nếu script đó có tham số riêng cho thư mục
lưu, truyền qua `DOWNLOAD_ARGS`.

## Luồng xử lý

```
catalog.bin ──► build_image_bundles.py ──► download_bundles.py ──► data/bundles/ ──┐
                                                                                    ▼
data/src/cozy-kitchen.data.br ───────────────────────────────────► extract_cozy_kitchen.py
                                                                                    │
                                              data/ouput/*.json  ◄──────────────────┤
                                              data/images/**     ◄──────────────────┘
```

Tham số chi tiết của hai bước đầu: `python build_image_bundles.py --help` và `python download_bundles.py --help`.

## Dữ liệu đầu ra

### `recipes.json`

| Field         | Ý nghĩa                                                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------- |
| `name`        | tên món (tiếng Anh), cũng là khóa để tra `translations.json`                                          |
| `category`    | `normal`, `dark_cuisine` hoặc `messy` (nhóm công thức trong dữ liệu game)                            |
| `dish_type`   | số tương ứng với nhóm trên: 0, 1, 2                                                                  |
| `ingredients` | danh sách tên nguyên liệu **hoặc tên tag** (công thức `messy` dùng tag như `Cheeses`, `Creepy`)       |
| `description` | mô tả tiếng Anh, `null` nếu không có                                                                 |
| `image`       | đường dẫn ảnh, `null` nếu không có ảnh                                                               |

```json
{
    "name": "Boiled Egg",
    "category": "normal",
    "dish_type": 0,
    "ingredients": ["Egg"],
    "description": "...",
    "image": "images/recipes/boiled_egg.png"
}
```

### `ingredients.json`

| Field         | Ý nghĩa                                       |
| ------------- | --------------------------------------------- |
| `name`        | tên nguyên liệu                               |
| `tags`        | các tag (nhóm) của nguyên liệu, ví dụ `Eggs`  |
| `auto_unlock` | nguyên liệu có tự mở khóa hay không           |
| `description` | mô tả tiếng Anh, `null` nếu không có          |
| `image`       | đường dẫn ảnh, `null` nếu không có ảnh        |

### `translations.json`

Khóa là tên tiếng Anh của mọi tên mà dữ liệu nhắc tới: nguyên liệu, tag, món ăn và các mục nằm trong
`ingredients` của công thức. Mỗi mục có tên và mô tả bằng 15 ngôn ngữ; bản dịch thiếu là `null`.

```json
{
    "Egg": {
        "name": { "en": "Egg", "vi": "Trứng", "id": "...", "...": "..." },
        "description": { "en": "...", "vi": "...", "...": "..." }
    }
}
```

Thứ tự và mã ngôn ngữ: `en`, `vi`, `id`, `ms`, `th`, `ru`, `hi`, `de`, `fr`, `es`, `it`, `tr`, `ko`, `ja`, `zh`.

### `menu_collections.json`

Các bộ sưu tập món (menu). Dữ liệu lấy từ một Google Sheet (CSV) mà game tải lúc chạy; địa chỉ của sheet nằm trong
dữ liệu game, script tự tải về.

| Field                  | Ý nghĩa                                                                         |
| ---------------------- | ------------------------------------------------------------------------------- |
| `id`                   | mã menu, ví dụ `menu_001`                                                        |
| `name`, `description`  | tên và mô tả tiếng Anh                                                           |
| `sort_order`           | thứ tự hiển thị                                                                  |
| `available_quest`      | số quest liên quan đến việc mở menu (ý nghĩa suy ra từ tên cột)                  |
| `quest_phase`          | giá trị cột `Quest Phase` của sheet (`Quest Reward` hoặc `Quest Gift`)           |
| `story_unlock`         | vật phẩm mở khóa theo cốt truyện                                                 |
| `reward_type`, `reward_id` | phần thưởng của menu, ví dụ `Badge` và `badge_001`                           |
| `required_ingredients` | nguyên liệu và dụng cụ cần có                                                    |
| `recipes`              | các món thuộc menu (tên khớp với `recipes.json` khi tìm được)                    |
| `key_name`, `key_desc` | khóa của tên và mô tả trong bảng dịch                                            |
| `translations`         | `{"name": {...}, "description": {...}}` bằng 15 ngôn ngữ                         |
| `images`               | `{"badge": ..., "splash": ...}`: đường dẫn ảnh, `null` nếu không có              |

File này chỉ được tạo khi tải được sheet. Nếu không có mạng, xem phần xử lý sự cố.

### Ảnh

- `data/images/ingredients/*.png`: lấy từ chính file `.data.br`.
- `data/images/recipes/*.png` và `data/images/menu_collections/*.png`: lấy từ các bundle (cần `--bundles-dir`).
- Tên file là tên đã bỏ dấu, viết thường, nối bằng `_` (ví dụ `olive_oil.png`). Trùng tên thì thêm `_2`.
- Đường dẫn trong JSON (ví dụ `images/ingredients/egg.png`) tính từ **thư mục cha của thư mục ảnh**, tức là từ `data/`.

## `extract_cozy_kitchen.py`

```
python extract_cozy_kitchen.py [data_file] [--out-dir DIR] [--images-dir DIR]
                               [--bundles-dir DIR] [--menu-csv FILE] [--work-dir DIR]
```

| Tham số         | Mặc định                       | Ý nghĩa                                                           |
| --------------- | ------------------------------ | ----------------------------------------------------------------- |
| `data_file`     | `data/src/cozy-kitchen.data.br` | file `.data.br` của game                                          |
| `--out-dir`     | `data/ouput`                   | nơi ghi các file JSON                                             |
| `--images-dir`  | `data/images`                  | nơi ghi ảnh PNG                                                   |
| `--bundles-dir` | (không có)                     | thư mục bundle đã tải; không có thì bỏ qua ảnh món ăn và ảnh menu |
| `--menu-csv`    | (tải từ Google Sheets)         | dùng bản CSV đã lưu thay vì tải                                   |
| `--work-dir`    | (thư mục tạm)                  | giữ lại các file game đã giải nén ở đây                           |

Các bước script thực hiện:

1. Đọc `.data.br` và giải nén Brotli (bỏ qua nếu file đã được giải nén).
2. Tách kho `UnityWebData` thành các file.
3. Tìm object `DataRecipe` theo tên class script.
4. Đọc dữ liệu công thức và nguyên liệu (định dạng Odin Serializer).
5. Đọc bảng dịch I2 Localization: mỗi term là một khóa tiếng Anh kèm 15 bản dịch. Mô tả của `X` được lấy từ khóa `X desc`.
6. Tải và đọc bảng menu.
7. Xuất ảnh PNG.
8. Ghi các file JSON và in thống kê cuối lần chạy.

Cuối mỗi lần chạy, script in số công thức, nguyên liệu, số mô tả và ảnh tìm được, cùng danh sách các tên thiếu
bản dịch hoặc thiếu ảnh. Hãy đọc phần này để biết dữ liệu đã đầy đủ chưa.

## Lưu ý và giả định

- Hai cột "Telur" trong bảng dịch giống nhau; thứ tự Indonesian (`id`) rồi Malay (`ms`) là giả định. Nếu sai, đổi chỗ
  hai mã trong hằng `LANGUAGE_CODES` của `extract_cozy_kitchen.py`. Script có kiểm tra cột tiếng Việt và sẽ dừng nếu
  thứ tự không khớp.
- Mô tả được ghép theo quy tắc khóa `<tên> desc`; dòng thống kê cuối lần chạy cho biết có bao nhiêu mô tả khớp.
- Ảnh món ăn và ảnh menu giả định rằng trong bundle ảnh là Texture2D hoặc Sprite mang đúng tên món (hoặc
  `menu_001_badge`, `menu_001_splash`).
- Nguyên liệu không có khóa riêng trong bảng dịch (ví dụ chỉ có `Eggs` chứ không có `Egg`) sẽ có bản dịch toàn `null`.

## Xử lý sự cố

| Thông báo                                                | Cách xử lý                                                                              |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `Missing packages. Run: pip install brotli UnityPy`      | cài thư viện như thông báo                                                              |
| `data/src/cozy-kitchen.data.br not found`                 | lưu file `.data.br` của game vào đúng đường dẫn, hoặc đặt biến `DATA_FILE`              |
| `No DataRecipe object found`                             | game có thể đã đổi định dạng; kiểm tra lại file `.data.br` đã tải đúng chưa              |
| `Could not read the I2 Localization terms`               | game đổi định dạng bảng dịch; script in kèm một đoạn hexdump, gửi đoạn đó để sửa script |
| `Vietnamese was found in column N`                       | sai thứ tự `LANGUAGE_CODES`, sửa lại theo cột mà thông báo nêu                           |
| `could not download the menu collections`                | không có mạng: mở link của sheet trong trình duyệt, lưu CSV rồi chạy với `--menu-csv`    |
| `recipes without an image`                               | thiếu bundle: tải thêm bundle vào `BUNDLES_DIR` rồi chạy lại                            |
| `could not decode N images`                              | có texture ở định dạng nén chưa giải mã được; xem danh sách ví dụ in ra kèm lỗi         |

## Khi game cập nhật

Tải lại `cozy-kitchen.data.br` (và `catalog.bin` nếu đổi), xóa hoặc làm mới thư mục `data/bundles`, rồi chạy lại
`./run.sh`.
