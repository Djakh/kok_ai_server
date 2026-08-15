import json
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.storage.s3 import get_s3_client
from app.modules.trees.models import Tree, TreeImage
from app.modules.trees.repository import TreeRepository
from app.modules.uploads.models import UploadedAsset


class TreeDetectionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TreeRepository(db)
        self.settings = get_settings()

    def analyze_tree(self, tree_id: uuid.UUID) -> None:
        tree = self.repo.get_tree(tree_id)
        if not tree:
            return

        tree.ai_model_version = self.settings.tree_detector_model_version
        try:
            if not self.settings.tree_detector_enabled:
                self._set_tree_analysis(
                    tree,
                    status="skipped",
                    summary={"reason": "tree_detector_disabled"},
                )
                return

            model_path = Path(self.settings.tree_detector_model_path)
            if not model_path.exists():
                self._set_tree_analysis(
                    tree,
                    status="failed",
                    summary={"reason": "model_file_not_found", "model_path": str(model_path)},
                )
                return

            model = self._load_model(model_path)
            if model is None:
                self._set_tree_analysis(
                    tree,
                    status="failed",
                    summary={"reason": "ultralytics_not_installed"},
                )
                return

            images = self.repo.get_images(tree.id)
            assets = self._get_assets(images)
            image_results: dict[str, dict] = {}
            detected_count = 0
            max_confidence = 0.0

            for image in images:
                asset = assets.get(image.uploaded_asset_id)
                if not asset:
                    image_results[image.kind.value] = {
                        "detected": False,
                        "boxes_count": 0,
                        "max_confidence": 0.0,
                        "reason": "uploaded_asset_missing",
                    }
                    continue

                result = self._predict_asset(model, asset)
                if result["detected"]:
                    detected_count += 1
                    max_confidence = max(max_confidence, float(result["max_confidence"]))
                image_results[image.kind.value] = result

            summary = {
                "tree_detected": detected_count > 0,
                "images_with_detections": detected_count,
                "max_confidence": round(max_confidence, 4),
                "images": image_results,
            }
            self._set_tree_analysis(tree, status="completed", summary=summary)
        except Exception as exc:
            self._set_tree_analysis(tree, status="failed", summary={"reason": "analysis_error", "detail": str(exc)})

    def _load_model(self, model_path: Path):
        try:
            from ultralytics import YOLO
        except ImportError:
            return None
        return YOLO(str(model_path))

    def _get_assets(self, images: Iterable[TreeImage]) -> dict[uuid.UUID, UploadedAsset]:
        asset_ids = [image.uploaded_asset_id for image in images]
        if not asset_ids:
            return {}
        rows = self.db.query(UploadedAsset).filter(UploadedAsset.id.in_(asset_ids)).all()
        return {row.id: row for row in rows}

    def _predict_asset(self, model, asset: UploadedAsset) -> dict:
        client = get_s3_client()
        obj = client.get_object(Bucket=self.settings.s3_bucket, Key=asset.storage_key)
        content = obj["Body"].read()
        suffix = Path(asset.file_name).suffix or ".jpg"

        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            results = model.predict(
                source=tmp.name,
                conf=self.settings.tree_detector_confidence,
                verbose=False,
            )

        first = results[0]
        boxes = getattr(first, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return {"detected": False, "boxes_count": 0, "max_confidence": 0.0}

        confidences = [float(x) for x in boxes.conf.tolist()]
        return {
            "detected": True,
            "boxes_count": len(confidences),
            "max_confidence": round(max(confidences), 4),
        }

    def _set_tree_analysis(self, tree: Tree, status: str, summary: dict) -> None:
        tree.ai_status = status
        tree.ai_model_version = self.settings.tree_detector_model_version
        tree.ai_summary_json = json.dumps(summary)
        tree.ai_analyzed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(tree)
