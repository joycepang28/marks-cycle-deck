# 霍华德·马克斯 市场周期仪表盘

基于霍华德·马克斯《最重要的事》投资哲学，追踪六大市场的估值与情绪周期定位。

**公开链接（无需账号）：** https://joycepang28.github.io/marks-cycle-deck/

---

## 市场覆盖

| 市场 | 指数 | 阶段判断依据 |
|------|------|-------------|
| 🇺🇸 美国 | S&P 500 | TTM PE、恐贪指数（CNN FGI）|
| 🇸🇬 新加坡 | STI | TTM PE、价格动量 RSI(14) |
| 🇭🇰 香港 | 恒生指数 | TTM PE、VHSI 波动率指数 |
| 🇯🇵 日本 | 日经 225 | TTM PE、NKVI 波动率指数 |
| 🇲🇾 马来西亚 | FBM KLCI | TTM PE、价格动量 RSI(14) |
| 🇨🇳 中国 A 股 | 中证 500 | TTM PE（CSIndex 官方汇总法）、价格动量 RSI(14) |

---

## 数据来源与抓取方式

所有抓取逻辑集中在 `fetch_market_data.py`，每周一 09:00 SGT 由 GitHub Actions 自动运行。

### 指数点位

| 市场 | 来源 | 方法 |
|------|------|------|
| US / SG / HK / JP | [CNBC Quote API](https://www.cnbc.com/quotes/.SPX) | 解析 `"last":` 字段 |
| CN（中证 500） | [东方财富 push2 API](https://push2.eastmoney.com/) | `secid=1.000905`，字段 `f43/100` |
| MY（FBM KLCI） | [i3investor.com](https://klse.i3investor.com/web/index/market-index) | HTML 解析 `<strong>` 标签 |

### 年初涨跌（YTD）

通过东方财富 kline API 获取年初首个交易日收盘价，再与当前点位计算涨跌幅。

### TTM PE / 5年均值 / 10年均值

| 市场 | 来源 | 说明 |
|------|------|------|
| US / SG / HK / JP / MY | [worldperatio.com](https://worldperatio.com/) | HTML 解析 `P/E Ratio`、`5Y Average`、`10Y Average` |
| CN（中证 500） | [AkShare](https://akshare.akfamily.xyz/) `stock_zh_index_value_csindex` | **见下方专项说明** |

### 美股 CAPE

来源：[multpl.com](https://www.multpl.com/shiller-pe)，解析 `id="current-value"`。

---

## 情绪指标说明

> **统一约定（所有市场进度条方向一致）：**
> 所有情绪进度条均遵循「左红=恐慌/超卖，右绿=贪婪/平静」的方向。
> VHSI / NKVI 属于波动率指数（高 = 恐慌），标记位置已做反转处理，使视觉方向与 CNN FGI / RSI 保持一致。

### 🇺🇸 美股 — CNN 恐贪指数（Fear & Greed Index）

- **来源：** [alternative.me API](https://api.alternative.me/fng/?limit=1)
- **范围：** 0（极度恐慌）→ 100（极度贪婪）
- **更新频率：** 日频
- **进度条颜色：** 左红（恐慌）→ 橙（中性）→ 右绿（贪婪）
- **数据字段：** 存储为 `fgi`，标记位置 = 原始值%

---

### 🇸🇬 新加坡 — 价格动量 RSI(14)

> **为什么不用 MacroMicro SG Fear & Greed Index？**
>
> MacroMicro 提供 [MM Singapore Fear & Greed Index](https://en.macromicro.me/series/46957/singapore-mm-fear-and-greed-index)，综合了价格动量、成交量、波动率和广度指标，是最理想的新加坡情绪代理。但 MacroMicro 对服务器端请求全部返回 HTTP 403，无法在 GitHub Actions 中自动抓取。

**当前替代方案：STI RSI(14)**

- **来源：** Yahoo Finance `^STI`，通过 [yfinance](https://github.com/ranaroussi/yfinance) 获取近 3 个月日线
- **计算方式：**
  ```
  RSI(14) = 100 - 100 / (1 + 过去14日平均涨幅 / 过去14日平均跌幅)
  ```
- **范围：** 0–100（与 FGI 同向）
  - `< 30` → 超卖 / 市场悲观
  - `30–70` → 中性动量
  - `> 70` → 超买 / 市场乐观
- **局限性：**
  - RSI 仅反映价格动量，不包含成交量、波动率、市场广度等维度
  - 趋势性市场中 RSI 可长期维持高位，不代表顶部
  - 建议结合卡片上的 TTM PE 与 PE 历史均值综合判断
- **进度条颜色：** 左红（超卖）→ 橙（中性）→ 右绿（超买），与美股 FGI 同向
- **数据字段：** 存储为 `fgi`，与美股共用同一渲染逻辑

**如果 MacroMicro 开放 API 访问（或有合法 cookie/token），可替换 `fetch_sg_rsi()` 为直接请求：**
```
https://en.macromicro.me/series/46957/singapore-mm-fear-and-greed-index
```

---

### 🇭🇰 香港 — VHSI 恒生波动率指数

- **来源：** [CNBC Quote API](https://www.cnbc.com/quotes/VHSI)，解析 `"last":` 字段
- **定义：** 基于恒指期权隐含波动率，方法论与美国 VIX 相同，由恒生指数公司发布
- **范围显示：** 10（历史低位 / 极度平静）→ 60（历史高位 / 极度恐慌）
- **进度条颜色方向：与 FGI 一致** — 左红（高波动 = 恐慌）→ 右绿（低波动 = 平静）
- **标记位置计算：** `left = 100% - (VHSI - 10) / 50 × 100%`（高值 → 偏左红区）
- **标签顺序（左→右）：** `60 恐慌 | 40 紧张 | 25 正常 | 10 平静`
- **历史参考：** 正常区间约 15–28；新冠疫情峰值约 80
- **注意：** Yahoo Finance `^VHSI.HK` 已下架，不可用；东方财富 secid 亦无数据；仅 CNBC 可稳定获取

---

### 🇯🇵 日本 — NKVI 日经波动率指数

- **来源：** Yahoo Finance `^NKVI.OS`，通过 yfinance `fast_info.last_price` 获取
- **定义：** 基于大阪交易所日经 225 期权隐含波动率
- **范围显示：** 10 → 60（与 VHSI 同标准）
- **进度条颜色方向：与 VHSI / FGI 一致** — 左红（高波动 = 恐慌）→ 右绿（低波动 = 平静）
- **标记位置计算：** `left = 100% - (NKVI - 10) / 50 × 100%`（同 VHSI）
- **标签顺序（左→右）：** `60 恐慌 | 40 紧张 | 25 正常 | 10 平静`
- **历史参考：** 10 年范围约 13–71；正常区间约 15–30

---

### 🇲🇾 马来西亚 — 价格动量 RSI(14)

- **来源：** Yahoo Finance `^KLSE`，通过 yfinance 获取近 3 个月日线
- **计算方式：** 与 SG RSI 完全相同
  ```
  RSI(14) = 100 - 100 / (1 + 过去14日平均涨幅 / 过去14日平均跌幅)
  ```
- **范围：** 0–100（`< 30` 超卖 / `30–70` 中性 / `> 70` 超买）
- **进度条方向：** 左红（超卖）→ 右绿（超买），与其他市场一致
- **数据字段：** 存储为 `fgi`
- **选择该指标的原因：** 马来西亚无官方 VIX 类波动率指数；`^KLSE` 是 Yahoo Finance 上 FBM KLCI 的标准代码，数据稳定可用

---

### 🇨🇳 中国 A 股 — 价格动量 RSI(14)

- **来源：** AkShare `stock_zh_index_daily(symbol='sh000905')` 获取中证500全历史日线
- **计算方式：**
  ```
  RSI(14) = 100 - 100 / (1 + 过去14日平均涨幅 / 过去14日平均跌幅)
  ```
- **范围：** 0–100（`< 30` 超卖 / `30–70` 中性 / `> 70` 超买）
- **进度条方向：** 左红（超卖）→ 右绿（超买），与其他市场一致
- **数据字段：** 存储为 `fgi`
- **选择该指标的原因：** Yahoo Finance `000905.SS` 与 `399905.SZ` 均无历史日线可用；AkShare `sh000905` 数据完整，含 5000+ 交易日，可靠性高

---

## 中证 500 PE 口径专项说明

中证 500 TTM PE 有多种口径，差异较大，特此说明：

| 来源 | 口径 | 当前值（2026-04） | 说明 |
|------|------|-----------------|------|
| **CSIndex 官方**（本项目采用） | 汇总法 TTM PE | ~32× | 指数总市值 ÷ 成分股 TTM 净利润合计；由中证指数公司官方发布 |
| 理杏仁（lixinger.com） | 市值加权，剔除亏损股 | ~36× | 剔除负 PE 公司后加权，分母偏小，PE 偏高 |
| 乐估乐股（legulegu） | 市值加权滚动 PE | ~29× | 含负 PE 公司，分母偏大，PE 偏低 |
| worldperatio.com/area/china/ | 全 A 股市场 PE | ~10× | **❌ 错误** — 返回全体 A 股，非中证 500 |

**本项目数据抓取：**
- 当前 PE：`AkShare.stock_zh_index_value_csindex(symbol="000905")` → `市盈率2` 字段
- 历史均值（5Y / 10Y）：`AkShare.stock_index_pe_lg(symbol="中证500")` → 静态市盈率，按 CSIndex 当前值进行口径校正

---

## 自动更新工作流

```
.github/workflows/deploy.yml
```

| 步骤 | 说明 |
|------|------|
| **触发条件** | 每周一 01:00 UTC（09:00 SGT）、push to main、手动触发 |
| **Job 1: fetch-data** | 运行 `fetch_market_data.py`，更新 `index.html` 中的数值字段，如有变更则 commit 到 main |
| **Job 2: deploy** | 构建独立 HTML（内联 Chart.js，移除 Google Fonts CDN），部署到 `gh-pages` 分支 |

**更新的字段（按市场）：**

```
us:  level, ytd, ttmPE, pe5y, pe10y, cape, fgi
sg:  level, ytd, ttmPE, pe5y, pe10y, fgi (RSI-14)
hk:  level, ytd, ttmPE, pe5y, pe10y, vix (VHSI)
jp:  level, ytd, ttmPE, pe5y, pe10y, vix (NKVI)
my:  level, ytd, ttmPE, pe5y, pe10y, fgi (RSI-14)
cn:  level, ytd, ttmPE, pe5y, pe10y, fgi (RSI-14)
```

---

## 本地开发

```bash
# 克隆仓库
git clone https://github.com/joycepang28/marks-cycle-deck.git
cd marks-cycle-deck

# 安装依赖（数据抓取脚本）
pip install yfinance akshare requests beautifulsoup4

# 手动抓取最新数据（会直接写入 index.html）
python fetch_market_data.py

# 在浏览器预览
open index.html
```

---

## 文件结构

```
marks-cycle-deck/
├── index.html              # 主仪表盘（含 base64 图表，约 2.3MB）
├── fetch_market_data.py    # 数据抓取脚本（每周 GitHub Actions 调用）
├── fetch_summary.json      # 上次抓取摘要（date + fields_updated）
├── build_standalone.py     # 构建脚本：内联依赖，移除外部 CDN
└── .github/
    └── workflows/
        └── deploy.yml      # 自动更新 + 部署工作流
```

---

## 免责声明

本仪表盘仅供学习研究，基于霍华德·马克斯公开演讲及著作《The Most Important Thing》整理，**不构成投资建议**。数据来源均为公开渠道，可能存在延迟或误差，请以各市场官方数据为准。
