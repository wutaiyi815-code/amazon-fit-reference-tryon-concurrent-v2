---
name: amazon-fit-reference-tryon-concurrent-v2
description: Strict concurrent batch virtual try-on for apparel SKU folders. Requires every actual product in 上身, including 搭配品, to be worn; groups front/back views as one product; validates complete product Figure coverage before any paid generation; and preserves resumable ToAPIs or RunningHub task IDs.
---

# Amazon Fit Reference Try-On — Concurrent

Use this independent concurrent skill for SKU-folder product try-on when fit/silhouette references must be selected from local `版型参考_上装` / `版型参考_下装` folders or from the Amazon fit library using the 亚马逊视觉需求表. It does not modify or call the sequential `amazon-fit-reference-tryon` skill.

The main agent owns all semantic image decisions. The helper script inventories files, reads normalized Excel data, resolves tokenized library folders, validates the explicit selection manifest, builds stable Figure order, calls the providers, and checkpoints remote task IDs. Do not replace visual inspection with filename guessing.

## Required inputs

- Target root whose immediate child folders are SKUs.
- 亚马逊视觉需求表 as either a local Excel workbook or a DingTalk AI-table link/base.
- Fit-library path supplied explicitly with `--library`. Do not assume or publish a machine-specific default path; verify the resolved directory before continuing.
- Provider/model choices, aspect ratio, resolution, and API credentials immediately before a paid generation stage. Never persist or print credentials.

## Non-negotiable image rules

- Each SKU root contains model images. `上身` contains actual product images. Never treat files in either fit-reference folder as products or models.
- Ignore generated `result_*` files, contact sheets, and workflow artifacts when discovering model images.
- A nonempty local `版型参考_上装` or `版型参考_下装` has priority for that garment area. Visually choose the closest local candidate; do not replace it with a library image.
- Only a missing/empty local reference area may fall back to spreadsheet plus library lookup. If `版型` is blank or lookup is unreliable, use no fit reference for that product.
- `版型参考_上装` can only serve upper-body products. `版型参考_下装` can serve lower-body products, including skirts. Never force either onto full-body products or accessories.
- Product images control the actual item: color, fabric, pattern, panels, stripes, logos, hardware, waistband, and all key design details.
- Fit-reference images control only length, looseness, shoulder shape, body volume, sleeve shape, leg width, silhouette, and drape. Never transfer color, pattern, logo, material, accessory, or product design from them.
- Every fit reference defaults to one best product only. If correspondence is not reliable, omit it.
- For every visually identified pants product in a new schema-v2 selection, classify `lower_hem.type` from the original product images. Use `open` only for full-length non-elastic hems and `drawcord_released` only when adjustable hem drawcords must stay loose. Do not apply either rule to true cuffs, cinched hems, cropped pants, shorts, or uncertain construction.
- Open-hem contracts control only the pants' lower opening and natural contact with footwear. They do not change the shoes or add a global socks/footwear visibility rule.

## Workflow

1. Read [table and library matching](references/table_library_matching.md) before inspecting the spreadsheet source or library.
2. For local Excel, run `prepare` with `--table-excel`. For DingTalk, use the official DingTalk AI-table tools described below, write the normalized read-only JSON schema from the reference, then run `prepare` with `--table-json`.
3. Run `prepare` to create an inventory, selection template, and labeled contact sheets in `_aigc_fit_work/<run-id>/`. This stage does not call a paid model.
4. Inspect every SKU's product images, model images, and candidate fit references yourself. Use the contact sheets for overview and open individual originals before committing subtle fit judgments.
5. Read [selection manifest schema](references/selection_schema.md), then complete `selections.json`:
   - classify each root model image as `front`, `back`, `side`, or `unknown`;
   - inventory every actual product in `上身`; filenames containing `搭配品` or `搭配品平铺图` are actual try-on products and must never be treated as optional styling references;
   - group front/back views of the same colorway and design into one logical product (`product_id`), not two products; use visual identity, not filename order alone;
   - keep genuinely different products in separate groups. If two products compete for the same exclusive body area and a reliable layered-wear plan cannot be established, stop for review instead of silently ignoring either product;
   - assign stable `product_id`, `garment_area`, `product_type`, and per-file `view`;
   - for every `lower` / `pants` group, visually classify `lower_hem.type` and record the evidence in `lower_hem.reason`;
   - choose at most one fit reference for each logical product and record a short visual reason;
   - keep `fit_reference` null when no reliable match exists.
6. Run `validate-selections`. Resolve every error before any API call. V2 rejects any `搭配品` image in `ignored_product_files` and requires every such image to belong to a logical product group.
7. Read [prompt writer system](references/prompt_writer_system.md). Run the generation stage in a PTY/session so credential prompts remain interactive and the process stays recoverable.
8. For every model image, the helper selects the product view matching that model, then creates one immutable Figure plan:
   - Figure 1 = model;
   - all selected actual product images next;
   - all used fit-reference images last.
   Each reference record explicitly names its product Figure. Missing references create no placeholder and do not shift correspondence.
9. The prompt-writing request and final image-generation request must reuse the exact same ordered URL list. Review the logged Figure plan before submission. V2 independently checks that every logical product group appears exactly once as a product Figure for every model image; a missing or duplicate product aborts before upload and paid generation.
   For `open` and `drawcord_released` pants, the helper deterministically appends the corresponding lower-hem contract and validates its presence before the paid image stage. Do not replace this with a global shoe/sock visibility instruction.
10. After all jobs are prepared, run paid submissions and provider polling through a bounded thread pool. `--max-workers` defaults to 3 and accepts 1–8. Preparation remains deterministic and Figure order never depends on worker completion order.
11. Save results beside the SKU model image as `result_<run-id>_<model-stem>.png`. Preserve logs, Figure plans, prompts, uploaded URL cache, remote task IDs, per-task errors, and status in the work directory.

## Concurrency contract

- Concurrency applies to paid generation submission, polling, download, and result saving. File discovery, visual review, Figure planning, uploads, and prompt preparation finish before the concurrent paid stage.
- Use `--max-workers 3` by default. Raise it only when the user requests more throughput and the provider account can tolerate the corresponding rate and cost.
- Every worker uses a private task snapshot. Checkpoint writes are serialized and each provider task ID is persisted immediately after submission.
- A process lock prevents two runs from mutating the same work directory. Never bypass it or start two processes against the same `checkpoint.json`.
- One worker failure does not cancel other workers. Completed artifacts remain valid; report failed task keys and use `--resume` only when a provider task ID exists.
- A submission with no recoverable provider task ID is marked `submission_unknown` and is not automatically resubmitted, preventing accidental duplicate charges.

## DingTalk AI-table route

- Treat DingTalk as read-only.
- Resolve an AliDocs `/i/nodes/<id>` node as candidate `baseId`, verify it with `getNotableAllSheets` using operator `Q1qWXObu3IL0Ka7DPGWzqAiEiE`, and resolve the `SPU数据` and `AIGC需求` data-table IDs and necessary field IDs.
- Use the official `钉钉 AI 表格` `query_records` tool for row reads. From `AIGC需求`, request full SKU, SPU, and `版型`; from `SPU数据`, request SPU plus `二级类目-AM` and `三级目录-AM`. Use a limit up to 100 and follow `nextCursor` until empty.
- Preserve duplicate SKU rows in the normalized JSON and flag them for review rather than silently choosing a conflicting value.
- Do not switch to browser automation unless the MCP route has been checked and the exact failing layer is known.

## Commands

```powershell
python scripts/fit_reference_tryon.py prepare --root "<目标根目录>" --table-excel "<亚马逊视觉需求表.xlsx>" --library "<版型库目录>"

python scripts/fit_reference_tryon.py prepare --root "<目标根目录>" --table-json "<钉钉规范化数据.json>" --library "<版型库目录>"

python scripts/fit_reference_tryon.py validate-selections --inventory "<inventory.json>" --selections "<selections.json>"

python scripts/fit_reference_tryon.py run --inventory "<inventory.json>" --selections "<selections.json>" --generation-model gpt-image-2 --language-model gpt-5.6-sol --aspect-ratio 3:4 --resolution 2K --max-workers 3

python scripts/fit_reference_tryon.py run --inventory "<inventory.json>" --selections "<selections.json>" --resume --max-workers 3
```

Use the script located relative to this `SKILL.md`, not a copied stale path.

Before the first run, verify the active Python has the three runtime packages without displaying credentials:

```powershell
python -c "import requests, PIL, openpyxl; print('runtime dependencies OK')"
```

## Liveness and recovery

- Before submission, verify the work directory and checkpoint path and show the user the last completed stage.
- Run long commands through a resumable session. Provide a user-facing update every 45–55 seconds with the last confirmed provider state and next check.
- The helper persists each remote task ID before that worker starts polling. After interruption, inspect the checkpoint and use `--resume`; never blindly resubmit a possibly completed paid task.
- Each worker's polling wait is bounded and emits task-specific heartbeat output. Summarize concurrent states in user-facing updates rather than reporting unverified aggregate progress.
- After three recovery checks with no new evidence, stop silent polling, preserve artifacts, and report the exact failed layer.
