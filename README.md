# CarMall 火星塞快速查詢

機車廠牌 → 車款 → 出廠年份 → NGK 火星塞規格 + 一鍵購買。純靜態，放 GitHub Pages，用 iframe 內嵌到
carmall.com.tw。做法與 [carmall-wiper-finder](https://github.com/liquimolytaiwan/carmall-wiper-finder)
相同。

## 為什麼要看年份（2026-08-06 改版的原因）

NGK 台灣官網 `/api/finder` 對機車幾乎不給年份（214 筆裡 144 筆是 `-----`），所以**同一車款中途換過
料號的車，只會吐一支**。實例：

| 車款 | 出廠年份 | 正確料號 |
|---|---|---|
| Yamaha MT-03 | 2015/10 – 2018/03 | `CR8EDX-S` |
| Yamaha MT-03 | 2018/03 起 | `LMAR8ADX-9S` |

舊版查詢器只給後期的 `LMAR8ADX-9S`，前期車主照著裝就是錯的。**印刷版原廠型錄有這些年份斷點**，
所以現在以型錄為主資料源。全表共 **32 個車系**存在這種年份分歧（MT-03、YZF-R3、MT-25、YZF-R25、
PCX、PCX150、Dio110、CB125R、Monkey125、Super Cub C125、GSX1300R 隼、V-Strom 等）。

## 三個資料源與優先序

```
tools/source/ngk_book_2223.pdf  p129-200 ─parse_catalog.py──► tools/ngk_catalog_moto.json ┐
tools/source/{kymco,sym,yamaha}_dx.xlsx ─parse_tw_tables.py─► tools/ngk_tw_tables.json    ├─build_data.py─► data.json
NGK 台灣官網 /api/*             ─────────fetch_ngk.py───────► tools/ngk_raw_moto.json      │
CarMall Cyberbiz /products/*.json ───────fetch_products.py──► tools/ngk_products.json     ┘
```

| 優先序 | 來源 | 有年份 | 為什麼排這個位置 |
|---|---|---|---|
| 1 | **NGK 原廠車款對照表**（日本 ブック式適応表 22-23） | ✅ | 唯一有年份斷點的來源 |
| 2 | **台灣機種別 MOTO DX 對照表**（CarMall 提供 xlsx） | ❌ | 台灣專屬速可達，日本型錄根本沒有 |
| 3 | **NGK 台灣官網 API** | ❌ | 補前兩者都沒有的車；也是**支數**的唯一來源 |

**後面的來源只會「補車」，不會覆蓋前面的答案。** 判斷是不是同一台車看
`build_data.match_key()`：括號、標點、中文別名、`ABS`／`碟煞`／`仕樣` 這類配備字尾都會被抹掉，
但兩件事一定保留 ——

- **排氣量**：同名不同 cc 就是不同車。`MT-03` 有 320 與 660(平輸) 兩台、`NMAX` 有 125 與台灣 155，
  料號不同，不能互相蓋掉。
- **世代標記**（`六期`／`七期`／`水冷`／`1~5代`）：這些**會換料號**。光陽 MANY 110 六期是
  `CR7EDX-S`、七期是 `CPR7EDX-9S`；山葉勁戰 1~5 代是 `CR7EDX-S`、水冷六代是 `CPR8EDX-9S`。
  把它們當同一台車會直接製造出這次要修的那個 bug。

名字差太多、`match_key` 認不出來的同一台車（例：台灣「野狼T2 250」＝型錄「T2 250」），寫在
`build_data.TW_SAME_AS_CATALOG` 明列，不靠放寬比對 —— 放寬過的版本把「勁風光」和
「Cygnus-GRYPHUS」、「JOG 125」和「JOG 50」merge 在一起，那比多一筆重複嚴重得多。

### 型錄怎麼解析

`-layout` 純文字會因為 CJK 全形寬度塌掉而對不齊，而且**排氣量欄只印在每個排氣量分組的第一列**，
光看 token 順序分不出「這是排氣量還是車名」。所以 `parse_catalog.py` 走
`pdftotext -bbox-layout` 讀每個字的座標，逐頁校準「車名欄」的 x 位置；三組火星塞欄位則從**右邊
往左**吃，因為車名是唯一的自由欄位而且永遠在最左。`――` = 這條產品線沒出，`―` = 沒有庫存編號。

解析器**寧可失敗也不寫半份檔**：任何一頁抽不到列、總列數低於門檻、或有表格列解析不出來，就
`exit 1`。少抓幾列不會報錯，只會讓那些車默默變成「查無此車」。

### 車名在地化

型錄是日本國內版，車名印的是「シグナスX」「スーパーカブ110」「アドレスV125」。`tools/model_names.py`
把 335 個假名車名對到台灣人認得的寫法（Cygnus X 勁戰／Super Cub 110／Address V125），日文原名
一律保留顯示在結果頁，隨時可以跟印刷頁對帳。

**查不到官方拉丁名的就不硬翻**，列在 `UNMAPPED_ON_PURPOSE` 保持日文原樣 —— 在挑引擎零件的人面前
擺一個自己編的車名，比擺日文原名糟。

### 支數不猜

三張台灣 xlsx 只有料號沒有支數，而支數會直接影響「共 N 支 $X」的報價與能不能湊成一套。所以支數
只從有寫的來源查（`api_plug_counts()`），查不到就是 `null`，前端改顯示「請依引擎缸數選購數量」，
不會印一個猜出來的「此車需 1 支」。目前 27 台是這個狀態。

## 目前涵蓋範圍（2026-08-06）

- 27 廠牌 / **799 車款** / 864 個車款年份組合（改版前：9 廠牌 202 車款）
- 原廠型錄 660 車款 ／ 台灣對照表 81 ／ 台灣官網 58
- **863 個組合可直接導購**，1 個現貨不足
- 型錄裡出現的 MotoDX 料號**剛好就是店裡進的 12 支，一支不多一支不少**
  （順帶解掉舊版的懸案：`CPR6EDX-9S`、`CR8EHDX-9S`、`CR9EHDX-9S` 在型錄裡都有對應車款，
  只是 NGK 台灣資料庫沒有）

**沒有 MotoDX 的車不收錄**（Jerry 指定）—— 店裡只賣 MotoDX，型錄裡沒出 MotoDX 的車放進來也沒東西賣。

**鐵律：不做替代料號推測。** 不拿熱值相近的塞硬湊 —— 熱值/牙距裝錯會傷引擎。

### 已知待確認

- `NEW MANY 125(六期)`：台灣對照表寫 `CPR7EDX-9S`、NGK 台灣官網寫 `CR8EDX-S`。目前依優先序採用
  對照表；build 時會印 ⚠ 提醒。
- 27 台查不到支數（多為單缸速可達，但沒有來源明講，所以不寫死）。

## 檔案

| 檔案 | 用途 |
|---|---|
| `index.html` / `styles.css` / `app.js` | 前端（無框架、無外部依賴） |
| `data.json` | 建置產出，前端唯一資料來源 |
| `tools/parse_catalog.py` | 解析原廠型錄 PDF → `ngk_catalog_moto.json` |
| `tools/model_names.py` | 日文車名 → 台灣車名對照表 |
| `tools/parse_tw_tables.py` | 解析台灣 xlsx → `ngk_tw_tables.json` |
| `tools/fetch_ngk.py` | 抓 NGK 台灣官網 → `ngk_raw_moto.json` |
| `tools/fetch_products.py` | 抓 CarMall 價格庫存 → `ngk_products.json` |
| `tools/build_data.py` | 合併四者 → `data.json` |
| `embed-snippet.html` | 貼到 Cyberbiz 的內嵌碼（含 iframe 自動高度） |
| `.github/workflows/refresh-data.yml` | 每日更新價格庫存；每週一另外重抓 NGK 台灣官網 |

### 原始檔在哪裡

`tools/source/` **不進 repo**（見 `.gitignore`）—— 這個 repo 是公開的、而且會被 GitHub Pages 直接
serve，型錄 PDF 是有版權的出版品。要重跑解析器的話把檔案放回去：

| 檔案 | 來源 |
|---|---|
| `tools/source/ngk_book_2223.pdf` | Google Drive：`260312 NGK_車款對照表 PACJA-010_ 22-23 ブック式適応表` |
| `tools/source/{kymco,sym,yamaha}_dx.xlsx` | CarMall 提供的機種別 MOTO DX 對照表 |

解析產出的 JSON 有進 repo，所以 CI 不需要原始檔也能跑每日的價格庫存更新。

## 常用指令

```bash
# 只更新價格/庫存（快，約 15 次請求）
python3 tools/fetch_products.py && python3 tools/build_data.py

# 重新解析型錄與台灣對照表（需要 tools/source/ 的原始檔）
python3 tools/parse_catalog.py && python3 tools/parse_tw_tables.py && python3 tools/build_data.py

# 重抓 NGK 台灣官網（慢，約 8 分鐘，限流 60 req/min）
python3 tools/fetch_ngk.py --cartype 2 --out tools/ngk_raw_moto.json

# 本機預覽
python3 -m http.server 8777    # 開 http://127.0.0.1:8777/

# 手動觸發雲端更新
gh workflow run refresh-data.yml -R liquimolytaiwan/carmall-ngk-finder
gh workflow run refresh-data.yml -R liquimolytaiwan/carmall-ngk-finder -f recrawl_ngk=true
```

## UI 決策

- **年份只在真的有兩個以上選項時才出現。** 多數車只有一組適用資料，每台都逼使用者點一次年份，
  會訓練出「隨便點過去」的習慣 —— 而那個步驟正是有年份分歧那 32 個車系的救命關卡。
- **料號相同的相鄰年份會合併成一段**（`merge_runs()`）。型錄只要任一欄變動就切一列，所以會出現
  兩列只差在銥合金料號、MotoDX 完全一樣的情形；讓使用者在兩個結果相同的年份之間選，等於把真正
  重要的年份稀釋成雜訊。
- **來源會寫在結果頁。** 非型錄來源的車會明講「未區分出廠年份」並提醒對照車主手冊 —— 這正是這次
  改版要修的失效模式，不能只在自己知道的地方修掉。

## 部署

GitHub Pages，`main` 根目錄，帳號 **liquimolytaiwan**（推送前 `gh auth switch -u liquimolytaiwan`），
commit email 用 `manhowtrading@gmail.com`。
