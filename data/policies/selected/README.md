# 已选解析文档

本目录只放已经确认要进入 RAG 的解析文档，默认由 `scripts/build_chunks.py` 读取。

当前共 7 篇：

- `RET-return-shipping-CSV.md`：退货运费标准，CSV 系列规范版本
- `LOG-delivery-sla-CSV.md`：配送时效标准，CSV 系列规范版本
- `PRI-price-protection-window-CSV.md`：价保期限表，CSV 系列规范版本
- `TRD-trade-in-valuation-CSV.md`：以旧换新估价表，CSV 系列规范版本
- `INV-invoice-types-CSV.md`：发票类型对比表，CSV 系列规范版本
- `TRD-recycle-receipt-scan-PDF.md`：以旧换新回收单扫描件，PDF 为 JPG 的规范版本
- `PLT-platform-notice-scan-PDF.md`：平台规则变更公告扫描件，PDF 为 JPG 的规范版本

## 选择原则

- CSV 作为表格的规范版本，跳过对应 XLSX。
- 扫描 PDF 作为扫描件的规范版本，跳过对应 JPG。
- HTML 与 CSV 重复时跳过 HTML。
- 文本 PDF、DOCX、PNG 暂不并入，避免和现有政策 Markdown 重复。

## 重新生成

```powershell
./.venv/Scripts/python.exe scripts/generate_policy_docs.py
./.venv/Scripts/python.exe scripts/parse_policy_raw.py --ocr
./.venv/Scripts/python.exe scripts/select_policy_parsed.py
./.venv/Scripts/python.exe scripts/build_chunks.py
./.venv/Scripts/python.exe scripts/embed_and_ingest.py --prune
```

`manifest.json` 记录每篇文档的 `doc_id`、原始文件、格式和选择原因。
