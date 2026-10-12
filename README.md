# CTO虚拟电学驱动平台 · 正式整合版与研究原型分开交付

更新：2026-10-12。**默认 `main` 是已核验整合版；恢复—重扫候选另放未验证研究分支。**
基于假设BVD、有损L型匹配与戴维南源的准稳态电学研究。非实测器件、非完整射频功放、非声学或临床验证。
本仓库保持私有，不声明开源许可；没有自动添加协作者或部署网页。

## 当前从哪里运行

在 `main` 页面点击 **Code → Download ZIP**，完整解压，或克隆仓库后：

```powershell
cd integrated/CTO_virtual_drive_platform_v2_1
python -m pip install -r requirements-ui.txt
python run_project.py verify
python run_project.py ui
```

浏览器打开 `http://127.0.0.1:8501`。端口占用可加 `--port 8502`。
`python run_project.py test` 可运行行为与网页测试；`validate` 会新建控制批次并在复核后切换登记，**本次发布没有执行该命令**。
保持 `integrated/` 内平台与 `outputs/` 的同级结构；不能只拖出一个脚本运行。
当前准稳态引擎不需要LTspice；独立LTspice页面需要本机软件与路径配置。

## 三种身份，不混为同一批实验

| 身份 | 位置 | 能说明什么 |
|---|---|---|
| 正式整合交付 | [integrated/CTO_virtual_drive_platform_v2_1](integrated/CTO_virtual_drive_platform_v2_1) | 同口径固定／周期扫频／相位反馈、网页、参数来源登记、明确批次及测试 |
| 已完成独立诊断 | [拟合与控制分账](integrated/CTO_virtual_drive_platform_v2_1/research/fit_control_diagnostics_20261006/README.md) | 拟合数值方法核查、105条既有时序分账；不是新控制性能结果 |
| 未验证恢复候选 | [单独研究分支](https://github.com/buyaozhangbikoule/cto-virtual-drive-platform/tree/research/recovery-scan-handoff-unvalidated-20261012) | 仅候选代码与预登记协议；尚无有效性结论，不进入正式入口 |
| 历史资料 | `workspace/`、根目录 `docs/`、`reports/`及原审核分支 | 保留当时结果与表述，不能冒充当前批次 |

当前版本由 [CURRENT_RELEASE.json](CURRENT_RELEASE.json) 明确登记，固定发布分支为
`release/verified-integration-20261012`。本次范围与排除项见 [发布说明](release/20261012/README.md)。
根目录旧 `docs/01` 等文件保留历史身份，最新完成度以整合目录内README、文档和当前登记批次为准。

## 当前完成到哪里

- 已完成统一三策略的准稳态比较并接入网页；正式策略为固定频率、周期扫频、相位反馈，P&O是扩展。
- 当前批次为 `UNIFIED_20260923T013352_476445Z_f442bcda`，包含原12段日程及34个登记条目的三策略覆盖。登记条目含等价别名，不等于34种独立真实负载。
- 原12段日程连续稳态通过数仍为固定7/12、周期扫频1/12、相位反馈6/12；没有因本次上传而提高。不能据此外推固定频率普遍最好。
- 参数来源登记区分设计工况、假设模型／控制参数、文献参考及待核实范围；不把文献组织数据直接写回假设器件模型。
- 已有静态AC对照、历史瞬态重放与五轮固定负载低幅LTspice反馈接口记录；这些不等于当前三策略的完整动态LTspice闭环验证。
- 恢复效率、恢复—重扫衔接、采样间隙硬限、动态负载反馈、器件辨识及结构声场仍未解决。负载研究原型尚未接入正式控制链。

验证日志见 [本次核验记录](release/20261012/verification.json)，复制文件清单见
[source_manifest.json](release/20261012/source_manifest.json)。**通过软件复核不等于控制全部验收通过，更不等于真实硬件安全。**
旧文件中的“不推送GitHub”等说明是生成当时记录，本次同步状态以发布登记为准。

## 科学口径

- `P_Rm` 是机械支路电阻的电学耗散，不是声功率；`eta_elec=P_port/P_source` 不是电声效率。
- 100 Vpp、5 mA RMS、50 Ω保留设计工况／推荐量级身份；软硬阈值与控制增益均非实测器件额定值。
- 捕获率以当前场景安全功率参考归一化，100%不等于恢复基准170 mW，也不代表全过程无损失。
- 相位反馈用匹配网络输入相位，基准标定后冻结；相位近零不保证最大功率或满足约束。
- 正式三级局部扫描为 ±50 kHz/5 kHz → ±5 kHz/1 kHz → ±1 kHz/0.1 kHz，并有有界回退。离线±20/50/100 kHz热图不能直接证明该方案最优。
- 保护后记录受限不能外推为采样间隙、执行延迟和载波瞬态绝不越限。SHA256只证明快照完整。

## 历史RAW与旧交接包

大型RAW等不包含在本次新增轻量快照中。需要历史完整原始证据时，查看
[旧交接下载说明](docs/history/README_main_20260915.md)及
[2026-09-15历史Release](https://github.com/buyaozhangbikoule/cto-virtual-drive-platform/releases/tag/handoff-2026-09-15)。
**旧Release不是当前代码版本**；不要用它覆盖本次正式整合目录。
旧PPT与讲稿未更新，不作为当前版本说明。历史目录、审核分支和失败记录均保留。

<details>
<summary>2026-09-15 历史首页原文（非当前状态，展开查看）</summary>

> 以下“尚未统一”等陈述仅指旧交接时点；当前状态以本页上半部及 CURRENT_RELEASE.json 为准。

## CTO超声换能器虚拟电学平台 · 私有交接仓库（历史）

基于假设BVD参数、有损L型匹配和戴维南源的电学仿真与控制研究原型。**非实测器件、非完整功放、非临床或声学验证。** 本仓库不声明开源许可，请保持私有；原始记录含内部本地路径和引用材料。

## 怎样取得完整项目

**优先下载 [2026-09-15交接Release](https://github.com/buyaozhangbikoule/cto-virtual-drive-platform/releases/tag/handoff-2026-09-15)**，而不只是点击绿色按钮“Download ZIP”。Git源代码归档不包含大型RAW、TIFF及部分构建检查文件。

为适应不稳定的上传连接，两个原始ZIP均拆成每块不超过16 MiB的附件：主包27块、RAW包148块。不是175个独立ZIP；分块不会改变原始文件内容。

1. 使用有此私有仓库访问权限的账号登录GitHub CLI，然后批量下载全部附件：

   ```powershell
   gh auth login
   gh release download handoff-2026-09-15 --repo buyaozhangbikoule/cto-virtual-drive-platform --dir handoff_download --skip-existing
   python handoff_download/restore_handoff_archives.py
   ```

   命令用法见 [GitHub CLI官方文档](https://cli.github.com/manual/gh_release_download)。没有GitHub CLI也可在Release页面逐项下载，但必须保存所有分块、`ARCHIVE_MANIFEST.json` 和 `restore_handoff_archives.py` 到同一目录。不要将账号密码或令牌发给聊天助手。
2. 合并脚本逐块及整包校验SHA256，输出 `project_handoff_main.zip` 和 `project_handoff_raw.zip`。若已有同名文件且校验一致则跳过，不覆盖不一致的文件。
3. 将两个ZIP解压到同一个父目录，得到 `CTO_Handoff_20260915/`。
4. 阅读其中的 `00_先读_项目交接说明.md`，按说明安装依赖并用 `handoff.py prepare` 建立工作副本。

原始主包SHA256：`085bbf0c937de70e65e37289f226e4259645038ec798ca0dc28a641213c38775`。
原始RAW包SHA256：`739b1ca924b20c638b7fcf04e7019f9417e845b77cd68bee4b29e427620b2a24`。

解压后约5.2 GB；分块、合并和工作副本需要额外空间，建议至少12 GB可用。LTspice、Python、ANSYS/COMSOL的安装程序及许可证不在交接包内。

## Git仓库和完整交接包的区别

Git保留可审阅的代码、配置、结果表、PNG/PDF图、PPT及讲稿。`GIT_CONTENT_INDEX.json`列出从交接快照纳入的文件，`GIT_OMISSIONS.json`列出仅随Release保留的文件。原完整 `FILE_MANIFEST.json`也保留，但在精简Git树直接执行原`handoff.py verify`会提示未纳入Git的文件缺失；**完整验证应在两个Release包解压合并后进行**。

不要在历史 `workspace/` 快照中直接运行会覆盖结果的脚本。源文件原有本机路径与旧描述为历史信息，最新迁移与口径说明见 `docs/`。

## 当前进度与未完成事项

- 已有线性BVD、匹配、单因素与组合扰动、选频评估和Python/LTspice静态对照。
- 已有固定频率、周期扫频、相位反馈原型；P&O为扩展。现存批次不足以进行统一三策略正式排名。
- 已有真实LTspice历史指令瞬态重放；固定负载、低幅的五轮真实反馈接口检查。
- 尚未完成统一全场景闭环验收、动态负载反馈、全过程／采样间隙硬约束证明及结构—声场求解。
- 最新32页汇报在 `reports/`；算法消融、失败和历史批次保留，不用后续成绩覆盖旧结果。

### 扫描参数说明（交接后的补充澄清）

当前原型三级扫描为：**±50 kHz／5 kHz → ±5 kHz／1 kHz → ±1 kHz／0.1 kHz**，各级围绕当前频率或上级候选峰。PPT中±20／±50／±100 kHz的热图是固定中心、均匀步长的离线比较，不能直接证明三级扫描最优或已覆盖全部34场景。扩大窗口与三级方案的同口径比较尚需验证。本次上传不改写仿真数据或PPT来掩盖这一缺口。

## 主要入口

- `workspace/CTO_virtual_drive_platform_v2_1/streamlit_app.py`：平台页面。
- `workspace/CTO_virtual_drive_platform_v2_1/pages/03_LTspice闭环验证.py`：真实反馈实验页。
- `workspace/outputs/v2_self_consistent_rebuild/active_stage3_5/`：活动模型和阶段脚本。
- `docs/`：接手顺序、数据导航、历史勘误与边界。
- `reports/`：最新PPT和逐页讲稿。

私有仓库不会自动向接手人开放；仓库所有者需要另行邀请其GitHub账号。本次上传不自动添加协作者、不部署网页、不触发仿真。

</details>
