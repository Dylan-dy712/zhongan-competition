import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useCanvasAction,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";

type PhaseId = "all" | "foundation" | "core" | "integration" | "finale";

const phases = [
  {
    id: "foundation" as const,
    days: "D1–D3",
    title: "指标与数据底座",
    goal: "冻结范围、数据契约、标注规范和第一份真实指标。",
    deliverables: ["JSON Schema V0.1", "评测脚本骨架", "结构化 F1 ≥ 0.85", "证据回溯 V1"],
    gate: "G1：没有冻结数据与真实 F1，不进入页面扩张。",
  },
  {
    id: "core" as const,
    days: "D4–D8",
    title: "证据、痛点与温度",
    goal: "跑通最有分量的三项核心能力，并完成首次双盲评测。",
    deliverables: ["医疗事件图谱", "痛点一致率 ≥ 85%", "三病种温度指引", "盲评 ≥ 4.0/5"],
    gate: "G2：证据、痛点、温度均需真实运行；未通过则砍低价值功能。",
  },
  {
    id: "integration" as const,
    days: "D9–D11",
    title: "推荐、记忆与全链路",
    goal: "完成品质画像、Semantix 连续记忆和端到端联调。",
    deliverables: ["3 病种 × 5 机构", "两次连续关怀", "撤回与降级", "主流程 5/5"],
    gate: "G3：D10 后冻结主功能；P1 不得拖累 P0。",
  },
  {
    id: "finale" as const,
    days: "D12–D14",
    title: "冻结评测与答辩",
    goal: "用隐藏集、盲评、压力测试和答辩包装形成完整证据链。",
    deliverables: ["F1 ≥ 0.94", "痛点 ≥ 90%", "温度 ≥ 4.5/5", "演示 10/10"],
    gate: "G4：使用冻结稳定版本，禁止决赛前临场换模型。",
  },
];

const dailyRows = [
  ["D1", "范围、角色、病种、Schema、演示故事", "R1 主导，全员", "范围与责任冻结"],
  ["D2", "数据划分、标注指南、API 契约、页面骨架", "R2 / R4 / R5", "一个病例走通空链路"],
  ["D3", "结构化基线、证据坐标、自动评测", "R2 + 评测负责人", "F1 ≥ 0.85"],
  ["D4", "跨文档事件归并、冲突与缺失", "R2 / R5", "关键事实可回原文"],
  ["D5", "三类痛点、严重度、证据和动作", "R2 + 医学审核", "一致率 ≥ 80%"],
  ["D6", "错误分析、医学安全、对抗用例", "R2 / R3", "一致率 ≥ 85%"],
  ["D7", "事实计划、六段温度指引、安全审校", "R3 / R5", "三病种可生成"],
  ["D8", "首次双盲评测与生成优化", "R3 / R1", "温度、行动 ≥ 4.0"],
  ["D9", "五维画像、可信度、可解释推荐", "R4 / R5", "3 病种 × 5 机构"],
  ["D10", "Semantix 授权、检索、撤回、降级", "R3 / R4 / R5", "两次会话跑通"],
  ["D11", "全链路联调、日志、演示脚本", "全员", "主流程 5/5"],
  ["D12", "隐藏集、盲评、消融、安全与成本", "评测负责人 + 全员", "硬指标全部达线"],
  ["D13", "方案书、PPT、视频、讲稿、问答", "R1 主导，全员", "8 分钟彩排不超时"],
  ["D14", "10 次压测、故障降级、最终归档", "全员", "10/10，无 P0 缺陷"],
];

const roles = [
  ["R1", "队长 / 产品与答辩", "范围、用户旅程、方案书、PPT、讲稿"],
  ["R2", "医学 / NLP 算法", "结构化、事件图谱、痛点引擎、错误分析"],
  ["R3", "LLM / 记忆算法", "温度生成、安全审校、Semantix、盲评优化"],
  ["R4", "后端 / 数据工程", "API、证据库、画像推荐、日志、成本"],
  ["R5", "前端 / 可视化", "六页面、证据交互、看板、演示稳定性"],
];

const nonNegotiables = [
  "每个对外指标都必须由固定数据、固定脚本和固定版本复现。",
  "每条事实、痛点和推荐理由都要有证据或数据来源。",
  "不替代医生诊断，不指导自行停药换药，不虚构机构排名。",
  "D10 后不新增主功能，演示稳定性优先于功能数量。",
];

export default function ChampionshipWorkplan() {
  const theme = useHostTheme();
  const dispatch = useCanvasAction();
  const [selectedPhase, setSelectedPhase] = useCanvasState<PhaseId>("zhongan-phase", "all");
  const visiblePhases = selectedPhase === "all" ? phases : phases.filter((phase) => phase.id === selectedPhase);

  return (
    <Stack gap={22} style={{ padding: 24, maxWidth: 1320, margin: "0 auto" }}>
      <Stack gap={8}>
        <Row align="start" justify="space-between" gap={20} wrap>
          <Stack gap={6} style={{ maxWidth: 840 }}>
            <Text tone="secondary" size="small" weight="semibold">众安 1024 AI Coding 校园挑战赛</Text>
            <H1>众安·暖愈智护｜V1 历史作战图</H1>
            <Text tone="secondary">
              此视图保留 V1 历史排期。团队执行请以 V2 文档为准：D2 验证依赖、D3 真实病例闭环、D7 全链路、D9 功能冻结。
            </Text>
          </Stack>
          <Button
            variant="primary"
            onClick={() => dispatch({ type: "openFile", path: "D:\\众安比赛\\docs\\众安暖愈智护_两周冲冠工作安排_V2.md" })}
          >
            打开 V2 执行方案
          </Button>
        </Row>
        <Callout tone="info" title="唯一完成标准">
          功能做完不等于完成。只有“硬指标可复现、证据可追溯、医疗有边界、演示稳定”同时成立，才算通过。
        </Callout>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat value="≥ 0.94" label="结构化 F1 目标" tone="success" />
        <Stat value="≥ 90%" label="痛点专家一致率" tone="success" />
        <Stat value="≥ 4.5/5" label="温度与行动盲评" tone="success" />
        <Stat value="10/10" label="决赛演示成功率" tone="info" />
      </Grid>

      <Divider />

      <Stack gap={12}>
        <Row justify="space-between" align="center" wrap gap={12}>
          <H2>四阶段时间线</H2>
          <Row gap={8} wrap>
            <Pill active={selectedPhase === "all"} onClick={() => setSelectedPhase("all")}>全部</Pill>
            {phases.map((phase) => (
              <Pill key={phase.id} active={selectedPhase === phase.id} onClick={() => setSelectedPhase(phase.id)}>
                {phase.days}
              </Pill>
            ))}
          </Row>
        </Row>

        <Grid columns="repeat(auto-fit, minmax(250px, 1fr))" gap={12}>
          {visiblePhases.map((phase) => (
            <Card key={phase.id} size="lg">
              <CardHeader trailing={<Pill size="sm" active>{phase.days}</Pill>}>{phase.title}</CardHeader>
              <CardBody>
                <Stack gap={10}>
                  <Text>{phase.goal}</Text>
                  <div style={{ height: 3, background: theme.accent.primary, width: "48%" }} />
                  <Stack gap={5}>
                    {phase.deliverables.map((item) => (
                      <Text key={item} size="small" tone="secondary">— {item}</Text>
                    ))}
                  </Stack>
                  <Text size="small" weight="semibold">{phase.gate}</Text>
                </Stack>
              </CardBody>
            </Card>
          ))}
        </Grid>
      </Stack>

      <Grid columns="minmax(0, 1.45fr) minmax(280px, 0.55fr)" gap={22} align="start">
        <Stack gap={12}>
          <H2>14 天逐日交付</H2>
          <Table
            headers={["日期", "当日主任务", "主责", "退出条件"]}
            rows={dailyRows}
            striped
            stickyHeader
            columnAlign={["center", "left", "left", "left"]}
          />
        </Stack>

        <Stack gap={14}>
          <H2>责任队形</H2>
          <Card>
            <CardHeader>五人标准配置</CardHeader>
            <CardBody>
              <Stack gap={9}>
                {roles.map(([id, role, output], index) => (
                  <Stack key={id} gap={3}>
                    <Row gap={8} align="center">
                      <Pill size="sm" active>{id}</Pill>
                      <Text weight="semibold">{role}</Text>
                    </Row>
                    <Text size="small" tone="secondary">{output}</Text>
                    {index < roles.length - 1 ? <Divider /> : null}
                  </Stack>
                ))}
              </Stack>
            </CardBody>
          </Card>

          <Callout tone="warning" title="人数不足时">
            3 人：R1+R5、R2+医学审核、R3+R4；4 人：R1、R2+医学审核、R3、R4+R5。无论人数多少，指标与数据泄漏负责人不能缺失。
          </Callout>
        </Stack>
      </Grid>

      <Divider />

      <Grid columns="minmax(0, 1fr) minmax(0, 1fr)" gap={24} align="start">
        <Stack gap={10}>
          <H2>不可妥协的四条规则</H2>
          {nonNegotiables.map((item, index) => (
            <Row key={item} gap={10} align="start">
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 12,
                  background: theme.fill.secondary,
                  color: theme.accent.primary,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {index + 1}
              </div>
              <Text>{item}</Text>
            </Row>
          ))}
        </Stack>

        <Stack gap={10}>
          <H2>每日作战节奏</H2>
          <Table
            headers={["时间", "动作", "必须产出"]}
            rows={[
              ["09:30", "15 分钟站会", "昨日结果、今日交付、阻塞"],
              ["13:30", "接口与数据同步", "Schema/API 变更结论"],
              ["18:00", "全员主流程演示", "指标看板与缺陷更新"],
              ["22:00", "冻结可运行版本", "稳定提交与答辩素材"],
            ]}
            striped
          />
        </Stack>
      </Grid>

      <Stack gap={8}>
        <H2>团队首次评审会</H2>
        <Text tone="secondary">60 分钟内必须确定：人员角色、三个病种、数据可用性、技术栈、医学与指标审核人、四个闸门验收人，以及 D10 后冻结主功能。</Text>
        <Callout tone="success" title="第一天的正确结果">
          不追求页面精致。第一天结束时必须把范围、指标、数据契约和责任边界锁死，冠军项目从第一天开始积累可验证证据。
        </Callout>
      </Stack>
    </Stack>
  );
}
