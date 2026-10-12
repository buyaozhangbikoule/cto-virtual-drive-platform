# 模型目录

运行`python run_all.py --collect-only`后，本目录包含：

- `python/model_v2_1.py`：活动v2.1解析模型的归档副本；
- `ltspice/stage1`：裸BVD网表；
- `ltspice/stage2`：匹配前、理想匹配和活动有损匹配网表及匹配参数。

参数类别必须沿用`config.yaml`和模型源文件中的声明。这里没有实测换能器参数。
