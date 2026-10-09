import argparse
import concurrent.futures
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from PIL import Image


MODULE_PATH = Path(__file__).with_name("fit_reference_tryon.py")
SPEC = importlib.util.spec_from_file_location("fit_reference_tryon", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_image(path: Path, color: str = "#7f8c8d") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 100), color).save(path)
    return path.resolve()


class FitReferenceTryOnTests(unittest.TestCase):
    def test_worker_count_is_bounded(self):
        self.assertEqual(MODULE.worker_count("1"), 1)
        self.assertEqual(MODULE.worker_count("8"), 8)
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE.worker_count("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE.worker_count("9")

    def test_generation_workers_overlap_and_checkpoint_stays_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint_path = root / "checkpoint.json"
            checkpoint = {
                "schema_version": 2,
                "run_id": "concurrent-test",
                "config": {},
                "upload_cache": {},
                "tasks": {},
            }
            jobs = []
            for index in range(3):
                key = f"SKU{index}::model{index}"
                output = root / f"result_{index}.png"
                checkpoint["tasks"][key] = {
                    "sku": f"SKU{index}",
                    "model_path": str(root / f"model{index}.png"),
                    "output_path": str(output),
                    "prompt_path": str(root / f"prompt{index}.txt"),
                    "ordered_image_urls": [f"https://example.test/{index}.png"],
                    "provider": "toapis",
                    "status": "prepared",
                    "prompt": f"prompt {index}",
                }
                jobs.append({"key": key, "output_path": str(output)})

            MODULE.checkpoint_save(checkpoint_path, checkpoint)
            store = MODULE.CheckpointStore(checkpoint_path, checkpoint)
            active = 0
            peak = 0
            active_lock = threading.Lock()

            def fake_submit(*args, **kwargs):
                nonlocal active, peak
                with active_lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.08)
                with active_lock:
                    active -= 1
                return f"task-{threading.get_ident()}"

            def fake_poll(api_key, task_id, task, persist):
                task["provider_status"] = "completed"
                task["result_url"] = f"https://example.test/{task_id}.png"
                persist(task)
                time.sleep(0.03)
                return b"generated-image"

            with (
                mock.patch.object(MODULE, "submit_toapis", side_effect=fake_submit),
                mock.patch.object(MODULE, "poll_toapis", side_effect=fake_poll),
                concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor,
            ):
                futures = [
                    executor.submit(
                        MODULE.execute_generation_job,
                        job,
                        store,
                        "test-key",
                        "",
                        "gpt-image-2",
                        "3:4",
                        "2K",
                    )
                    for job in jobs
                ]
                for future in futures:
                    future.result()

            self.assertGreaterEqual(peak, 2)
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [task["status"] for task in saved["tasks"].values()],
                ["completed", "completed", "completed"],
            )
            self.assertTrue(all(Path(job["output_path"]).is_file() for job in jobs))

    def test_existing_provider_task_is_polled_without_resubmission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint_path = root / "checkpoint.json"
            key = "SKU1::model"
            output = root / "result.png"
            checkpoint = {
                "schema_version": 2,
                "run_id": "resume-test",
                "config": {},
                "upload_cache": {},
                "tasks": {
                    key: {
                        "sku": "SKU1",
                        "model_path": str(root / "model.png"),
                        "output_path": str(output),
                        "prompt_path": str(root / "prompt.txt"),
                        "ordered_image_urls": ["https://example.test/input.png"],
                        "provider": "toapis",
                        "provider_task_id": "existing-task-id",
                        "status": "polling_interrupted",
                        "prompt": "prompt",
                    }
                },
            }
            MODULE.checkpoint_save(checkpoint_path, checkpoint)
            store = MODULE.CheckpointStore(checkpoint_path, checkpoint)

            def fake_poll(api_key, task_id, task, persist):
                self.assertEqual(task_id, "existing-task-id")
                task["provider_status"] = "completed"
                persist(task)
                return b"recovered-image"

            with (
                mock.patch.object(
                    MODULE,
                    "submit_toapis",
                    side_effect=AssertionError("resume must not submit"),
                ),
                mock.patch.object(MODULE, "poll_toapis", side_effect=fake_poll),
            ):
                MODULE.execute_generation_job(
                    {"key": key, "output_path": str(output)},
                    store,
                    "test-key",
                    "",
                    "gpt-image-2",
                    "3:4",
                    "2K",
                )

            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["tasks"][key]["status"], "completed")
            self.assertEqual(output.read_bytes(), b"recovered-image")

    def test_run_command_executes_paid_stage_concurrently(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            work_dir = target / "_aigc_fit_work" / "run-concurrent"
            inventory_path = work_dir / "inventory.json"
            selections_path = work_dir / "selections.json"
            inventory = {
                "schema_version": 1,
                "run_id": "run-concurrent",
                "work_dir": str(work_dir),
                "skus": [],
            }
            selections = {
                "schema_version": 1,
                "run_id": "run-concurrent",
                "skus": [],
            }
            for index in range(3):
                sku_name = f"SKU{index}"
                sku_dir = target / sku_name
                model = make_image(sku_dir / f"model{index}.png")
                product = make_image(sku_dir / "上身" / f"product{index}.png")
                inventory["skus"].append({
                    "sku": sku_name,
                    "folder": str(sku_dir),
                    "model_candidates": [str(model)],
                    "product_candidates": [str(product)],
                    "local_fit_candidates": {"upper": [], "lower": []},
                    "library_lookup": {"images": []},
                })
                selections["skus"].append({
                    "sku": sku_name,
                    "models": [{"path": str(model), "view": "front"}],
                    "ignored_product_files": [],
                    "product_groups": [{
                        "product_id": "upper_1",
                        "garment_area": "upper",
                        "product_type": "hoodie",
                        "files": [{"path": str(product), "view": "front"}],
                        "fit_reference": None,
                    }],
                })
            MODULE.json_save(inventory_path, inventory)
            MODULE.json_save(selections_path, selections)

            active = 0
            peak = 0
            active_lock = threading.Lock()

            def fake_poll(api_key, task_id, task, persist):
                nonlocal active, peak
                with active_lock:
                    active += 1
                    peak = max(peak, active)
                task["provider_status"] = "in_progress"
                persist(task)
                time.sleep(0.08)
                task["provider_status"] = "completed"
                task["result_url"] = f"https://example.test/{task_id}.png"
                persist(task)
                with active_lock:
                    active -= 1
                return b"end-to-end-image"

            args = argparse.Namespace(
                inventory=str(inventory_path),
                selections=str(selections_path),
                language_model="gpt-5.6-sol",
                generation_model="gpt-image-2",
                aspect_ratio="3:4",
                resolution="2K",
                max_workers=3,
                resume=False,
            )
            with (
                mock.patch.object(MODULE, "prompt_secret", return_value="test-key"),
                mock.patch.object(
                    MODULE,
                    "upload_image",
                    side_effect=lambda api_key, path: f"https://example.test/{Path(path).name}",
                ),
                mock.patch.object(MODULE, "generate_prompt", return_value="generated prompt"),
                mock.patch.object(
                    MODULE,
                    "submit_toapis",
                    side_effect=lambda *args, **kwargs: f"task-{threading.get_ident()}",
                ),
                mock.patch.object(MODULE, "poll_toapis", side_effect=fake_poll),
            ):
                self.assertEqual(MODULE.run_command(args), 0)

            self.assertGreaterEqual(peak, 2)
            saved = json.loads((work_dir / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["concurrency"]["max_workers"], 3)
            self.assertTrue(all(
                task["status"] == "completed"
                for task in saved["tasks"].values()
            ))
            results = list(target.glob("SKU*/result_run-concurrent_*.png"))
            self.assertEqual(len(results), 3)

    def test_tokenized_directory_matching_is_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = root / "oversized02_上装OVRZ02_上装OVRZ03"
            expected.mkdir()
            (root / "slim01-1_上装SLIM01-1").mkdir()
            (root / "slim01_").mkdir()
            self.assertEqual(MODULE.match_tokenized_directories(root, ["上装OVRZ03"]), [expected.resolve()])
            self.assertEqual(MODULE.match_tokenized_directories(root, ["slim01"]), [(root / "slim01_").resolve()])

    def test_figure_products_first_and_explicit_reference_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "model.jpg")
            top = make_image(root / "top.jpg", "red")
            pants = make_image(root / "pants.jpg", "blue")
            bag = make_image(root / "bag.jpg", "green")
            top_ref = make_image(root / "top_ref.jpg", "pink")
            pants_ref = make_image(root / "pants_ref.jpg", "cyan")
            groups = [
                {
                    "product_id": "top_1", "garment_area": "upper", "product_type": "hoodie",
                    "files": [{"path": str(top), "view": "front"}],
                    "fit_reference": {"path": str(top_ref), "reason": "same oversized shoulder"},
                },
                {
                    "product_id": "pants_1", "garment_area": "lower", "product_type": "pants",
                    "files": [{"path": str(pants), "view": "front"}],
                    "fit_reference": {"path": str(pants_ref), "reason": "same straight leg"},
                },
                {
                    "product_id": "bag_1", "garment_area": "accessory", "product_type": "bag",
                    "files": [{"path": str(bag), "view": "front"}],
                    "fit_reference": None,
                },
            ]
            plan = MODULE.build_figure_plan({"path": str(model), "view": "front"}, groups)
            self.assertEqual([item["role"] for item in plan], [
                "model", "product", "product", "product", "fit_reference", "fit_reference"
            ])
            self.assertEqual([item["for_product_figure"] for item in plan[4:]], [2, 3])
            mapping = MODULE.build_mapping_text(plan)
            self.assertIn("Figure 4 has NO fit-reference Figure", mapping)
            self.assertIn("Figure 5 is the fit-and-silhouette reference ONLY", mapping)

    def test_product_view_is_selected_per_model_before_numbering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "model_back.jpg")
            front = make_image(root / "product_front.jpg")
            back = make_image(root / "product_back.jpg")
            groups = [{
                "product_id": "upper_1",
                "garment_area": "upper",
                "product_type": "tshirt",
                "files": [
                    {"path": str(front), "view": "front"},
                    {"path": str(back), "view": "back"},
                ],
                "fit_reference": None,
            }]
            plan = MODULE.build_figure_plan({"path": str(model), "view": "back"}, groups)
            self.assertEqual(plan[1]["path"], str(back))
            self.assertEqual(plan[1]["figure"], 2)

    def test_open_and_released_drawcord_hems_receive_deterministic_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "model.jpg")
            pants = make_image(root / "pants.jpg")
            groups = [{
                "product_id": "lower_1",
                "garment_area": "lower",
                "product_type": "pants",
                "files": [{"path": str(pants), "view": "front"}],
                "lower_hem": {
                    "type": "open",
                    "reason": "Visible full-length non-elastic opening.",
                },
                "fit_reference": None,
            }]
            plan = MODULE.build_figure_plan({"path": str(model), "view": "front"}, groups)
            mapping = MODULE.build_mapping_text(plan)
            self.assertIn("AUTHORITATIVE LOWER-HEM CONTRACT", mapping)
            self.assertIn("open, non-elastic hems", mapping)

            final_prompt = MODULE.apply_lower_hem_contracts("Generated edit prompt.", plan)
            self.assertIn("partially over the shoe upper", final_prompt)
            self.assertEqual(MODULE.validate_prompt_contracts(final_prompt, plan), [])
            self.assertTrue(MODULE.validate_prompt_contracts("Generated edit prompt.", plan))

            groups[0]["lower_hem"] = {
                "type": "drawcord_released",
                "reason": "Visible adjustable hem drawcords should remain loose.",
            }
            drawcord_plan = MODULE.build_figure_plan(
                {"path": str(model), "view": "front"}, groups
            )
            drawcord_prompt = MODULE.apply_lower_hem_contracts(
                "Generated edit prompt.", drawcord_plan
            )
            self.assertIn("drawcords fully released", drawcord_prompt)
            self.assertEqual(
                MODULE.validate_prompt_contracts(drawcord_prompt, drawcord_plan), []
            )

    def test_true_cuff_does_not_receive_open_hem_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "model.jpg")
            pants = make_image(root / "pants.jpg")
            groups = [{
                "product_id": "lower_1",
                "garment_area": "lower",
                "product_type": "pants",
                "files": [{"path": str(pants), "view": "front"}],
                "lower_hem": {
                    "type": "elastic_cuff",
                    "reason": "Visible fixed elastic cuff.",
                },
                "fit_reference": None,
            }]
            plan = MODULE.build_figure_plan({"path": str(model), "view": "front"}, groups)
            self.assertNotIn("AUTHORITATIVE LOWER-HEM CONTRACT", MODULE.build_mapping_text(plan))
            self.assertEqual(
                MODULE.apply_lower_hem_contracts("Generated edit prompt.", plan),
                "Generated edit prompt.",
            )
            self.assertEqual(MODULE.validate_prompt_contracts("Generated edit prompt.", plan), [])

    def test_excel_and_library_prepare(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "target"
            sku = target / "SKU001-01TBLK-M"
            make_image(sku / "model_front.jpg")
            make_image(sku / "上身" / "product.jpg")
            make_image(sku / "上身" / "已处理" / "old_result.jpg")
            library = base / "library"
            fit_dir = library / "卫衣_Hoodie" / "oversized02_上装OVRZ02_上装OVRZ03"
            library_image = make_image(fit_dir / "reference.jpg")

            workbook_path = base / "requirements.xlsx"
            workbook = Workbook()
            spu = workbook.active
            spu.title = "SPU数据"
            spu.append(["SPU(业务通用)", "二级类目-AM", "三级目录-AM"])
            spu.append(["SKU001", "Hoodie", "卫衣"])
            aigc = workbook.create_sheet("AIGC需求")
            aigc.append(["SKU", "SPU", "版型"])
            aigc.append(["SKU001-01TBLK-M", "SKU001", "上装OVRZ03, 上装OVRZ03"])
            workbook.save(workbook_path)

            args = argparse.Namespace(
                root=str(target), table_excel=str(workbook_path), table_json=None, library=str(library)
            )
            self.assertEqual(MODULE.prepare(args), 0)
            runs = sorted((target / "_aigc_fit_work").iterdir())
            inventory = json.loads((runs[-1] / "inventory.json").read_text(encoding="utf-8"))
            selections = json.loads((runs[-1] / "selections.json").read_text(encoding="utf-8"))
            entry = inventory["skus"][0]
            self.assertEqual(selections["schema_version"], 2)
            self.assertEqual(entry["library_lookup"]["category_match_level"], "三级目录-AM")
            self.assertEqual(entry["library_lookup"]["images"], [str(library_image)])
            self.assertEqual(entry["table"]["fit_values"], ["上装OVRZ03"])
            self.assertEqual([Path(path).name for path in entry["product_candidates"]], ["product.jpg"])

    def test_validation_requires_local_reference_and_preserves_missing_lower_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "SKU1" / "model.jpg")
            top = make_image(root / "SKU1" / "上身" / "top.jpg")
            pants = make_image(root / "SKU1" / "上身" / "pants.jpg")
            local_top = make_image(root / "SKU1" / "版型参考_上装" / "fit.jpg")
            inventory = {
                "run_id": "run1",
                "skus": [{
                    "sku": "SKU1",
                    "model_candidates": [str(model)],
                    "product_candidates": [str(top), str(pants)],
                    "local_fit_candidates": {"upper": [str(local_top)], "lower": []},
                    "library_lookup": {"images": []},
                }],
            }
            selections = {
                "schema_version": 2,
                "run_id": "run1",
                "skus": [{
                    "sku": "SKU1",
                    "models": [{"path": str(model), "view": "front"}],
                    "ignored_product_files": [],
                    "product_groups": [
                        {
                            "product_id": "upper_1", "garment_area": "upper", "product_type": "hoodie",
                            "files": [{"path": str(top), "view": "front"}],
                            "fit_reference": {"path": str(local_top), "source": "local_upper", "reason": "same fit"},
                        },
                        {
                            "product_id": "lower_1", "garment_area": "lower", "product_type": "pants",
                            "files": [{"path": str(pants), "view": "front"}],
                            "lower_hem": {
                                "type": "open",
                                "reason": "Visible full-length non-elastic opening.",
                            },
                            "fit_reference": None,
                        },
                    ],
                }],
            }
            self.assertEqual(MODULE.validate_selection_data(inventory, selections), [])
            selections["skus"][0]["product_groups"][0]["fit_reference"] = None
            errors = MODULE.validate_selection_data(inventory, selections)
            self.assertTrue(any("本地版型参考文件夹非空" in error for error in errors))

    def test_schema_v2_requires_reviewed_lower_hem_for_pants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "SKU1" / "model.jpg")
            pants = make_image(root / "SKU1" / "上身" / "pants.jpg")
            inventory = {
                "run_id": "run1",
                "skus": [{
                    "sku": "SKU1",
                    "model_candidates": [str(model)],
                    "product_candidates": [str(pants)],
                    "local_fit_candidates": {"upper": [], "lower": []},
                    "library_lookup": {"images": []},
                }],
            }
            selections = {
                "schema_version": 2,
                "run_id": "run1",
                "skus": [{
                    "sku": "SKU1",
                    "models": [{"path": str(model), "view": "front"}],
                    "ignored_product_files": [],
                    "product_groups": [{
                        "product_id": "lower_1",
                        "garment_area": "lower",
                        "product_type": "pants",
                        "files": [{"path": str(pants), "view": "front"}],
                        "fit_reference": None,
                    }],
                }],
            }
            errors = MODULE.validate_selection_data(inventory, selections)
            self.assertTrue(any("必须填写 lower_hem" in error for error in errors))

            selections["skus"][0]["product_groups"][0]["lower_hem"] = {
                "type": "open",
                "reason": "Visible full-length non-elastic opening.",
            }
            self.assertEqual(MODULE.validate_selection_data(inventory, selections), [])

            selections["skus"][0]["product_groups"][0]["lower_hem"]["type"] = "wide"
            errors = MODULE.validate_selection_data(inventory, selections)
            self.assertTrue(any("lower_hem.type 无效" in error for error in errors))

    def test_companion_product_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "SKU1" / "model.jpg")
            main = make_image(root / "SKU1" / "上身" / "SKU平铺图.jpg")
            companion = make_image(root / "SKU1" / "上身" / "搭配品平铺图.jpg")
            inventory = {
                "run_id": "run1",
                "skus": [{
                    "sku": "SKU1", "model_candidates": [str(model)],
                    "product_candidates": [str(main), str(companion)],
                    "local_fit_candidates": {"upper": [], "lower": []},
                    "library_lookup": {"images": []},
                }],
            }
            selections = {
                "schema_version": 2, "run_id": "run1",
                "skus": [{
                    "sku": "SKU1", "models": [{"path": str(model), "view": "front"}],
                    "product_groups": [{
                        "product_id": "upper_1", "garment_area": "upper", "product_type": "shirt",
                        "files": [{"path": str(main), "view": "front"}], "fit_reference": None,
                    }],
                    "ignored_product_files": [{"path": str(companion), "reason": "styling reference"}],
                }],
            }
            errors = MODULE.validate_selection_data(inventory, selections)
            self.assertTrue(any("搭配品属于必须上身" in error for error in errors))
            self.assertTrue(any("搭配品必须进入 product_groups" in error for error in errors))

    def test_front_back_views_are_one_product_figure_and_all_groups_are_covered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = make_image(root / "model.jpg")
            top_front = make_image(root / "top_front.jpg")
            top_back = make_image(root / "top_back.jpg")
            pants = make_image(root / "pants.jpg")
            groups = [
                {
                    "product_id": "upper_1", "garment_area": "upper", "product_type": "shirt",
                    "files": [
                        {"path": str(top_front), "view": "front"},
                        {"path": str(top_back), "view": "back"},
                    ], "fit_reference": None,
                },
                {
                    "product_id": "lower_1", "garment_area": "lower", "product_type": "pants",
                    "files": [{"path": str(pants), "view": "unknown"}],
                    "lower_hem": {"type": "open", "reason": "open hem"},
                    "fit_reference": None,
                },
            ]
            plan = MODULE.build_figure_plan({"path": str(model), "view": "back"}, groups)
            products = [item for item in plan if item["role"] == "product"]
            self.assertEqual(len(products), 2)
            self.assertEqual(Path(products[0]["path"]).name, "top_back.jpg")
            self.assertEqual(MODULE.validate_figure_product_coverage("SKU1", groups, plan), [])


if __name__ == "__main__":
    unittest.main()
