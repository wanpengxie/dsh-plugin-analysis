# C-lite 实验方案

目标：用低成本漏斗处理 `lists/zero-star.csv`，不直接复用 B 层完整生成流程。

## 阶段

1. **A+B 基线（一次性）**：只读取 Git 已跟踪的 canonical cards/units，生成可查询的 TF-IDF 能力基线。
2. **C 静态初筛（全部）**：下载固定 commit，运行静态 facts 提取，计算入口、注册面、源码量、测试、提交与 README 信号。
3. **近邻比较**：C 的能力指纹只查询 A+B 基线 Top-5，不让 worker 重读 A+B。
4. **机器路由**：输出 `promote`、`lite`、`drop`、`failed`，每项保留规则命中原因和近邻证据。
5. **模型复核**：只复核 promote、边界样本和随机 drop 样本。通过校准后再扩到 12,642 个。

## 首轮 100 个实验

- 从 C 清单全区间等距抽样，避免只看榜首或某个时间段。
- facts 输出到 `experiments/c-lite/facts/`，不污染正式 `results/`。
- 下载源码仍放在 `work/<owner>__<repo>`，实验结束后按精确样本清单删除。
- 结果写入 `experiments/c-lite/decisions.jsonl` 与 `summary.json`。

## 初始规则（用于校准，不是最终产品规则）

- `drop`：无入口/注册面/bundle，且源码很少、提交不超过 1。
- `promote`：8 项信号中至少命中 6 项：源码量、文件结构、提交、测试、CI、类型、明确注册项、低近邻相似度。相似度最多贡献 1 分，不能单独晋级。
- `lite`：其余可识别仓库，只保留精简检索材料。
- `failed`：固定 commit 无法下载或 facts 无法提取。

近邻相似度不是“价值”本身；它只作为重复度证据。低相似但内容贫乏的仓库不会晋级。
