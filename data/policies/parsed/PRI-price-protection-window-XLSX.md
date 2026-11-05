---
doc_id: RAW-TBL-PRI-price-protection-window-XLSX
product_id: STORE
title: 价格保护期限表（XLSX 解析）
doc_type: store_policy
category: 价格保护
source: 烬狐官方店铺政策（模拟）·解析
authority_level: 高
version: v1
effective_date: 2026-01-01
valid_until: 2026-12-31
deprecated: false
policy_domain: 价格保护
region: 全国
scope: 店铺
source_file: data/policies/raw/tables/PRI-price-protection-window.xlsx
source_format: XLSX
parser: openpyxl
parsed_at: 2026-10-25
duplicate_of: RAW-TBL-PRI-price-protection-window-CSV
---

# 价格保护期限表

## 价保期限表

| 用户类型 | 价保天数 | 适用商品 | 说明 |
|---|---|---|---|
| 普通用户 | 7 天 | 店铺在售商品 | 签收次日起算 |
| 星潮会员 | 15 天 | 店铺在售商品 | 需在会员有效期内 |
| 秒杀/清仓 | 不适用 | — | 活动价不参与价保 |
| 以旧换新订单 | 不适用 | — | 按以旧换新规则处理 |

## 来源说明

本文件由 `data/policies/raw/tables/PRI-price-protection-window.xlsx`（XLSX）解析生成，解析器为 openpyxl，解析时间 2026-10-25。原始文件属于价格保护领域，适用范围为全国，生效日期 2026-01-01，失效日期 2026-12-31。解析结果仅用于本地 RAG 演示，具体条款以原始文件和店铺最新公告为准。
