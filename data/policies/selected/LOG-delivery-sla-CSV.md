---
doc_id: RAW-TBL-LOG-delivery-sla-CSV
product_id: STORE
title: 配送时效标准（CSV 解析）
doc_type: store_policy
category: 物流
source: 烬狐官方店铺政策（模拟）·解析
authority_level: 高
version: v1
effective_date: 2026-01-01
valid_until: 2026-12-31
deprecated: false
policy_domain: 物流
region: 全国
scope: 店铺
source_file: data/policies/raw/tables/LOG-delivery-sla.csv
source_format: CSV
parser: csv
parsed_at: 2026-10-25
---

# 配送时效标准

## 表格内容

| 区域 | 预计时效 | 承运商 | 说明 |
|---|---|---|---|
| 珠三角 | 1 天 | 迅风快递 | 深圳仓发货 |
| 长三角 | 2 天 | 迅风快递 | 武汉/天津仓发货 |
| 京津冀 | 2 天 | 迅风快递 | 天津仓发货 |
| 华中/华南 | 2–3 天 | 迅风快递 | 按就近仓分配 |
| 西南/西北 | 3–5 天 | 迅风快递/云链物流 | 部分区域转云链 |
| 偏远地区 | 5–7 天 | 云链物流 | 以物流揽收为准 |
| 港澳台/海外 | 暂不支持 | — | 不发货 |

## 来源说明

本文件由 `data/policies/raw/tables/LOG-delivery-sla.csv`（CSV）解析生成，解析器为 csv，解析时间 2026-10-25。原始文件属于物流领域，适用范围为全国，生效日期 2026-01-01，失效日期 2026-12-31。解析结果仅用于本地 RAG 演示，具体条款以原始文件和店铺最新公告为准。
