# 多车仓库调度仿真

两辆仓库小车同时空闲，架上有好几件货，先派哪一单、交给哪辆车？这个项目用 Python 模拟取货、送货和会车，在同一张地图上比较三种派单办法。下面用一个两车、八单的例子跑通项目。仓库结构、算法原理和五组实验的设计见[项目与实验指南](docs/PROJECT_GUIDE.md)。

## 运行需要什么

- **Python**。建议使用 64 位 Python 3.13，项目在 Windows 的 Python 3.13.5 上验证过。仿真使用 CPU，派单、避碰、日志核验和单元测试只用 Python 标准库。
- **绘图依赖**。导出轨迹图、GIF 或运行会自动绘图的主实验 `batch` 时，需要安装 Matplotlib、NumPy、Pillow 等软件包。对应版本列在 [requirements.txt](requirements.txt)。

## 快速开始

**1. 取得源码，打开仓库根目录。** 可以在 GitHub 下载 ZIP 并解压，也可以用以下命令克隆。后续命令都在能同时看到 `requirements.txt` 和 `warehouse_sim/` 的目录运行。

```shell
git clone https://github.com/Nano-hz/AGV_project.git
cd AGV_project
```

**2. 在自己的电脑上创建 Python 环境。** 在 Windows PowerShell 中运行以下命令。先看第一行的输出，确认当前用的是 Python 3.13，再创建 `.venv`。这个目录由本机生成。

```powershell
python --version
python -m venv .venv
$py = '.\.venv\Scripts\python.exe'
```

**3. 跑一次对照，检查三种方法的派单记录。** 下面的例子让 B0、B1、P 各自指挥同样的两辆车搬同样的八件货。继续在同一个 PowerShell 窗口运行。

```powershell
$run = 'outputs/run_demo_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
& $py -m warehouse_sim compare --instance instances/b0_wide_8.json --output $run
foreach ($method in 'B0', 'B1', 'P') {
    & $py -m warehouse_sim verify "$run/$method"
}
```

打开本次目录中的 `comparison.csv`，三种方法的 `completed_tasks` 都应为 8。三次核验均应显示 `dispatch_ok` 和 `completion_time_ok` 为 `true`，`conflict_count` 为 0。想知道一单具体派给了谁，可以看对应策略目录下的 `dispatch.csv`。

**4. 看小车怎样走。** 首次安装绘图依赖通常需要联网。在同一窗口运行以下命令，就能在本次结果的 `P/` 目录中打开 `trajectory.png` 和 `replay.gif`。

```powershell
& $py -m pip install -r requirements.txt
& $py -m pip check
& $py -m warehouse_sim render "$run/P" --gif
```

在 macOS 或 Linux 上，进入仓库根目录后可用以下终端命令完成相同的对照和核验。需要绘图时用 `.venv/bin/python -m pip install -r requirements.txt` 安装依赖。

```sh
python3.13 -m venv .venv
run="outputs/run_demo_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m warehouse_sim compare --instance instances/b0_wide_8.json --output "$run"
for method in B0 B1 P; do .venv/bin/python -m warehouse_sim verify "$run/$method"; done
```

## 文档入口

详细说明都在 `docs/` 目录下。想从头了解项目，可以先读 `docs/PROJECT_GUIDE.md`。

| 想了解什么 | 读哪份文档 |
| --- | --- |
| 目录怎么找、三种算法怎么选单、五组实验如何设计与验证 | [项目与实验指南](docs/PROJECT_GUIDE.md) |
| 查看已有实验的结果表、公式和失败案例 | [原版算法与实验记录](docs/ALGORITHMS_AND_EXPERIMENTS.md) |
| 查看最初怎样验证地图、单车动作和计时 | [第一步实施与验收记录](docs/STEP1.md) |
| 查找旧版首页里的分阶段命令、示例数据和日志字段 | [旧版 README](docs/README_PREVIOUS.md) |

### 复跑 E4 分批发布与 E5 小规模枚举

首次运行可按上面的八单示例检查环境。需要重跑正式实验时，按指南中的命令分别生成结果并核验。[完整实验的复跑命令](docs/PROJECT_GUIDE.md#复跑完整实验)
