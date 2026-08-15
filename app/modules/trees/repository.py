import uuid

from geoalchemy2.functions import ST_DWithin, ST_MakePoint
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.common.pagination.cursor import decode_cursor
from app.modules.tree_analyses.models import (
    TreeAnalysis,
    TreeAnalysisCandidate,
    TreeAnalysisImage,
    TreeScan,
)
from app.modules.trees.models import Tree, TreeEvent, TreeImage, TreeLocation, TreeStatus


class TreeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_tree(self, row: Tree) -> Tree:
        self.db.add(row)
        self.db.flush()
        return row

    def create_image(self, row: TreeImage) -> TreeImage:
        self.db.add(row)
        self.db.flush()
        return row

    def create_location(self, row: TreeLocation) -> TreeLocation:
        self.db.add(row)
        self.db.flush()
        return row

    def create_event(self, row: TreeEvent) -> TreeEvent:
        self.db.add(row)
        self.db.flush()
        return row

    def get_tree(self, tree_id: uuid.UUID) -> Tree | None:
        return self.db.query(Tree).filter(Tree.id == tree_id, Tree.deleted_at.is_(None)).first()

    def list_trees(
        self,
        cursor: str | None,
        limit: int,
        status: str | None,
        owner_id: uuid.UUID | None,
        q: str | None,
        sort: str,
        viewer_id: uuid.UUID,
        species: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> list[Tree]:
        qry = self.db.query(Tree).filter(
            Tree.deleted_at.is_(None),
            or_(Tree.is_public.is_(True), Tree.owner_user_id == viewer_id),
        )
        if status:
            qry = qry.filter(Tree.status == TreeStatus(status))
        if owner_id:
            qry = qry.filter(Tree.owner_user_id == owner_id)
        if q:
            qry = qry.filter(
                or_(
                    Tree.name.ilike(f"%{q}%"),
                    Tree.confirmed_species.ilike(f"%{q}%"),
                    Tree.candidate_species.ilike(f"%{q}%"),
                )
            )
        if species:
            qry = qry.filter(
                or_(Tree.confirmed_species.ilike(species), Tree.candidate_species.ilike(species))
            )

        if cursor:
            cur_created_at, cur_id = decode_cursor(cursor)
            cur_uuid = uuid.UUID(cur_id)
            qry = qry.filter(
                or_(
                    Tree.created_at < cur_created_at,
                    and_(Tree.created_at == cur_created_at, Tree.id < cur_uuid),
                )
            )

        if sort == "nearest" and latitude is not None and longitude is not None:
            qry = qry.join(TreeLocation, TreeLocation.tree_id == Tree.id).order_by(
                text(
                    "ST_Distance(tree_locations.location, "
                    f"ST_SetSRID(ST_MakePoint({float(longitude)},{float(latitude)}),4326)::geography)"
                )
            )
        elif sort == "last_scanned":
            qry = qry.order_by(Tree.ai_analyzed_at.desc().nullslast(), Tree.id.desc())
        else:
            qry = qry.order_by(Tree.created_at.desc(), Tree.id.desc())
        return qry.limit(limit).all()

    def map_bbox(self, min_lng: float, min_lat: float, max_lng: float, max_lat: float, status: str | None):
        sql = text(
            """
            SELECT t.id
            FROM trees t
            JOIN tree_locations tl ON tl.tree_id=t.id
            WHERE t.deleted_at IS NULL
            AND t.is_public IS TRUE
            AND (:status IS NULL OR t.status=:status)
            AND ST_Intersects(
              tl.location::geometry,
              ST_MakeEnvelope(:min_lng,:min_lat,:max_lng,:max_lat,4326)
            )
            """
        )
        rows = self.db.execute(
            sql,
            {
                "min_lng": min_lng,
                "min_lat": min_lat,
                "max_lng": max_lng,
                "max_lat": max_lat,
                "status": status,
            },
        ).all()
        ids = [x[0] for x in rows]
        if not ids:
            return []
        return self.db.query(Tree).filter(Tree.id.in_(ids)).all()

    def map_center_radius(self, lat: float, lng: float, radius: float, status: str | None):
        point = ST_MakePoint(lng, lat)
        qry = self.db.query(Tree).join(TreeLocation, TreeLocation.tree_id == Tree.id)
        qry = qry.filter(
            Tree.deleted_at.is_(None),
            Tree.is_public.is_(True),
            ST_DWithin(TreeLocation.location, point, radius),
        )
        if status:
            qry = qry.filter(Tree.status == TreeStatus(status))
        return qry.limit(200).all()

    def list_events(self, tree_id: uuid.UUID) -> list[TreeEvent]:
        return (
            self.db.query(TreeEvent)
            .filter(TreeEvent.tree_id == tree_id)
            .order_by(TreeEvent.created_at.desc())
            .all()
        )

    def get_images(self, tree_id: uuid.UUID) -> list[TreeImage]:
        return self.db.query(TreeImage).filter(TreeImage.tree_id == tree_id).all()

    def get_location(self, tree_id: uuid.UUID) -> TreeLocation | None:
        return self.db.query(TreeLocation).filter(TreeLocation.tree_id == tree_id).first()

    def get_analysis(self, analysis_id: uuid.UUID, owner_id: uuid.UUID) -> TreeAnalysis | None:
        return (
            self.db.query(TreeAnalysis)
            .filter(
                TreeAnalysis.id == analysis_id,
                TreeAnalysis.owner_user_id == owner_id,
            )
            .first()
        )

    def get_candidate(
        self, candidate_id: uuid.UUID, analysis_id: uuid.UUID
    ) -> TreeAnalysisCandidate | None:
        return (
            self.db.query(TreeAnalysisCandidate)
            .filter(
                TreeAnalysisCandidate.id == candidate_id,
                TreeAnalysisCandidate.analysis_id == analysis_id,
            )
            .first()
        )

    def get_analysis_images(self, analysis_id: uuid.UUID) -> list[TreeAnalysisImage]:
        return (
            self.db.query(TreeAnalysisImage)
            .filter(TreeAnalysisImage.analysis_id == analysis_id)
            .order_by(TreeAnalysisImage.ordinal.asc())
            .all()
        )

    def nearby(
        self, latitude: float, longitude: float, radius_meters: float, viewer_id: uuid.UUID
    ):
        return self.db.execute(
            text(
                """
                SELECT t.id,
                       ST_Distance(tl.location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography) AS distance_meters
                FROM trees t JOIN tree_locations tl ON tl.tree_id=t.id
                WHERE t.deleted_at IS NULL
                  AND (t.is_public IS TRUE OR t.owner_user_id=:viewer_id)
                  AND ST_DWithin(tl.location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, :radius)
                ORDER BY distance_meters ASC, t.id ASC
                LIMIT 200
                """
            ),
            {"lat": latitude, "lng": longitude, "radius": radius_meters, "viewer_id": viewer_id},
        ).all()

    def create_scan(self, row: TreeScan) -> TreeScan:
        self.db.add(row)
        self.db.flush()
        return row

    def get_scan_by_analysis(self, analysis_id: uuid.UUID) -> TreeScan | None:
        return self.db.query(TreeScan).filter(TreeScan.analysis_id == analysis_id).first()

    def list_scans(self, tree_id: uuid.UUID, cursor: str | None, limit: int) -> list[TreeScan]:
        qry = self.db.query(TreeScan).filter(TreeScan.tree_id == tree_id)
        if cursor:
            analyzed_at, scan_id = decode_cursor(cursor)
            scan_uuid = uuid.UUID(scan_id)
            qry = qry.filter(
                or_(
                    TreeScan.analyzed_at < analyzed_at,
                    and_(TreeScan.analyzed_at == analyzed_at, TreeScan.id < scan_uuid),
                )
            )
        return qry.order_by(TreeScan.analyzed_at.desc(), TreeScan.id.desc()).limit(limit).all()
