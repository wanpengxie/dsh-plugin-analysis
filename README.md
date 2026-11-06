# DSH Plugin Analysis

为 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）的插件市场准备底层数据：GitHub 上有哪些 DSH 插件，每个能做什么、要什么配置、风险和实现质量怎样，以及让人和 agent 用一句话需求就能搜到并被推荐合适插件的索引文本。

## 数据从哪来

1. **候选**：GitHub 仓库搜索，查找 topic 为 `dsh-plugin` 或 `deepseek-harness` 的仓库。按创建时间切片拉全，截至 2026-11-06，去重后共 31,371 个仓库。
2. **认定插件**：读取每个仓库 HEAD 上的 `package.json`，声明了 `dsh.bundle` 的算插件，共 **23,954 个**，占候选的 76%。其余是只打了 topic 的普通仓库，或者没有 `package.json`。
3. **排重**：不下载代码，只靠 git 对象 id（按内容寻址，内容相同 id 就相同）比较仓库，满足任一条件就归入同一组：
   - GitHub 记录的 fork 关系；
   - 根目录树完全相同；
   - `package.json` 完全相同；
   - 顶层主要文件有 80% 以上相同。
   
   每组取最早创建的仓库作代表（视为原作），其余记为副本。README 相同、仓库名相同只单独列出，不并组，因为用同一个模板做出来的不同插件也会出现这两种情况。
4. **分层**：按组内最高 star 数分层：

   | 层 | star 数 |
   |---|---|
   | A | ≥ 10 |
   | B | 1–9 |
   | C | 0 |

## 清单

| 文件 | 内容 |
|---|---|
| `lists/high-priority.csv` | 高优组：A 层和 B 层的代表仓库，按 star 排序，带分析时要固定的 commit |
| `lists/zero-star.csv` | 0 star 组：C 层，这一轮不分析 |
| `lists/duplicates.csv` | 每个副本对应哪个代表仓库，是哪种关系 |
| `lists/same-readme.csv`、`lists/same-name.csv` | README 相同、仓库名相同的仓库，仅供参考 |
| `lists/stats.json` | 各项数量统计 |

清单里的 star、推送时间等字段都是采集当天的快照。

## 怎么分析

见 [STRATEGY.md](STRATEGY.md)。每个插件先用脚本从源码里静态抽出事实，再由模型阅读源码，写出卡片（包括能力、配置要求、外部服务、风险、实现质量）和索引文本。要进检索索引的文本见 [INDEX-TEXTS.md](INDEX-TEXTS.md)，主题见 [TAXONOMY.md](TAXONOMY.md)，各产出的格式见 `schema/`。

这一轮只做高优组（A、B 层），0 star 组（C 层）留作后续。分析只做静态阅读，不安装依赖，也不运行插件里的任何代码。

## 目录

```
lists/      清单（由 scripts/dedupe.py 生成）
schema/     每个插件的输出格式
scripts/    排重等脚本
results/    每个插件的产出：facts/、cards/、units/、failed/、progress.jsonl
report/     汇总报告
```

## 说明

- 风险评级是对公开代码做静态阅读得出的判断，可能有误判。评为 high 的插件都会经过人工复核。
- 结论只针对清单里固定的那个 commit，不代表仓库现在的状态。
