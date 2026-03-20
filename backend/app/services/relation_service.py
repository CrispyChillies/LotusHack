from __future__ import annotations

import base64
import json
import os
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import HTTPException, status
import psycopg
from psycopg.rows import dict_row

from app.schemas.relation import JoinByQRRequest, JoinByQRResponse, RelationEdge

load_dotenv()

RELATION_INVERSE_MAP: dict[str, str] = {
    "father": "child",
    "mother": "child",
    "parent": "child",
    "child": "parent",
    "son": "parent",
    "daughter": "parent",
    "brother": "sibling",
    "sister": "sibling",
    "sibling": "sibling",
    "husband": "wife",
    "wife": "husband",
    "spouse": "spouse",
    "partner": "partner",
    "grandfather": "grandchild",
    "grandmother": "grandchild",
    "grandparent": "grandchild",
    "grandchild": "grandparent",
    "uncle": "niece/nephew",
    "aunt": "niece/nephew",
    "niece": "aunt/uncle",
    "nephew": "aunt/uncle",
    "niece/nephew": "aunt/uncle",
    "aunt/uncle": "niece/nephew",
    "cousin": "cousin",
}

_CHILD_TO_PATIENT = {"father", "mother", "parent"}
_SPOUSE_TO_PATIENT = {"husband", "wife", "spouse", "partner"}
_PARENT_TO_PATIENT = {"son", "daughter", "child"}
_SIBLING_TO_PATIENT = {"brother", "sister", "sibling"}


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    return db_url


def _connect() -> psycopg.Connection:
    return psycopg.connect(_get_database_url(), row_factory=dict_row)


def _normalize_relation(value: str) -> str:
    normalized = " ".join(value.strip().replace("_", " ").split()).lower()
    return normalized


def _display_relation(value: str) -> str:
    return value.strip()


def _decode_qr_token(qr_token: str) -> dict[str, str]:
    try:
        padded = qr_token + "=" * (-len(qr_token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        data = json.loads(decoded)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid qr_token format: {exc}",
        )

    required = {"family_id", "patient_id", "suggested_relation_to_patient"}
    if not required.issubset(data.keys()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="qr_token payload missing one of: family_id, patient_id, suggested_relation_to_patient",
        )
    return data


def _get_inverse_relation(relation_name: str) -> str:
    normalized = _normalize_relation(relation_name)
    return RELATION_INVERSE_MAP.get(normalized, "related")


def _infer_relation_between_members(
    new_user_to_patient: str,
    member_to_patient: str,
) -> tuple[str, str] | None:
    n = _normalize_relation(new_user_to_patient)
    m = _normalize_relation(member_to_patient)

    if n in _CHILD_TO_PATIENT and m in _CHILD_TO_PATIENT:
        return "sibling", "sibling"

    if n in _SPOUSE_TO_PATIENT and m in _CHILD_TO_PATIENT:
        return "parent", "child"

    if n in _CHILD_TO_PATIENT and m in _SPOUSE_TO_PATIENT:
        return "child", "parent"

    if n in _PARENT_TO_PATIENT and m in _PARENT_TO_PATIENT:
        return "spouse", "spouse"

    if n in _SIBLING_TO_PATIENT and m in _CHILD_TO_PATIENT:
        return "aunt/uncle", "niece/nephew"

    if n in _CHILD_TO_PATIENT and m in _SIBLING_TO_PATIENT:
        return "niece/nephew", "aunt/uncle"

    if n == m and n in _SIBLING_TO_PATIENT:
        return "sibling", "sibling"

    return None


def _build_edge(
    subject_user_id: UUID,
    object_user_id: UUID,
    relation_name: str,
    family_id: UUID,
    source: str,
) -> RelationEdge:
    return RelationEdge(
        subject_user_id=subject_user_id,
        object_user_id=object_user_id,
        relation_name=relation_name,
        family_id=family_id,
        source=source,
    )


def _insert_relation_if_absent(
    *,
    cur: psycopg.Cursor,
    cache: set[tuple[str, str]],
    created: list[RelationEdge],
    skipped: list[RelationEdge],
    subject_user_id: UUID,
    object_user_id: UUID,
    relation_name: str,
    family_id: UUID,
    source: str,
) -> None:
    if subject_user_id == object_user_id:
        skipped.append(
            _build_edge(subject_user_id, object_user_id, relation_name, family_id, source)
        )
        return

    key = (str(subject_user_id), str(object_user_id))
    edge = _build_edge(subject_user_id, object_user_id, relation_name, family_id, source)

    if key in cache:
        skipped.append(edge)
        return

    cur.execute(
        """
        INSERT INTO user_relations (id, subject_user_id, object_user_id, relation_name, family_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (str(uuid4()), str(subject_user_id), str(object_user_id), relation_name, str(family_id)),
    )
    cache.add(key)
    created.append(edge)


async def join_family_by_qr(new_user_id: UUID, payload: JoinByQRRequest) -> JoinByQRResponse:
    token_data = _decode_qr_token(payload.qr_token)

    try:
        family_id = UUID(str(token_data["family_id"]))
        patient_id = UUID(str(token_data["patient_id"]))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"qr_token contains invalid UUID: {exc}",
        )

    suggested_relation = _display_relation(str(token_data["suggested_relation_to_patient"]))
    inverse_relation = _get_inverse_relation(suggested_relation)

    created: list[RelationEdge] = []
    skipped: list[RelationEdge] = []

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT patient_id FROM families WHERE id = %s",
                    (str(family_id),),
                )
                family_row = cur.fetchone()
                if not family_row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Family not found",
                    )
                if str(family_row["patient_id"]) != str(patient_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="patient_id in qr_token does not match family patient",
                    )

                cur.execute(
                    """
                    SELECT subject_user_id, object_user_id
                    FROM user_relations
                    WHERE family_id = %s
                    """,
                    (str(family_id),),
                )
                existing_edges = cur.fetchall()
                edge_cache: set[tuple[str, str]] = {
                    (str(row["subject_user_id"]), str(row["object_user_id"]))
                    for row in existing_edges
                }

                _insert_relation_if_absent(
                    cur=cur,
                    cache=edge_cache,
                    created=created,
                    skipped=skipped,
                    subject_user_id=new_user_id,
                    object_user_id=patient_id,
                    relation_name=suggested_relation,
                    family_id=family_id,
                    source="direct",
                )

                _insert_relation_if_absent(
                    cur=cur,
                    cache=edge_cache,
                    created=created,
                    skipped=skipped,
                    subject_user_id=patient_id,
                    object_user_id=new_user_id,
                    relation_name=inverse_relation,
                    family_id=family_id,
                    source="inverse",
                )

                if payload.create_transitive:
                    cur.execute(
                        """
                        SELECT subject_user_id, relation_name
                        FROM user_relations
                        WHERE family_id = %s
                          AND object_user_id = %s
                          AND subject_user_id <> %s
                        """,
                        (str(family_id), str(patient_id), str(new_user_id)),
                    )
                    member_rows = cur.fetchall()

                    for row in member_rows:
                        member_id = UUID(str(row["subject_user_id"]))
                        member_to_patient = str(row["relation_name"])

                        inferred = _infer_relation_between_members(
                            suggested_relation,
                            member_to_patient,
                        )
                        if not inferred:
                            continue

                        new_to_member, member_to_new = inferred

                        _insert_relation_if_absent(
                            cur=cur,
                            cache=edge_cache,
                            created=created,
                            skipped=skipped,
                            subject_user_id=new_user_id,
                            object_user_id=member_id,
                            relation_name=new_to_member,
                            family_id=family_id,
                            source="transitive",
                        )

                        _insert_relation_if_absent(
                            cur=cur,
                            cache=edge_cache,
                            created=created,
                            skipped=skipped,
                            subject_user_id=member_id,
                            object_user_id=new_user_id,
                            relation_name=member_to_new,
                            family_id=family_id,
                            source="transitive_inverse",
                        )

            conn.commit()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join family by QR: {exc}",
        )

    return JoinByQRResponse(
        family_id=family_id,
        patient_id=patient_id,
        new_user_id=new_user_id,
        created=created,
        skipped=skipped,
    )
