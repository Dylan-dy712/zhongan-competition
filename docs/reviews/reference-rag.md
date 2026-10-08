# 暖暖语气与参考知识 RAG

2026-10-08 用户明确要求将提供的专业书籍、刊物知识用于 RAG，不以现有“待审核”标记阻断参考检索。此授权用于一般知识引用；原条目状态和原有正式报告审核规则保持原值，不伪造审核人或医学批准。

当前检索库由599条版本化医护知识与14章费用、发票知识编译出的136个片段组成。费用源文件保存在 docs/medical/费用与发票知识库；运行 `python -m scripts.build_rag_corpus` 重建 contracts/knowledge/rag-cost-chunks.jsonl 及 SHA256 清单。启动检索时校验知识库原有 SHA256 和费用片段清单，内容或引用版本变化时拒绝旧引用。

检索采用中文双字/三字与英文词的 BM25，加本地中文向量与 RRF 排名合并。病种筛选和既有适用范围排除约束两路召回；返回最多6个相关片段，生成最多引用4条。关键词提供术语匹配，向量补充口语和近义表达；不是医疗判断模型。

已知病种时将病种名加入短问题的语义上下文，不把“出院后怎么养”无条件当成任何疾病。向量有效时以达到余弦相似度门槛的候选作为相关性过滤，BM25 排名参与其排序；无相关候选则不引用知识。阈值是有限问法样例上的工程筛选，不是医疗准确性概率。

向量使用固定版本 BAAI/bge-small-zh-v1.5（512维），通过 FastEmbed/ONNX 在 CPU 本地运行，不调用外部 embedding API。公开模型文件固定到 Qdrant 仓库提交 46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59，contracts/knowledge/embedding-model.json 保存各文件 SHA256，初始化时验证。知识库版本、模型提交和分段方式共同标识索引。长条目用带重叠的小段完整生成向量，召回合并回原始知识条目，出处保持原值。

PostgreSQL pgvector 用余弦距离进行精确检索；当前规模无需近似索引。索引构建在事务内发布，保留旧版本以便代码回退；运行时核对条目和向量总数，不使用未完成或版本不符的索引。向量不可用时明确记录 vector_status 并继续 BM25，不让知识检索中断对话。

部署准备：先在 PostgreSQL 安装 pgvector 并由管理员创建 public.vector 扩展，安装 services/api/requirements-rag.txt。运行 `python -m scripts.prepare_embedding_model --cache-dir /home/ubuntu/zhongan-data/embeddings` 下载校验模型；服务器不能访问源时，可在能访问官方仓库的机器运行，再传送固定提交目录。部署脚本在迁移后运行 `python -m scripts.build_knowledge_vectors`，成功后才启动启用 ZHONGAN_RAG_ENABLED=1 的服务。更新知识后自动重建当前语料版本，模型文件不在聊天请求期间下载。

普通聊天按问题调用 search_knowledge；材料解读在已授权原文读取后检索相关知识。用户病历事实和一般知识分开引用，原文对照阶段保留 general_knowledge 标记。知识不能证明本人的诊断、药物适应证、用药调整或保险赔付。检索失败或无命中时回到已有材料，不编造知识依据。

模型只能引用实际检索返回的 entry_id，后端校验引用及版本，并将真实出处元数据写入回答。聊天与材料解读下方提供折叠的“参考知识与出处”。旧回答没有知识字段时仍能显示。

语气由 CARE_VOICE 的完整倾诉与费用对话示例、材料解读的完整口述示例共同引导。医嘱自然说成“医生在出院时交代了”，不要求每句重复“出院记录写到”；通俗表达保留疑似、否定、阶段和金额原标签。

2026-10-09 真实本地模型与隔离 PostgreSQL schema 验证：735个原始条目形成787个向量段；12个固定口语问题按预设相关主题检查前4个结果，BM25命中7个、混合检索命中11个。三项天气/菜谱/物理无关问法均不返回知识。热模型检索约16–27毫秒（不含模型回答）；本次首轮生成约65秒。样例集用于回归，不代表普遍命中率；骨折脚趾麻木问题仍未在前4条召回预设S9危险信号主题。相关依据：pgvector官方文档 https://github.com/pgvector/pgvector ，FastEmbed官方模型表 https://qdrant.github.io/fastembed/examples/Supported_Models/ 。
