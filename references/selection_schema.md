# `selections.json` schema

`prepare` creates the file with every discovered model image and empty `product_groups`. The main agent must complete it after visually inspecting the contact sheets and original images.

## Complete example

```json
{
  "schema_version": 2,
  "run_id": "20260826_120000",
  "inventory": "D:\\job\\_aigc_fit_work\\20260826_120000\\inventory.json",
  "skus": [
    {
      "sku": "AE26XXXX",
      "models": [
        {
          "path": "D:\\job\\AE26XXXX\\model_front.jpg",
          "view": "front"
        },
        {
          "path": "D:\\job\\AE26XXXX\\model_back.jpg",
          "view": "back"
        }
      ],
      "product_groups": [
        {
          "product_id": "upper_1",
          "garment_area": "upper",
          "product_type": "hoodie",
          "files": [
            {
              "path": "D:\\job\\AE26XXXX\\上身\\hoodie_front.jpg",
              "view": "front"
            },
            {
              "path": "D:\\job\\AE26XXXX\\上身\\hoodie_back.jpg",
              "view": "back"
            }
          ],
          "fit_reference": {
            "path": "D:\\job\\AE26XXXX\\版型参考_上装\\oversized.jpg",
            "source": "local_upper",
            "reason": "Same dropped shoulder, long sleeve volume, and oversized body length."
          }
        },
        {
          "product_id": "lower_1",
          "garment_area": "lower",
          "product_type": "pants",
          "files": [
            {
              "path": "D:\\job\\AE26XXXX\\上身\\pants.jpg",
              "view": "front"
            }
          ],
          "lower_hem": {
            "type": "open",
            "reason": "The full-length pants have visibly open, non-elastic hems intended to fall over footwear."
          },
          "fit_reference": null
        }
      ],
      "ignored_product_files": [
        {
          "path": "D:\\job\\AE26XXXX\\上身\\unrelated_accessory.jpg",
          "reason": "Not one of the requested try-on products."
        }
      ]
    }
  ]
}
```

## Field rules

- `models` must contain every discovered root model image exactly once. Allowed `view`: `front`, `back`, `side`, `unknown`.
- `product_groups` represents logical products, not individual files. Put front and back views of the same colorway/design in one group. Confirm identity visually from color, fabric, graphics, trims, silhouette, and complementary construction; do not split front/back into two products merely because there are two files.
- Every actual product in `上身` must appear exactly once in a product group. Products named `搭配品` or `搭配品平铺图` are mandatory try-on products, not optional styling references, and validation forbids placing them in `ignored_product_files`.
- `ignored_product_files` is only for images visually confirmed not to depict a try-on product, such as an instruction card accidentally placed in `上身`. Its reason must state the non-product evidence. Never use it to resolve uncertain product identity or a same-area conflict.
- `product_id` must be stable and unique within the SKU. Prefer `upper_1`, `lower_1`, `shoes_1`, and similar role-based IDs.
- Allowed `garment_area`: `upper`, `lower`, `full`, `socks`, `shoes`, `accessory`, `unknown`.
- Use a specific `product_type` where visible: `tshirt`, `shirt`, `tank_top`, `hoodie`, `sweater`, `jacket`, `coat`, `vest`, `pants`, `shorts`, `skirt`, `dress`, `jumpsuit`, `socks`, `shoes`, `bag`, `hat`, `accessory`, or `unknown`.
- A product file's `view` uses the same allowed values as models. At generation time, the helper selects same-view first, then `unknown`, then the first file in that logical group.
- `fit_reference` is either null or one object with absolute `path`, `source`, and a short visual `reason`.
- In `schema_version: 2`, every `garment_area: lower` / `product_type: pants` group must include a visually reviewed `lower_hem` object with `type` and a concrete `reason`.
- Allowed `lower_hem.type`: `open`, `elastic_cuff`, `drawcord_released`, `drawcord_cinched`, `cropped`, `unknown`.
- Use `open` only for full-length, non-elastic leg openings that should fall naturally onto/over footwear. Use `drawcord_released` only when adjustable hem drawcords must remain fully loose. These two values add deterministic lower-hem instructions before paid generation.
- `elastic_cuff`, `drawcord_cinched`, `cropped`, and `unknown` do not receive the open-hem instruction. Never use `open` merely because the overall leg is wide; inspect the actual hem construction in the original product image.
- `lower_hem` is not allowed on shorts, skirts, upper garments, shoes, accessories, or other non-pants groups.
- Recommended `source` values are `local_upper`, `local_lower`, and `library`. Validation trusts the path allow-list and garment area rather than the label alone.
- Full-body products, socks, shoes, accessories, and unknown-area products cannot be assigned an upper/lower fit reference under the current business rule.
- More than one logical product in the same exclusive area is rejected for review instead of silently choosing or inventing layering.

## Figure invariant

Figure numbers do not appear in `selections.json`; they are derived separately for each model after selecting the matching product view:

1. model;
2. all products in deterministic garment-area order;
3. only the non-null fit references, in their product order.

The generated Figure plan records `for_product_figure` on every fit reference. Never infer correspondence from adjacency.

Before uploads or paid generation, v2 checks that the product Figures contain every `product_id` exactly once. Missing or duplicate logical products abort the run.
