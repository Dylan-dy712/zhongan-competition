# P0：费用行列绑定

依赖材料路由PR。新增单元格验证：明确名称列、唯一行总金额列、相同单行行号、原文名称和金额一致时才标verified_cells。跨行名称/金额直接拒绝；合并金额、表头歧义或OCR与视觉不一致标visual_review_required，不能因为模型自报高置信度就放行。

每条费用保存binding_status、binding_reason、source_row和原source_cells。不按名称去重。未验证的批次进入局部视觉恢复；仍未验证时记录unresolved，整个文档标partial。

通用OCR后，仅明确费用清单/结算候选可请求第二遍表格识别。API显式设置ZHONGAN_TABLE_OCR=1启用；评测命令使用preliminary_ocr --auto-table。默认不增加收费调用。失败保留通用OCR及降级状态，不自动切换供应商。原通用文字不被表格OCR覆盖，表格单元格保存在页metadata/评测缓存中。

腾讯表格置信度保留原始单元格值，传给通用页解析器的行分数统一到0至1；供应方分数不等于识别正确概率。

验证：19项已有worker/文档检查通过；在既有真实表格缓存上执行源行验证。没有新鲜表格服务效果或全量KR1提升结论；Paddle表格解析尚未成为生产依赖。没有新增或编辑测试。
