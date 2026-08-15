import uuid

from sqlalchemy.orm import Session

from app.modules.tree_analyses.models import TreeAnalysis, TreeAnalysisCandidate, TreeAnalysisImage


class TreeAnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, analysis_id: uuid.UUID, owner_id: uuid.UUID) -> TreeAnalysis | None:
        return (
            self.db.query(TreeAnalysis)
            .filter(TreeAnalysis.id == analysis_id, TreeAnalysis.owner_user_id == owner_id)
            .first()
        )

    def get_by_idempotency(
        self, owner_id: uuid.UUID, idempotency_key: str
    ) -> TreeAnalysis | None:
        return (
            self.db.query(TreeAnalysis)
            .filter(
                TreeAnalysis.owner_user_id == owner_id,
                TreeAnalysis.idempotency_key == idempotency_key,
            )
            .first()
        )

    def create(self, row: TreeAnalysis) -> TreeAnalysis:
        self.db.add(row)
        self.db.flush()
        return row

    def add_image(self, row: TreeAnalysisImage) -> TreeAnalysisImage:
        self.db.add(row)
        self.db.flush()
        return row

    def add_candidate(self, row: TreeAnalysisCandidate) -> TreeAnalysisCandidate:
        self.db.add(row)
        self.db.flush()
        return row

    def list_candidates(self, analysis_id: uuid.UUID) -> list[TreeAnalysisCandidate]:
        return (
            self.db.query(TreeAnalysisCandidate)
            .filter(TreeAnalysisCandidate.analysis_id == analysis_id)
            .order_by(TreeAnalysisCandidate.ordinal.asc())
            .all()
        )
