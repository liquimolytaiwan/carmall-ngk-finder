# CarMall 火星塞快速查詢

機車廠牌 → 車款 → （年份）→ NGK 火星塞規格 + 一鍵購買。純靜態，放 GitHub Pages，用 iframe 內嵌到
carmall.com.tw。做法與 [carmall-wiper-finder](https://github.com/liquimolytaiwan/carmall-wiper-finder)
相同，但資料來源是結構化 API，不需人工判讀。

## 資料流

```
NGK 台灣官網 /api/*  ──fetch_ngk.py──►  tools/ngk_raw_moto.json  ┐
                                                                 ├─build_data.py─► data.json
CarMall Cyberbiz /products/*.json ─fetch_products.py─► tools/ngk_products.json ┘
```

**NGK 適應表**（`ngksparkplugs.com.tw`）背後是四支無需驗證的 POST 端點：

| 端點 | 參數 | 回傳 |
|---|---|---|
| `/api/carbrand` | `cartype`（1=汽車 2=機車） | JSON 廠牌清單 |
| `/api/carmodel` | `carbrand`（廠牌 id） | JSON `"車款 / 排氣量"` 字串陣列 |
| `/api/caryear` | `modelname`, `displacement` | JSON 年份陣列 |
| `/api/finder` | `carbrand`, `modelname`, `displacement`, `caryear` | **HTML 片段**（每個引擎一列） |

伺服器限流 **60 req/min**，`fetch_ngk.py` 因此每次請求間隔 1.15 秒；整份機車資料約 420 次請求、8 分鐘。
`/api/finder` 回的是 HTML，欄位會隨 cartype 改變（汽車有 Premium RX / IX MAX，機車有 MOTO DX），
所以解析是讀每個 `<td>` 的 `data-th` 屬性，不靠欄位順序。

**CarMall 商品**走 Cyberbiz 公開 JSON（無金鑰、**無 CORS 標頭**，所以只能在建置時抓，不能前端即時抓）。
每個火星塞商品都是單一 variant，且 **variant 的 `sku` 就是 NGK 料號**（例：`CR7HDX-S`），
因此兩邊是精確 join，不需要模糊比對。

## 目前涵蓋範圍（2026-08-05）

只做**機車**（Jerry 指定）—— CarMall 目前只賣 NGK MotoDX 摩托車釕合金火星塞 12 個料號，汽車火星塞未上架。

- 9 廠牌 / 202 車款 / 212 個車款年份組合
- **175 個（82.5%）推薦料號有現貨可直接導購**
- 37 個（17.5%）NGK 根本沒出 MotoDX 規格（多為大排氣量跑車），顯示規格＋導客服
- **零缺口**：沒有任何一台是「NGK 有出 MotoDX、但店裡沒進貨」

> ⚠️ 進了貨但 NGK 台灣資料庫沒有任何車對應到的 3 個料號：
> `CPR6EDX-9S`、`CR8EHDX-9S`、`CR9EHDX-9S`

**鐵律：不做替代料號推測。** 查不到 MotoDX 就誠實顯示「此車款 NGK 未推出 MotoDX 規格」並導客服，
不拿熱值相近的塞硬湊 —— 火星塞熱值/牙距裝錯會傷引擎。

## 檔案

| 檔案 | 用途 |
|---|---|
| `index.html` / `styles.css` / `app.js` | 前端（無框架、無外部依賴） |
| `data.json` | 建置產出，前端唯一資料來源 |
| `tools/fetch_ngk.py` | 抓 NGK 適應表 → `ngk_raw_moto.json` |
| `tools/fetch_products.py` | 抓 CarMall 價格庫存 → `ngk_products.json` |
| `tools/build_data.py` | join 兩者 → `data.json` |
| `embed-snippet.html` | 貼到 Cyberbiz 的內嵌碼（含 iframe 自動高度） |
| `.github/workflows/refresh-data.yml` | 每日更新價格庫存；每週一另外重抓 NGK 適應表 |

## 常用指令

```bash
# 只更新價格/庫存（快，約 15 次請求）
python3 tools/fetch_products.py && python3 tools/build_data.py

# 重抓 NGK 適應表（慢，約 8 分鐘）
python3 tools/fetch_ngk.py --cartype 2 --out tools/ngk_raw_moto.json

# 本機預覽
python3 -m http.server 8777    # 開 http://127.0.0.1:8777/

# 手動觸發雲端更新
gh workflow run refresh-data.yml -R liquimolytaiwan/carmall-ngk-finder
gh workflow run refresh-data.yml -R liquimolytaiwan/carmall-ngk-finder -f recrawl_ngk=true
```

## UI 決策

NGK 的年份欄位對機車多半是空的（214 筆裡 144 筆是 `-----`，203 個車款裡 193 個只有一個年份選項），
所以**第 3 步「年份」只在真的有兩個以上選項時才出現**，不讓使用者點一個沒有意義的下拉。

## 部署

GitHub Pages，`main` 根目錄，帳號 **liquimolytaiwan**（推送前 `gh auth switch -u liquimolytaiwan`），
commit email 用 `manhowtrading@gmail.com`。
