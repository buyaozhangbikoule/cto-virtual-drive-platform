# CTO超声换能器虚拟电学平台 · 私有交接仓库

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
- `review/`：2026-09-17算法合理性与物理可实现性审查，含两个只读脚本（均不写入`workspace/`）。`audit_algorithm_physics.py`复算审查中的每个数字；`proposed_fixes_prototype.py`在活动模型旁验证建议的修法。审查指出三级扫描是局部搜索且失效时不置标志、`arg(Zin)`相位闭环在中等以上扰动下会锁到匹配网络零点，并对照两篇参考文献核对了BVD参数的物理量级。修正方案见`review/05_建议修正方案与验证_2026-09-17.md`，落地须先用`handoff.py prepare`建工作副本，不改历史快照。

私有仓库不会自动向接手人开放；仓库所有者需要另行邀请其GitHub账号。本次上传不自动添加协作者、不部署网页、不触发仿真。
