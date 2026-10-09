# Amazon Fit Reference Try-On Concurrent v2

按 SKU 并发执行服装试穿，并把实际产品图与只控制廓形的版型参考图严格分开。付费生成前会校验每件实际产品是否恰好出现一次、Figure 顺序是否稳定，以及任务能否通过远程任务 ID 恢复。

## 基础信息

| 项目 | 内容 |
| --- | --- |
| 名称 | `amazon-fit-reference-tryon-concurrent-v2` |
| 类型 | Codex Skill / Python 并发图像工作流 |
| 源目录创建时间 | 2026-09-15 |
| 公开版本 | `2026.10.09` |
| 发布日期 | 2026-10-09 |
| 当前状态 | 可用；选择清单必须人工视觉审核 |

入口文件是 `SKILL.md`；命令行辅助程序是 `scripts/fit_reference_tryon.py`。

## 解决的问题与适用范围

适用于一个 SKU 同时包含模特图、多件实际产品和可选版型参考的批量试穿。产品图控制颜色、材质、图案、Logo、五金和结构；版型参考只控制衣长、松量、肩型、裤腿、廓形和垂坠。

不适用于无法确认实际产品分组、互斥服装无法建立可靠叠穿关系、或缺少人工图像判断的全自动生成。

## 严格输入要求

### SKU 目录

目标根目录的直接子目录必须是 SKU：

```text
<目标根目录>/
  <SKU>/
    <模特图，直接位于 SKU 根目录>
    上身/
      <所有实际产品图，包括文件名含“搭配品”或“搭配品平铺图”的图>
    版型参考_上装/       # 可选，本地非空时优先
      <上装版型候选图>
    版型参考_下装/       # 可选，本地非空时优先
      <下装或裙装版型候选图>
```

- 支持图片：`.jpg`、`.jpeg`、`.png`、`.webp`。
- SKU 根部图片才是模特图；`上身` 内全部图片都是实际产品，不得把“搭配品”降级为可选参考。
- 同一产品的正背面应合并为一个逻辑产品；不同产品必须分组。
- 本地对应版型目录非空时必须从中人工选择，不能改用公共版型库。

### 表格数据

`prepare` 必须二选一提供：

- `--table-excel`：Excel 必须同时包含 `AIGC需求` 和 `SPU数据`。`AIGC需求` 以完整 SKU 精确匹配并读取 `SPU`、`版型`；`SPU数据` 读取 SPU、`二级类目-AM`、`三级目录-AM`。
- `--table-json`：按 `references/table_library_matching.md` 的规范化 JSON 结构提供 `spu_data` 和 `aigc_requirements`，并保留重复记录。

冲突的重复 SKU 不会静默取第一条，而会阻止该 SKU 自动匹配。

### 版型库

必须通过 `--library "<版型库目录>"` 显式提供版型库根目录。本公开版本不包含任何个人电脑默认路径。版型库采用“品类目录/版型目录/图片”结构，目录标识按 `_`、`／` 或 `/` 分隔后做完整匹配，禁止任意子串匹配。

### selections.json

`prepare` 会创建选择模板。人工审核后，每个产品组必须填写稳定的 `product_id`、`garment_area`、`product_type`，每张产品图填写 `view`。裤装还必须根据原产品图记录 `lower_hem.type` 和理由。可靠版型参考最多一张；无法确认时保持 `null`。

每张模特图的顺序固定：Figure 1 = 模特图；随后是全部实际产品；最后才是使用到的版型参考。每个逻辑产品在产品 Figure 中必须恰好出现一次，校验失败时不会上传或付费生成。

## 环境与依赖

- Python 3.10+。
- `requests`、`Pillow`、`openpyxl`。
- 语言模型：`gemini-3.1-flash-lite` 或 `gpt-5.6-sol`。
- 生成模型：`gemini-3.1-flash-image-preview`、`gpt-image-2` 或 `gpt-image-2-rh`。
- 默认比例 `3:4`，默认分辨率 `4K`；分辨率只允许 `1K`、`2K`、`4K`。
- `--max-workers` 允许 1–8，默认 3。
- API 凭据只在运行时读取，不得写入仓库或日志。

```powershell
python -m pip install -r requirements.txt
```

## 使用流程

```powershell
python scripts/fit_reference_tryon.py prepare `
  --root "<目标根目录>" `
  --table-excel "<亚马逊视觉需求表.xlsx>" `
  --library "<版型库目录>"

python scripts/fit_reference_tryon.py validate-selections `
  --inventory "<_aigc_fit_work/.../inventory.json>" `
  --selections "<_aigc_fit_work/.../selections.json>"

python scripts/fit_reference_tryon.py run `
  --inventory "<inventory.json>" `
  --selections "<selections.json>" `
  --generation-model gpt-image-2 `
  --language-model gpt-5.6-sol `
  --aspect-ratio 3:4 `
  --resolution 2K `
  --max-workers 3
```

生成阶段把结果保存到 SKU 模特图旁，文件名为 `result_<run-id>_<model-stem>.png`。工作目录 `_aigc_fit_work/<run-id>/` 保留 inventory、selections、联系表、Figure 计划、提示词、上传缓存、远程任务 ID、状态和错误。中断后使用相同清单及 `--resume` 恢复，避免重复付费提交。

完整选择规范见 `references/selection_schema.md`，表格与版型库规则见 `references/table_library_matching.md`，提示词职责见 `references/prompt_writer_system.md`。

