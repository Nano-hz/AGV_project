# 实验输出索引

写报告时使用下表的三个正式批次。E1、E2、E3 是从同一批运行中分别比较订单量、车辆数和地图布局，只统计一次。每一轮都保存了实际订单、派单顺序、逐步轨迹和送达时间。实验方法和结果解读见[算法与实验记录](../docs/ALGORITHMS_AND_EXPERIMENTS.md)。

| 实验 | 这一批是什么 | 看哪些文件 |
| --- | --- | --- |
| E1–E3 主实验 | `run_factorial_main/`。3 张图 × 2 档车数 × 3 档单量 × 10 个种子，共 180 份输入。每份各跑 B0、B1、P，共 540 轮。 | [分组汇总](run_factorial_main/summary.csv) 按地图、车数、单量查结果。[配对比较](run_factorial_main/paired_summary.csv) 比较相同种子下的用时，[失败明细](run_factorial_main/failures.csv) 可追到超时轮次。 |
| E4 分批发布 | `run_e4_release_20261123/`。固定单瓶颈、2 辆车、16 单。10 个种子分别一次发完或分四次发布，共 20 份输入、60 轮。 | [分组汇总](run_e4_release_20261123/summary.csv)、[同策略换发布时间](run_e4_release_20261123/paired_release.csv)、[同发布时间换派单策略](run_e4_release_20261123/paired_policy.csv)。 |
| E5 小规模枚举 | `run_e5_reference_20261123/`。2 个人工实例和 2 个随机实例，均为两车、3 或 4 单。共 12 轮策略运行，另验证 864 种顺序和车辆分配。 | [三种策略与参考值的差距](run_e5_reference_20261123/comparison.csv)、[每例的参考值与最佳序列编号](run_e5_reference_20261123/references.csv)。每个 `reference/<实例>/candidates.csv` 记录该实例的全部枚举方案。 |

核对某个数字时，可以从该批次的 `runs.csv` 找到对应的 `run_dir`，相对于**该批次目录**打开。里面的 `instance.json` 保存地图和订单，`dispatch.csv` 记录派单，`tasks.csv` 记录逐单完成时间，`trajectory.csv` 记录每一步的位置。任务完成率包含超时轮次中已送达的订单。比较两种策略的用时时，看配对成功的样本数。

## 四段正式实验回放

四段 GIF 均从对应轮次的 `trajectory.csv` 生成。每一行的两个回放使用相同的地图、车辆和货件。

| 对照 | 回放 |
| --- | --- |
| E4，种子 0，P 派单，改变订单发布时间 | [16 单同时发布](run_e4_release_20261123/runs/bottleneck_v2_n16_s00_simultaneous/P/replay.gif) · [第 0、10、20、30 步各发布 4 单](run_e4_release_20261123/runs/bottleneck_v2_n16_s00_waves/P/replay.gif) |
| E5，种子 1，单瓶颈 4 单，改变派单顺序 | [P 派单](run_e5_reference_20261123/runs/random_bottleneck_v2_n04_s01/P/replay.gif) · [枚举选出的参考方案](run_e5_reference_20261123/reference/random_bottleneck_v2_n04_s01/replay.gif) |

## 演示与本地归档

[demos/](demos/) 随仓库提供，适合在跑正式实验前查看功能。这里的场景和用途如下。

| 目录（均位于 `demos/`） | 用途 |
| --- | --- |
| [single_wide](demos/single_wide/)、[single_narrow](demos/single_narrow/)、[single_bottleneck](demos/single_bottleneck/) | 单车各搬一件货，检查三张地图和取放货计时。 |
| [two_shared_pickup](demos/two_shared_pickup/)、[two_passing_bay](demos/two_passing_bay/) | 两车分别演示共用取货位、在窄道错车。 |
| [wide_8_compare](demos/wide_8_compare/) | README 的宽通道两车八单案例，有 B0、B1、P 的派单日志和对照表。 |
| [wide_8_b0](demos/wide_8_b0/) | 同一个八单案例的 B0 动画。派单、轨迹、订单和事件与对照案例的 B0 相同。 |

`archive/` 保留整理前的四个本地目录，方便追查旧记录。

- `run_20261119_210411_162899` 和 `run_20261119_210443_688821` 都重复了单车宽通道演示。
- `run_compare_20261122_212650_368` 重复了宽通道八单的三策略对照。
- `run_recheck_20261123` 是主实验的独立复跑。180 份输入和 540 轮的派单、轨迹、逐单时间及事件与正式批次一致。运行耗时和版本记录有差异。该目录另有一个 `smoke/` 子目录，保存单车、双车和派单功能检查，其中有一个特意构造的送达位被占用后超时的案例。

## 换电脑怎样得到这些文件

Git 保存演示、实验代码和说明。正式批次与归档保存在实验电脑上。在新克隆的仓库中，从仓库根目录用以下 PowerShell 命令生成三个同名正式目录，上面的数据链接就能直接打开。运行前按[快速开始](../README.md#快速开始)安装依赖。如果目录已经存在，直接执行对应的核验命令。

```powershell
$py = '.\.venv\Scripts\python.exe'
$main = 'outputs/run_factorial_main'
$e4 = 'outputs/run_e4_release_20261123'
$e5 = 'outputs/run_e5_reference_20261123'

& $py -m warehouse_sim batch --output $main --workers 4
& $py -m warehouse_sim batch-verify $main --workers 4
& $py -m warehouse_sim e4 --output $e4
& $py -m warehouse_sim e4-verify $e4
& $py -m warehouse_sim e5 --output $e5
& $py -m warehouse_sim e5-verify $e5
```

核验主实验应得到 180 份输入、540 轮和 `tables_ok: true`。E4 和 E5 应返回 `verified: true`。要在新电脑上补齐上表的四段动画，继续运行以下命令。

```powershell
& $py -m warehouse_sim render "$e4/runs/bottleneck_v2_n16_s00_simultaneous/P" --gif --fps 10
& $py -m warehouse_sim render "$e4/runs/bottleneck_v2_n16_s00_waves/P" --gif --fps 10
& $py -m warehouse_sim render "$e5/runs/random_bottleneck_v2_n04_s01/P" --gif --fps 10
& $py -m warehouse_sim render "$e5/reference/random_bottleneck_v2_n04_s01" --gif --fps 10
```
