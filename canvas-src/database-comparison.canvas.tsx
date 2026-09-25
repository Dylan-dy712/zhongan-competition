import { Stack, Row, H1, H2, Text, Table, Callout, Pill, Button, Link, Divider, useState, useHostTheme, useCanvasAction } from "cursor/canvas";

const scenarios = [
  { label: "团队熟悉 MySQL", title: "优先 MySQL（InnoDB）", reason: "已有经验或环境可以减少学习与排错成本；原生 JSON、事务与关系建模足以支撑本题。", check: "确认 JSON 查询索引、迁移、事务和恢复测试；不要混入 PostgreSQL 专用 SQL。" },
  { label: "两者都不偏好", title: "保留 PostgreSQL 默认方案", reason: "沿用 V3，关系字段与 JSONB 并存，适合逐步扩展医疗结构化结果的查询。不是无条件性能冠军。", check: "确认部署责任人；只对实际高频查询建立索引，避免过度设计。" },
  { label: "单机离线演示", title: "SQLite 可以胜任低写入并发原型", reason: "不需要独立数据库服务；适合一台电脑、短事务、可排队写入的演示。", check: "明确单写者边界、每连接启用外键、验证备份；若最终主库不同，仍需最终引擎集成测试。" }
];

const rows = [
  ["运行方式", "独立数据库服务", "独立数据库服务", "嵌入应用、本机文件"],
  ["项目角色", "共享业务主库候选", "共享业务主库候选", "单机低写入并发原型候选"],
  ["JSON", "JSON / JSONB；可设计 JSONB 索引", "原生 JSON；生成列等索引路径", "JSON 函数；新版有自己的 JSONB"],
  ["并发写入", "多事务；仍需处理锁与重试", "InnoDB 多事务；仍需处理锁与重试", "同一数据库同一时刻一个写者"],
  ["完整性", "事务与关系约束", "InnoDB 事务与关系约束", "事务；外键须每连接确认开启"],
  ["费用表示建议", "整数分或明确精度的定点数", "整数分或明确精度的定点数", "优先整数分，勿假定 DECIMAL 等价"],
  ["团队协作", "独立开发库 + 统一迁移", "独立开发库 + 统一迁移", "独立本地文件；勿共享盘直接多机写"],
  ["运维关注", "服务、账号、备份恢复", "服务、账号、备份恢复", "文件权限、写锁、WAL 与一致备份"],
  ["比赛得分", "不直接提高 F1 或温度感", "不直接提高 F1 或温度感", "不直接提高 F1 或温度感"]
];

export default function DatabaseComparison() {
  const [selected, setSelected] = useState(1);
  const theme = useHostTheme();
  const dispatch = useCanvasAction();
  const current = scenarios[selected];
  return <Stack gap={18} style={{ padding: 24, color: theme.text.primary, background: theme.bg.editor }}>
    <Stack gap={6}>
      <Text size="small" tone="secondary">众安·暖愈智护 / 团队选型讨论 / 2026-09-23</Text>
      <H1>PostgreSQL · MySQL · SQLite</H1>
      <Text>选最能稳定交付的数据库，把比赛精力留给医疗理解、证据链和效果验证。</Text>
    </Stack>
    <Row gap={8} wrap>{scenarios.map((item, index) => <Pill key={item.label} active={selected === index} onClick={() => setSelected(index)}>{item.label}</Pill>)}</Row>
    <Callout tone="info" title={current.title}>
      <Text>{current.reason}</Text><Text tone="secondary">落地检查：{current.check}</Text>
    </Callout>
    <Text size="small" tone="secondary">场景切换仅改变建议展示，不会修改项目配置或 V3 方案。未执行三库性能测试。</Text>
    <H2>能力与工程取舍对照</H2>
    <Table headers={["维度", "PostgreSQL", "MySQL（InnoDB）", "SQLite"]} rows={rows} striped stickyHeader />
    <Text size="small" tone="secondary">来源：下方官方文档。按本项目需求归纳，不是性能排行；实际结果取决于版本、索引与负载。</Text>
    <H2>数据库保存证据，不替代医疗判断</H2>
    <Text>固定关系字段：案件、授权、任务状态、版本、金额、机构编号。灵活 JSON：提取结果、指引分段、画像指标。原始 PDF/图片另行受控存储，数据库记录引用。</Text>
    <Callout tone="warning" title="三个容易误判的地方">
      <Text>编程 Agent 多，不代表运行时写入并发高。合法 JSON，不代表符合医疗 Schema。数据库有事务，不代表短信发送或模型调用也被同一事务保护。</Text>
    </Callout>
    <H2>半天完成决策：建议时间盒</H2>
    <Table headers={["步骤", "建议时间", "必须产出"]} rows={[
      ["1 · 约束确认", "20 分钟", "经验、环境、数据使用限制、演示方式"],
      ["2 · 初选主库", "20 分钟", "一个候选，不先做三套实现"],
      ["3 · 数据契约", "40 分钟", "金额、缺失值、证据引用、版本与状态"],
      ["4 · 最小验证", "60–90 分钟", "事务、幂等、权限、并发、恢复证据"],
      ["5 · 冻结决策", "20 分钟", "版本、负责人、风险、配置与迁移统一"]
    ]} />
    <Text size="small" tone="secondary">以上为计划估计，不是已完成工时。1/2/4 工作进程可作为探索档位，不是比赛指标。</Text>
    <Row><Button variant="primary" onClick={() => dispatch({ type: "openFile", path: "D:\\众安比赛\\docs\\PostgreSQL_MySQL_SQLite_数据库选型对比报告.md" })}>打开完整中文报告</Button></Row>
    <Divider />
    <H2>官方能力依据</H2>
    <Row gap={14} wrap>
      <Link href="https://www.postgresql.org/docs/current/datatype-json.html">PostgreSQL JSON</Link>
      <Link href="https://www.postgresql.org/docs/current/tutorial-transactions.html">PostgreSQL 事务</Link>
      <Link href="https://dev.mysql.com/doc/refman/8.4/en/json.html">MySQL JSON</Link>
      <Link href="https://dev.mysql.com/doc/refman/8.4/en/innodb-introduction.html">MySQL InnoDB</Link>
      <Link href="https://www.sqlite.org/whentouse.html">SQLite 场景</Link>
      <Link href="https://www.sqlite.org/wal.html">SQLite WAL</Link>
      <Link href="https://www.sqlite.org/foreignkeys.html">SQLite 外键</Link>
      <Link href="https://www.sqlite.org/json1.html">SQLite JSON</Link>
      <Link href="https://www.sqlite.org/datatype3.html">SQLite 类型</Link>
      <Link href="https://www.sqlite.org/backup.html">SQLite 备份</Link>
    </Row>
    <Text size="small" tone="secondary">建议待团队确认；没有部署数据库、切换主库或产生云资源费用。</Text>
  </Stack>;
}
