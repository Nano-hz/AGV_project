# 多 AGV 仓库调度

依据课程要求和仓库调度方案实现。**第 5 步已完成主实验、分批发布对照和小规模枚举参考。** 自动派单支持 2 辆和 4 辆车，各策略共用同一套取送货规则、时空 A* 和预约表。

已准备宽通道、窄通道、单瓶颈三种 20 × 20 地图。仿真使用 Python 标准库，图像和 GIF 由 Matplotlib / Pillow 根据保存的日志生成。

## 复跑第 5 步批量实验

主实验交叉三种地图、2/4 辆车、8/16/24 单和种子 0–9，保存 180 份共同输入，三种策略各运行一次，共 540 次。每个种子用同一组随机取货位和送达位索引，允许重复组合，每件货有独立编号。各地图按下文的四个正式取货位和地图里的四个送达位映射索引。8 单和 16 单是 24 单序列的前缀，不同车数使用同一批任务。两车占第一和最后一个停车位，四车再增加中间两个。所有任务在第 0 步发布，取货和放货各 1 步，全组使用 1000 步上限。

在 `project` 目录用 PowerShell 运行完整实验并复核全部输出。

```powershell
$run = 'outputs/run_factorial_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -m warehouse_sim batch --output $run --workers 4
.\.venv\Scripts\python.exe -m warehouse_sim batch-verify $run --workers 4
Import-Csv "$run/overall.csv" | Format-Table
```

本次交付在 `outputs/run_factorial_main`，也可直接对它运行 `batch-verify`。核验会检查 180 份共同输入及各策略输入是否一致，复核 540 次派单和逐帧轨迹，复算完成时间、冲突数及汇总表。可以省略 `--workers 4` 使用单进程，或在 `batch` 后加 `--seeds 0` 先试跑 54 次。每轮数据可单独用 `verify <run_dir>` 检查。用 `batch-report $run` 从已有 `runs.csv` 重画图和生成统计表。

| 文件 | 内容 |
| --- | --- |
| `overall.csv` | 三种策略各自 180 次运行的总体结果 |
| `summary.csv` | 18 个地图、车数、任务量组合，每个组合 3 行策略统计和样本数 |
| `paired_summary.csv` | 同种子 P 对 B0/B1 的时间百分比变化及任务完成率变化 |
| `failures.csv` | 失败轮次的地图、车数、任务量、种子、已完成数、超时、冲突和日志路径 |
| `runs.csv` | 540 条逐轮统计，可按种子与策略筛选 |
| `mean_flow_time.png`、`mean_makespan.png`、`task_completion_rate.png` | 按地图和车数分面的任务量曲线 |
| `instances/`、`runs/`、`manifest.json` | 共同输入、每轮原始轨迹及调度证据、实验配置及地图指纹 |

平均任务完成时间按每单「放货完成时刻 − 发布时间」取平均，总完工时刻取该轮最后一单的放货完成时刻。时间均值与样本标准差只统计整轮成功的种子，空白表示样本不足，`complete_runs` 给出样本数。任务完成率把所有轮次送达的任务数除以所有提交任务数，整轮成功率则是全部任务完成且无冲突的轮次占比。配对时间改善只计算两种策略都成功的种子，正值表示 P 用时更短。配对完成率差纳入全部种子，单位为百分点。超时表示达到 1000 步时仍有任务未交付，失败明细中的末步规划原因来自事件日志。

## 复跑 E4 分批发布与 E5 小规模枚举

在 `project` 目录运行以下 PowerShell 命令。两个实验分别创建新目录，核验命令读取保存的文件。

```powershell
$py = '.\.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$e4 = "outputs/run_e4_$stamp"
$e5 = "outputs/run_e5_$stamp"
& $py -m warehouse_sim e4 --output $e4
& $py -m warehouse_sim e4-verify $e4
& $py -m warehouse_sim e5 --output $e5
& $py -m warehouse_sim e5-verify $e5
```

E4 核验 20 份输入、60 次策略运行和配对统计。E5 核验 4 份输入、12 次策略运行，重新模拟全部 864 种顺序与分配，并复核 4 条最佳参考轨迹。两条核验命令均应返回 `"verified": true`。已生成的结果位于 [E4 分组汇总](../outputs/run_e4_release_20261123/summary.csv) 和 [E5 策略与参考值对照](../outputs/run_e5_reference_20261123/comparison.csv)。实验设置、完整数据入口及单个实例的验证示例见[算法与实验说明](ALGORITHMS_AND_EXPERIMENTS.md#8-e4-分批发布对照)。

## 复跑 B0、B1、P 对照

三种策略共用 `instances/b0_wide_8.json` 中的地图、双车起点、8 单任务、发布时间、服务步数和时限。B0 按先来先服务选任务，再选离取货位最近的空闲车。B1 比较所有已发布待办任务与空闲车辆的组合，取「当前时刻 + 到取货位的静态最短距离 + 取货步数 + 到送达位的静态最短距离 + 放货步数」最小的一组。P 对同样的组合运行带预约的时空 A*，用路线长度估计放货完成时刻，计入等待和绕行。P 只在找到可行路线后派单并提交该路线，无可行组合时任务留在队列。预计完成时刻相同时，按任务发布时间、任务编号、车辆编号依次决定。每次派单后处理该车的预约，再选择下一组。

在 `project` 目录打开 PowerShell，复跑三组并核对日志。

```powershell
$run = 'outputs/run_compare_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -m warehouse_sim compare --instance instances/b0_wide_8.json --output $run
Import-Csv "$run/comparison.csv" | Format-Table
foreach ($policy in 'B0', 'B1', 'P') {
    Write-Host $policy
    .\.venv\Scripts\python.exe -m warehouse_sim verify "$run/$policy"
}
```

已保存的同一组结果见 `outputs/demo_compare_wide_8/comparison.csv`。

| 策略 | 完成任务 | 平均任务完成时间 / 步 | 总完工时刻 / 步 | 同格冲突 | 对向交换 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | 8/8 | 66.875 | 110 | 0 | 0 |
| B1 | 8/8 | 59.375 | 113 | 0 | 0 |
| P | 8/8 | 59.000 | 121 | 0 | 0 |

核对派单时，检查各策略的 `dispatch.csv`。B0 用 `idle_distances` 核对空闲车到取货位的格数。B1 和 P 的 `estimated_finish` 是中选组合的预计放货时刻，`candidates` 包含这一轮所有组合的静态预计时刻、策略预计时刻和不可行原因。第 57 步，B1 给 AGV-01 派 T003，静态预计第 96 步完成。P 发现 T003 的送达位已被另一辆车预约为停留点，将其记为 `delivery_reserved_for_stop`，改派预计第 101 步完成的 T002。

```powershell
foreach ($policy in 'B1', 'P') {
    Write-Host $policy
    $decision = Import-Csv "$run/$policy/dispatch.csv" | Where-Object time -eq 57
    $decision | Format-Table task_id,vehicle_id,estimated_finish
    $decision.candidates | ConvertFrom-Json | Format-Table task_id,vehicle_id,static_finish,estimated_finish,unavailable_reason
}
```

三组 `verify` 均应返回 `dispatch_ok: true`、`checked_dispatches: 8`、`completion_time_ok: true`，两种冲突计数都为 0。它从输入及轨迹重建队列与空闲车辆，重算候选分数，逐帧检查位置和交换。P 的复核使用同一个时空规划器重建预约，并核对中选路线的实际执行。完成时间由轨迹中的取放货动作重新计算，再与 `tasks.csv` 和 `summary.json` 比对。手算时用 `completed_at - release_time` 得到单个任务的完成用时，对 8 单取平均。总完工时刻是最大的 `completed_at`。

也可用 `run --instance instances/b0_wide_8.json --policy P --gif` 单独回放 P，或用 `render "$run/P" --gif` 从已有日志生成回放。

## 验证 B0 自动派单

在 `project` 目录打开 PowerShell。下面的命令会创建一个新目录，打印每次派单的候选距离，再从保存的轨迹核对派单与避碰。

```powershell
$run = 'outputs/run_b0_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -m warehouse_sim run --instance instances/b0_wide_8.json --output $run --gif
Import-Csv "$run/dispatch.csv" | Format-Table sequence,time,task_id,release_time,vehicle_id,pickup_distance,idle_distances
.\.venv\Scripts\python.exe -m warehouse_sim verify $run
```

示例在宽通道地图的 4 个指定取货位使用 8 条独立任务。第 0、2、5 步分别发布 4、2、2 单。任务按发布时刻、任务编号依次出队。每次只比较当时空闲车辆，按当前位置到取货位的静态最短路格数选车，计算距离时绕开货架。距离相同按车辆编号选。编号都按字符串顺序比较。领单的车先向规划器申请预约，再派下一单。暂时规划失败的车保留任务，后续时间步继续尝试。

| 派单时刻 | 队首任务 → 车辆（同一行按派单先后排列） |
| ---: | --- |
| 0 | T002 → AGV-02，T003 → AGV-01 |
| 34 | T004 → AGV-02，T005 → AGV-01 |
| 50 | T001 → AGV-01 |
| 64 | T006 → AGV-02 |
| 71 | T007 → AGV-01 |
| 87 | T008 → AGV-01 |

第一单 T002 的候选距离为 AGV-01 的 18 格、AGV-02 的 9 格。第 34 步两车完成上一单后，距 T004 的取货位分别有 23 格和 14 格。第 2 步到达的 T001 排在所有第 0 步任务之后，即使其编号最小也要等待。全部 8 单在第 110 步完成，平均任务完成时间为 66.875 步。

`verify` 用输入中的任务发布时间重建队列，从轨迹中的放货记录判断车辆何时空闲，从派单时刻坐标用广度优先搜索重算候选距离，逐单比对 `dispatch.csv` 及 `tasks.csv`。同一命令也逐帧查同格冲突和对向交换。示例应得到 `checked_dispatches=8`、`dispatch_ok=true`、`checked_frames=111`，两种冲突均为 0。可直接校验已保存的 `outputs/demo_b0_wide_8`。若任务超时，`summary.json` 仍会报告实际完成数，`verify` 仅检查已发生的派单和移动。

## 验证两辆车避碰

在 `project` 目录打开 PowerShell，运行共用取货点案例，并独立核对保存的轨迹。

```powershell
$run = 'outputs/run_two_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -m warehouse_sim run --instance instances/two_shared_pickup.json --output $run --gif
.\.venv\Scripts\python.exe -m warehouse_sim verify $run
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

打开新目录下的 `replay.gif` 看两辆车，打开 `tasks.csv` 核对第一辆在第 3 步开始取货，第二辆在第 5 步开始取货。两辆车的取货坐标都是 `(4, 2)`，两单分别在第 6、8 步送达。`verify` 应输出 `checked_frames: 9`、`vertex_conflicts: 0` 和 `edge_swap_conflicts: 0`。

以下实例可替换命令中的 `--instance` 参数。

| 实例（位于 `instances/`） | 预期可见行为 |
| --- | --- |
| `two_shared_pickup.json` | 两件货共用一个取货位，两车分别在第 3、5 步开始取货，第 8 步全部完成 |
| `two_crossing.json` | 第 2 步第二辆车在路口前等待，第 3 步才进入交叉格，第 7 步全部完成 |
| `two_passing_bay.json` | 第 8 步第二辆车进入侧边 `(6, 1)`，第一辆同时经过主通道 `(6, 2)`，第 15 步全部完成 |
| `two_retry.json` | 第一辆车第 0 步规划失败并等待，第二辆车移开后，第一辆第 1 步重试成功，第 10 步全部完成 |
| `two_same_delivery_blocked.json` | 第一辆卸货后留在唯一送达格，第 12 步超时，完成 1 单，仍为 0 次冲突 |

规划按车辆编号尝试，已接受的路线在本次运行中保持预约。未出发的车占起始格，移动中的车占对应时刻的格和边，取放货占用服务格，完成任务后继续占送达格。单次规划失败的事件 `plan_unavailable` 会记录 `reason`，车原地等待并在下一步重试。`verify` 返回 0 表示轨迹无碰撞，即使任务超时也可单独验证轨迹安全。固定优先级和模拟时限会影响能否完成所有任务。

正式布局对照每张图使用四个取货位。现有宽、窄地图仍标有额外的候选位，正式任务生成时按下表取点。这一阶段的小案例可自行设定点位来测试避碰。

| 正式布局 | 固定取货坐标 `(x, y)` |
| --- | --- |
| 宽通道 | `(7, 4)`、`(13, 4)`、`(7, 15)`、`(13, 15)` |
| 窄通道 | `(7, 4)`、`(17, 4)`、`(7, 12)`、`(17, 12)` |
| 单瓶颈 | `(7, 4)`、`(16, 4)`、`(7, 14)`、`(16, 14)` |

## 直接运行

在本项目 `project` 目录打开 PowerShell。本机已经搭建好 `.venv`，无需激活环境：

```powershell
.\.venv\Scripts\python.exe -m warehouse_sim run --gif
```

主程序是 `warehouse_sim/__main__.py`，通过 `python -m warehouse_sim` 调用。默认运行宽通道实例，自动创建新的 `outputs/run_<时间戳>/` 目录，打印指标并保存 PNG 和 GIF。

```powershell
# 单瓶颈地图
.\.venv\Scripts\python.exe -m warehouse_sim run --instance instances/single_bottleneck.json --gif

# 仅仿真与日志，适合以后批量运行
.\.venv\Scripts\python.exe -m warehouse_sim run --instance instances/single_narrow.json

# 校验输入和地图连通性
.\.venv\Scripts\python.exe -m warehouse_sim validate --instance instances/single_wide.json

# 从现有日志重画，不重新执行仿真
.\.venv\Scripts\python.exe -m warehouse_sim render outputs/demo_wide --gif --fps 5

# 正确性检查
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

也可用 `--output outputs/my_run` 指定新的运行目录。如果目录已存在，程序拒绝覆盖；省略 `--output` 可自动保留每次运行的数据。GIF 的 `fps` 只改变播放速度，仿真中的 tick 没有换算成物理秒。

## 已保存的单车演示

| 地图 | 行驶距离 / 格 | 取放货 / 步 | 等待 / 步 | 完成时间 / 步 | 输出目录 |
| --- | ---: | ---: | ---: | ---: | --- |
| 宽通道 | 30 | 2 | 0 | 32 | `outputs/demo_wide/` |
| 窄通道 | 32 | 2 | 0 | 34 | `outputs/demo_narrow/` |
| 单瓶颈 | 32 | 2 | 0 | 34 | `outputs/demo_bottleneck/` |

三例均由本项目程序实际运行完成，取送货位不完全相同，只用于验证地图和仿真，不能据此比较布局或调度算法优劣。单车场景不存在车际冲突，日志中的 `conflict_count=0` 仅适用于本阶段，不能作为多车安全证明。

## 本机环境与复建

2026-11-19 检查结果：Windows 10 64 位，i7-11800H，16 个逻辑处理器，物理内存总量约 15.85 GiB。原 Python 位于 `D:\conda\python.exe`，版本 3.13.5；项目在 `.venv` 中独立安装依赖，`include-system-site-packages=false`。RTX 3060 Laptop 6 GB 已检测到，本阶段计算使用 CPU。

直接依赖：Matplotlib 3.10.0、NumPy 2.1.3、Pillow 11.1.0；`requirements.txt` 同时锁定本次验证过的传递依赖。未安装 NetworkX、Pytest、PyTorch 或机器人仿真平台；静态 A* 和仿真核心自行实现，测试使用标准库 `unittest`。

换机器时建议使用 **Python 3.13.5 或同系列 3.13** 重建，不要复制 `.venv`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m warehouse_sim run --gif
```

可选安装入口：`powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`。它只为当前进程采用该策略，不修改系统或用户的 PowerShell 策略。支持用 `-Python "解释器完整路径"` 选择 Python，安装前请确认是项目需要的版本。

环境检查可复跑：

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py --output docs/environment.json
```

本机原环境和项目环境记录分别见 `docs/host_environment.json`、`docs/environment.json`。它们记录检查时的内存和磁盘余量，数值会随时间变化。安装依赖需要联网，已安装后仿真、绘图和 GIF 导出均可离线执行。核心无界面仿真也可在未安装第三方库时运行。

## 输入规则

- 地图文件在 `maps/`。`grid` 是等宽字符串数组：`#` 障碍，`.` 通道，`P` 停车位，`U` 取货位，`D` 送达位。所有非障碍格须连通，特殊位置可通行。
- 坐标是 `[x, y]`，左上角为 `[0, 0]`，x 向右、y 向下，每步只能四连通移动一格或停留。
- 实例文件在 `instances/`。地图路径相对于实例文件所在目录解析；输出中的实例直接嵌入地图，可独立重跑。
- 实例顶层 `dispatch_policy` 可指定 `B0`、`B1` 或 `P`。自动派单需要两辆或四辆车和至少一条任务，任务省略 `vehicle_id`。省略策略字段时沿用固定派单格式，支持单车单任务或双车各一条固定任务。车辆从不同停车格出发，车辆编号和任务编号分别唯一。同一取货位可对应多件货。
- `pickup_steps`、`dropoff_steps` 默认 1，且须为正整数。`max_steps` 默认 1000。`release_time` 是非负整数，任务到达之前车辆原地等待。
- `seed=0` 随手工实例保留。后续随机任务必须保存实际生成后的实例。
- 静态 A* 使用曼哈顿距离。双车时空 A* 的估计值是忽略动态预约时剩余的最短路距离加剩余服务步数，遇到同优先级按入队顺序处理。

重新生成三种固定输入：`python scripts/generate_scenarios.py`。该命令会重写六个配套地图 / 实例 JSON；自行修改的实验输入请另存新文件。

## 时间与日志约定

`t=0` 记录每辆车的初始状态。每个区间 `[t,t+1)` 检查任务到达，交给对应车辆，处理路线预约，所有车辆同步执行一次移动、等待、取货或放货，在 `t+1` 每车写一行。任务释放和领取发生在区间起点，移动和服务完成发生在区间终点，具体事件见 `events.csv`。

取放货各自占用独立时间步。服务期间位置保持不变。完成任务后车辆仍在送达格。所有任务完成或达到步数上限时仿真结束。

每次运行保存：

| 文件 | 内容 |
| --- | --- |
| `instance.json` | 完整输入快照，内嵌地图、种子与参数 |
| `trajectory.csv` | 每个整数时刻的位置、阶段、载货标志、任务状态、上一时间步动作、累计计数 |
| `events.csv` | 释放、领取、规划、到达、开始服务、完成或失败事件 |
| `tasks.csv` | 包括未完成任务在内的到达、领取、取货和送达时刻 |
| `dispatch.csv` | 自动派单记录，含派单时刻、所选车辆和候选距离。B1、P 还记录所有候选组合的预计完成时刻 |
| `summary.json` | 完成率、平均完成时间、总完工时间、距离、等待、服务、失败原因、运行耗时 |
| `metadata.json` | 实际 Python / 依赖版本、源码和实例 SHA-256、UTC 生成时刻 |
| `trajectory.png` | 从轨迹日志生成的静态图，使用 `--plot` 或 `--gif` 时生成 |
| `replay.gif` | 从逐步日志生成的动画，使用 `--gif` 时生成 |

车辆阶段依次为 `idle`、`to_pickup`、`pickup`、`to_delivery`、`dropoff`、`idle`。任务状态为 `unreleased`、`pending`（已入队）、`assigned`、`picked_up`、`completed`。某车放货完成时刻为 t 时，即可参与时刻 t 的派单，下一次移动发生在区间 [t, t+1)。

主指标 `mean_flow_time` 是任务发布到完成的平均步数，`makespan` 是最后一单的完成时刻。全部任务完成时这两项才有值。`total_wait_steps` 汇总各车的等待，包含任务发布前和送达后原地停留，取放货另计。对每辆车，行驶步数 + 等待步数 + 服务步数等于仿真经过步数。`runtime_seconds` 统计仿真和轨迹校验的耗时。

成功退出码为 0，非法输入 / 文件或绘图错误为 1，达到最大步数但任务未完成为 2。超时运行仍保存已发生的轨迹和任务记录，`failure_reason=max_steps_exceeded`。非法或不连通地图在启动前拒绝。

## 目录结构

```text
project/
  .venv/                   本机隔离环境，迁移和提交时不打包
  requirements.txt         完整固定依赖
  warehouse_sim/
    models.py              两层共用的地图、车辆、任务与输入校验
    algorithms/
      planner.py           静态 A* 和最短距离
      space_time.py        取送路线规划、时空 A* 和预约表
      dispatch.py          B0、B1、P 候选评分与选车选单
    simulation/
      simulator.py         任务队列、状态推进、执行派单和记录结果
      collisions.py        从轨迹检查同格冲突与对向交换
      dispatch_audit.py    从输入和轨迹复核派单与完成时间
    experiment_inputs.py  生成配对的批量实验输入
    experiments.py         批量运行与复核
    experiment_report.py  汇总表与实验图
    output.py              CSV / JSON 与复现信息
    visualize.py           日志绘图和 GIF 回放
    __main__.py            命令行入口
  maps/                    三种固定 20 × 20 地图
  instances/               单车、双车固定任务与多任务实例
  scripts/                 环境搭建、检查及固定输入生成
  tests/                   仿真、调度、避碰和实验统计测试
  outputs/demo_*/          已运行的开发演示结果
  docs/                    算法与实验说明、环境记录
```

算法层读取共享模型、当前候选和预约，返回选择与路线。仿真层负责分配任务、提交预约、推进车辆状态和写出事件。命令行入口为 `python -m warehouse_sim`。在 Python 中可通过 `from warehouse_sim.simulation.simulator import run` 调用仿真，通过 `from warehouse_sim.algorithms.planner import shortest_path` 调用静态寻路。

作者、学号、两人分工、联系方式：**待项目成员填写**。最终报告与提交包尚未制作。

## 使用资料

- 上级目录《大作业-2026年秋.pptx》第 1—3 页：提交、复现、原创实现及多 AGV 调度要求；第 4—5 页为其他选题。
- 上级目录《大作业三题分析与完成方案.md》第二部分第 1、2、3、5 节：平台、模型、日志和实施顺序。
- [Python 3.13 venv 文档](https://docs.python.org/3.13/library/venv.html)：隔离环境、直接调用环境解释器和迁移时重建。
- [Matplotlib 动画文档](https://matplotlib.org/stable/users/explain/animations/animations.html)：FuncAnimation 根据已保存状态更新画面，PillowWriter 输出 GIF。
