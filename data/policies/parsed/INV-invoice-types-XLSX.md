---
doc_id: RAW-TBL-INV-invoice-types-XLSX
product_id: STORE
title: 发票类型对比表（XLSX 解析）
doc_type: store_policy
category: 发票
source: 烬狐官方店铺政策（模拟）·解析
authority_level: 高
version: v1
effective_date: 2026-01-01
valid_until: 2026-12-31
deprecated: false
policy_domain: 发票
region: 全国
scope: 店铺
source_file: data/policies/raw/tables/INV-invoice-types.xlsx
source_format: XLSX
parser: openpyxl
parsed_at: 2026-10-25
duplicate_of: RAW-TBL-INV-invoice-types-CSV
---

# 发票类型对比表

## 发票类型对比表

| 发票类型 | 适用对象 | 税率 | 开具时限 | 说明 |
|---|---|---|---|---|
| 电子普通发票 | 个人/企业 | 13% | 1–3 个工作日 | 默认开具，可下载 PDF |
| 增值税专用发票 | 企业一般纳税人 | 13% | 3–7 个工作日 | 需上传资质并邮寄 |
| 电子发票（个人） | 个人 | 13% | 1–3 个工作日 | 抬头为个人姓名 |
| 红字发票 | 退货/换开 | 13% | 3–7 个工作日 | 需先完成退款或换开审核 |

## 来源说明

本文件由 `data/policies/raw/tables/INV-invoice-types.xlsx`（XLSX）解析生成，解析器为 openpyxl，解析时间 2026-10-25。原始文件属于发票领域，适用范围为全国，生效日期 2026-01-01，失效日期 2026-12-31。解析结果仅用于本地 RAG 演示，具体条款以原始文件和店铺最新公告为准。
