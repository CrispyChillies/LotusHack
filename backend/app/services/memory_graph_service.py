from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from fastapi import HTTPException, status
from psycopg.rows import dict_row

from app.services.extract_entity_relation import EntityRelationExtractor, ExtractionResult
from app.services.media_service import generate_download_url

load_dotenv()


@dataclass(frozen=True)
class HybridSearchItem:
    source_type: str
    source_id: str
    content: str
    vector_score: float
    graph_score: float
    final_score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GraphEdgeResult:
    source_node: str
    target_node: str
    relation_type: str
    confidence: float
    evidence: str | None
    temporal_hint: str | None


class MemoryGraphService:
    def __init__(self) -> None:
        self.extractor = EntityRelationExtractor()
        self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

    @staticmethod
    def _get_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._get_env("DATABASE_URL"), row_factory=dict_row)

    @lru_cache(maxsize=1)
    def _has_pgvector(self) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.commit()
            return True
        except Exception:
            return False

    @lru_cache(maxsize=1)
    def init_storage(self) -> None:
        use_vector = self._has_pgvector()
        embedding_column = f"vector({self.embedding_dimensions})" if use_vector else "double precision[]"

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS memory_graph_nodes (
                        id UUID PRIMARY KEY,
                        family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                        node_type VARCHAR(32) NOT NULL,
                        canonical_name VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255) NOT NULL,
                        attributes JSONB,
                        source_type VARCHAR(32),
                        source_id UUID,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (family_id, node_type, canonical_name)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_graph_edges (
                        id UUID PRIMARY KEY,
                        family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                        source_node_id UUID NOT NULL REFERENCES memory_graph_nodes(id) ON DELETE CASCADE,
                        target_node_id UUID NOT NULL REFERENCES memory_graph_nodes(id) ON DELETE CASCADE,
                        relation_type VARCHAR(64) NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
                        evidence TEXT,
                        temporal_hint VARCHAR(128),
                        source_type VARCHAR(32),
                        source_id UUID,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (family_id, source_node_id, target_node_id, relation_type)
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS memory_graph_documents (
                        id UUID PRIMARY KEY,
                        family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
                        source_type VARCHAR(32) NOT NULL,
                        source_id UUID NOT NULL,
                        content TEXT NOT NULL,
                        content_tsv TSVECTOR,
                        metadata JSONB,
                        embedding {embedding_column},
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (family_id, source_type, source_id)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_mgn_family ON memory_graph_nodes(family_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_mge_family ON memory_graph_edges(family_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_mgd_family ON memory_graph_documents(family_id)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_mgd_tsv ON memory_graph_documents USING GIN(content_tsv)"
                )
                if use_vector:
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_mgd_embedding ON memory_graph_documents USING ivfflat (embedding vector_cosine_ops)"
                    )
            conn.commit()

    async def sync_family_graph(self, family_id: str, limit: int = 200) -> dict[str, int]:
        self.init_storage()
        family_uuid = self._as_uuid(family_id, "family_id")

        rows = self._load_memory_sources(family_uuid=family_uuid, limit=limit)
        if not rows:
            return {"processed": 0, "nodes": 0, "edges": 0, "documents": 0}

        total_nodes = 0
        total_edges = 0
        total_documents = 0

        existing_entities = self._list_existing_entity_names(family_uuid)

        for row in rows:
            source_type = row["source_type"]
            source_id = str(row["source_id"])
            note_text = row["text"] or ""
            image_url = row.get("image_url")

            if image_url:
                try:
                    image_url = generate_download_url(image_url)
                except Exception:
                    image_url = None

            extraction = self.extractor.extract_from_memory_item(
                note_text=note_text,
                image_url=image_url,
                existing_entities=existing_entities,
                context={"source_type": source_type, "source_id": source_id},
            )

            upserted = self._upsert_extraction(
                family_uuid=family_uuid,
                source_type=source_type,
                source_id=source_id,
                source_text=note_text,
                extraction=extraction,
            )
            total_nodes += upserted["nodes"]
            total_edges += upserted["edges"]
            total_documents += upserted["documents"]

        return {
            "processed": len(rows),
            "nodes": total_nodes,
            "edges": total_edges,
            "documents": total_documents,
        }

    async def hybrid_search(
        self,
        *,
        family_id: str,
        query: str,
        top_k: int = 10,
        node_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[HybridSearchItem]:
        self.init_storage()
        family_uuid = self._as_uuid(family_id, "family_id")
        if not query.strip():
            return []

        query_embedding = self._embed_text(query)
        vector_hits = self._vector_hits(
            family_uuid=family_uuid,
            query=query,
            query_embedding=query_embedding,
            top_k=max(5, top_k * 3),
        )
        graph_hits = self._graph_hits(
            family_uuid=family_uuid,
            query=query,
            node_types=node_types,
            relation_types=relation_types,
            start_time=start_time,
            end_time=end_time,
            top_k=max(5, top_k * 3),
        )

        merged: dict[tuple[str, str], HybridSearchItem] = {}
        for hit in vector_hits:
            key = (hit["source_type"], hit["source_id"])
            merged[key] = HybridSearchItem(
                source_type=hit["source_type"],
                source_id=hit["source_id"],
                content=hit["content"],
                vector_score=float(hit["vector_score"]),
                graph_score=0.0,
                final_score=float(hit["vector_score"]),
                metadata=hit.get("metadata") or {},
            )

        for hit in graph_hits:
            key = (hit["source_type"], hit["source_id"])
            existing = merged.get(key)
            graph_score = float(hit["graph_score"])
            if existing is None:
                merged[key] = HybridSearchItem(
                    source_type=hit["source_type"],
                    source_id=hit["source_id"],
                    content=hit["content"],
                    vector_score=0.0,
                    graph_score=graph_score,
                    final_score=graph_score,
                    metadata=hit.get("metadata") or {},
                )
            else:
                final_score = (0.65 * existing.vector_score) + (0.35 * graph_score)
                merged[key] = HybridSearchItem(
                    source_type=existing.source_type,
                    source_id=existing.source_id,
                    content=existing.content,
                    vector_score=existing.vector_score,
                    graph_score=graph_score,
                    final_score=final_score,
                    metadata=existing.metadata,
                )

        ranked = sorted(merged.values(), key=lambda x: x.final_score, reverse=True)
        return ranked[:top_k]

    async def advanced_memory_query(
        self,
        *,
        family_id: str,
        query: str,
        required_entities: list[str] | None = None,
        required_relations: list[str] | None = None,
        max_hops: int = 2,
        top_k: int = 10,
    ) -> dict[str, Any]:
        results = await self.hybrid_search(
            family_id=family_id,
            query=query,
            top_k=top_k,
            relation_types=required_relations,
        )

        graph_context = self._expand_graph_context(
            family_uuid=self._as_uuid(family_id, "family_id"),
            entity_names=required_entities or [],
            max_hops=max(1, min(max_hops, 4)),
            limit=100,
        )

        return {
            "query": query,
            "required_entities": required_entities or [],
            "required_relations": required_relations or [],
            "results": [item.__dict__ for item in results],
            "graph_context": graph_context,
        }

    def _load_memory_sources(self, *, family_uuid: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id AS source_id,
                           'media' AS source_type,
                           COALESCE(notes, '') AS text,
                           s3_url AS image_url,
                           uploaded_at AS at_time
                    FROM media
                    WHERE family_id = %s
                    UNION ALL
                    SELECT id AS source_id,
                           'memory' AS source_type,
                           COALESCE(title, '') || ' ' || COALESCE(ai_generated_story, '') AS text,
                           NULL AS image_url,
                           date_of_memory AS at_time
                    FROM memories
                    WHERE family_id = %s
                    ORDER BY at_time DESC NULLS LAST
                    LIMIT %s
                    """,
                    (family_uuid, family_uuid, max(1, min(limit, 1000))),
                )
                return cur.fetchall()

    def _list_existing_entity_names(self, family_uuid: str) -> list[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT display_name FROM memory_graph_nodes WHERE family_id = %s LIMIT 5000",
                    (family_uuid,),
                )
                rows = cur.fetchall()
        return [row["display_name"] for row in rows]

    def _upsert_extraction(
        self,
        *,
        family_uuid: str,
        source_type: str,
        source_id: str,
        source_text: str,
        extraction: ExtractionResult,
    ) -> dict[str, int]:
        node_id_by_name: dict[str, str] = {}
        node_upsert_count = 0
        edge_upsert_count = 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                for node in extraction.nodes:
                    canonical = self._canonical(node.name)
                    cur.execute(
                        """
                        INSERT INTO memory_graph_nodes (
                            id, family_id, node_type, canonical_name, display_name,
                            attributes, source_type, source_id, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        ON CONFLICT (family_id, node_type, canonical_name)
                        DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            attributes = EXCLUDED.attributes,
                            source_type = EXCLUDED.source_type,
                            source_id = EXCLUDED.source_id,
                            updated_at = now()
                        RETURNING id
                        """,
                        (
                            str(uuid.uuid4()),
                            family_uuid,
                            node.node_type,
                            canonical,
                            node.name,
                            psycopg.types.json.Jsonb(node.attributes or {}),
                            source_type,
                            source_id,
                        ),
                    )
                    returned = cur.fetchone()
                    if returned:
                        node_id_by_name[canonical] = str(returned["id"])
                        node_upsert_count += 1

                for edge in extraction.edges:
                    src_id = node_id_by_name.get(self._canonical(edge.source_name))
                    tgt_id = node_id_by_name.get(self._canonical(edge.target_name))
                    if not src_id or not tgt_id:
                        continue

                    cur.execute(
                        """
                        INSERT INTO memory_graph_edges (
                            id, family_id, source_node_id, target_node_id,
                            relation_type, confidence, evidence, temporal_hint,
                            source_type, source_id, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        ON CONFLICT (family_id, source_node_id, target_node_id, relation_type)
                        DO UPDATE SET
                            confidence = GREATEST(memory_graph_edges.confidence, EXCLUDED.confidence),
                            evidence = EXCLUDED.evidence,
                            temporal_hint = EXCLUDED.temporal_hint,
                            source_type = EXCLUDED.source_type,
                            source_id = EXCLUDED.source_id,
                            updated_at = now()
                        """,
                        (
                            str(uuid.uuid4()),
                            family_uuid,
                            src_id,
                            tgt_id,
                            edge.relation_type,
                            float(max(0.0, min(1.0, edge.confidence))),
                            edge.evidence,
                            edge.temporal_hint,
                            source_type,
                            source_id,
                        ),
                    )
                    edge_upsert_count += 1

                metadata = {
                    "summary": extraction.summary,
                    "model": extraction.model,
                    "source_type": source_type,
                    "source_id": source_id,
                }
                embedding = self._embed_text(source_text or extraction.summary or "")
                self._upsert_document(
                    cur=cur,
                    family_uuid=family_uuid,
                    source_type=source_type,
                    source_id=source_id,
                    content=source_text or extraction.summary,
                    metadata=metadata,
                    embedding=embedding,
                )
            conn.commit()

        return {"nodes": node_upsert_count, "edges": edge_upsert_count, "documents": 1}

    def _upsert_document(
        self,
        *,
        cur: psycopg.Cursor,
        family_uuid: str,
        source_type: str,
        source_id: str,
        content: str,
        metadata: dict[str, Any],
        embedding: list[float],
    ) -> None:
        if self._has_pgvector():
            embedding_param = f"[{','.join(f'{x:.8f}' for x in embedding)}]"
            cur.execute(
                """
                INSERT INTO memory_graph_documents (
                    id, family_id, source_type, source_id, content, content_tsv,
                    metadata, embedding, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, to_tsvector('simple', %s),
                    %s, %s::vector, now(), now()
                )
                ON CONFLICT (family_id, source_type, source_id)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    content_tsv = EXCLUDED.content_tsv,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
                """,
                (
                    str(uuid.uuid4()),
                    family_uuid,
                    source_type,
                    source_id,
                    content,
                    content,
                    psycopg.types.json.Jsonb(metadata),
                    embedding_param,
                ),
            )
            return

        cur.execute(
            """
            INSERT INTO memory_graph_documents (
                id, family_id, source_type, source_id, content, content_tsv,
                metadata, embedding, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, to_tsvector('simple', %s),
                %s, %s, now(), now()
            )
            ON CONFLICT (family_id, source_type, source_id)
            DO UPDATE SET
                content = EXCLUDED.content,
                content_tsv = EXCLUDED.content_tsv,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding,
                updated_at = now()
            """,
            (
                str(uuid.uuid4()),
                family_uuid,
                source_type,
                source_id,
                content,
                content,
                psycopg.types.json.Jsonb(metadata),
                embedding,
            ),
        )

    def _vector_hits(
        self,
        *,
        family_uuid: str,
        query: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if self._has_pgvector():
                    emb = f"[{','.join(f'{x:.8f}' for x in query_embedding)}]"
                    cur.execute(
                        """
                        SELECT source_type,
                               source_id::text AS source_id,
                               content,
                               metadata,
                               (1 - (embedding <=> %s::vector)) AS vector_score
                        FROM memory_graph_documents
                        WHERE family_id = %s
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (emb, family_uuid, emb, max(1, min(top_k, 200))),
                    )
                    return cur.fetchall()

                cur.execute(
                    """
                    SELECT source_type,
                           source_id::text AS source_id,
                           content,
                           metadata,
                           embedding
                    FROM memory_graph_documents
                    WHERE family_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (family_uuid, max(1, min(top_k * 10, 1000))),
                )
                rows = cur.fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            emb = row.get("embedding") or []
            score = self._cosine_similarity(query_embedding, emb) if emb else 0.0
            scored.append(
                {
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                    "content": row["content"],
                    "metadata": row.get("metadata") or {},
                    "vector_score": score,
                }
            )
        scored.sort(key=lambda x: x["vector_score"], reverse=True)
        return scored[:top_k]

    def _graph_hits(
        self,
        *,
        family_uuid: str,
        query: str,
        node_types: list[str] | None,
        relation_types: list[str] | None,
        start_time: datetime | None,
        end_time: datetime | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        tokens = [t.lower() for t in query.split() if len(t) >= 3]
        if not tokens:
            return []

        where_parts = ["n.family_id = %s"]
        params: list[Any] = [family_uuid]

        token_predicates = []
        for token in tokens[:8]:
            token_predicates.append("n.display_name ILIKE %s")
            params.append(f"%{token}%")
        if token_predicates:
            where_parts.append("(" + " OR ".join(token_predicates) + ")")

        if node_types:
            where_parts.append("n.node_type = ANY(%s)")
            params.append(node_types)

        if relation_types:
            where_parts.append("e.relation_type = ANY(%s)")
            params.append(relation_types)

        if start_time:
            where_parts.append("d.updated_at >= %s")
            params.append(start_time)
        if end_time:
            where_parts.append("d.updated_at <= %s")
            params.append(end_time)

        where_sql = " AND ".join(where_parts)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT d.source_type,
                           d.source_id::text AS source_id,
                           d.content,
                           d.metadata,
                           MAX(e.confidence) AS graph_score
                    FROM memory_graph_nodes n
                    JOIN memory_graph_edges e
                      ON e.family_id = n.family_id
                     AND (e.source_node_id = n.id OR e.target_node_id = n.id)
                    JOIN memory_graph_documents d
                      ON d.family_id = n.family_id
                     AND d.source_type = e.source_type
                     AND d.source_id = e.source_id
                    WHERE {where_sql}
                    GROUP BY d.source_type, d.source_id, d.content, d.metadata
                    ORDER BY graph_score DESC
                    LIMIT %s
                    """,
                    params + [max(1, min(top_k, 200))],
                )
                rows = cur.fetchall()

        return [
            {
                "source_type": r["source_type"],
                "source_id": r["source_id"],
                "content": r["content"],
                "metadata": r.get("metadata") or {},
                "graph_score": float(r["graph_score"] or 0.0),
            }
            for r in rows
        ]

    def _expand_graph_context(
        self,
        *,
        family_uuid: str,
        entity_names: list[str],
        max_hops: int,
        limit: int,
    ) -> dict[str, Any]:
        if not entity_names:
            return {"nodes": [], "edges": []}

        canonical_names = [self._canonical(x) for x in entity_names if x.strip()]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, node_type, display_name
                    FROM memory_graph_nodes
                    WHERE family_id = %s
                      AND canonical_name = ANY(%s)
                    """,
                    (family_uuid, canonical_names),
                )
                seed_nodes = cur.fetchall()

                if not seed_nodes:
                    return {"nodes": [], "edges": []}

                seed_ids = [str(n["id"]) for n in seed_nodes]
                cur.execute(
                    """
                    WITH RECURSIVE walk AS (
                        SELECT e.id,
                               e.source_node_id,
                               e.target_node_id,
                               e.relation_type,
                               e.confidence,
                               e.evidence,
                               e.temporal_hint,
                               1 AS depth
                        FROM memory_graph_edges e
                        WHERE e.family_id = %s
                          AND (e.source_node_id::text = ANY(%s) OR e.target_node_id::text = ANY(%s))
                        UNION ALL
                        SELECT e2.id,
                               e2.source_node_id,
                               e2.target_node_id,
                               e2.relation_type,
                               e2.confidence,
                               e2.evidence,
                               e2.temporal_hint,
                               w.depth + 1
                        FROM memory_graph_edges e2
                        JOIN walk w
                          ON e2.family_id = %s
                         AND (e2.source_node_id = w.target_node_id OR e2.target_node_id = w.source_node_id)
                        WHERE w.depth < %s
                    )
                    SELECT DISTINCT source_node_id, target_node_id, relation_type, confidence, evidence, temporal_hint
                    FROM walk
                    LIMIT %s
                    """,
                    (family_uuid, seed_ids, seed_ids, family_uuid, max_hops, max(1, min(limit, 500))),
                )
                edges = cur.fetchall()

                node_ids = set(seed_ids)
                for edge in edges:
                    node_ids.add(str(edge["source_node_id"]))
                    node_ids.add(str(edge["target_node_id"]))

                cur.execute(
                    """
                    SELECT id::text AS id, node_type, display_name, attributes
                    FROM memory_graph_nodes
                    WHERE family_id = %s
                      AND id::text = ANY(%s)
                    """,
                    (family_uuid, list(node_ids)),
                )
                nodes = cur.fetchall()

        return {
            "nodes": [
                {
                    "id": n["id"],
                    "node_type": n["node_type"],
                    "display_name": n["display_name"],
                    "attributes": n.get("attributes") or {},
                }
                for n in nodes
            ],
            "edges": [
                GraphEdgeResult(
                    source_node=str(e["source_node_id"]),
                    target_node=str(e["target_node_id"]),
                    relation_type=e["relation_type"],
                    confidence=float(e["confidence"] or 0.0),
                    evidence=e.get("evidence"),
                    temporal_hint=e.get("temporal_hint"),
                ).__dict__
                for e in edges
            ],
        }

    def _embed_text(self, text: str) -> list[float]:
        normalized = (text or "").strip()
        if not normalized:
            return [0.0] * self.embedding_dimensions

        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
                emb = client.embeddings.create(model=self.embedding_model, input=normalized)
                vector = emb.data[0].embedding
                if len(vector) == self.embedding_dimensions:
                    return vector
                if len(vector) > self.embedding_dimensions:
                    return vector[: self.embedding_dimensions]
                return vector + ([0.0] * (self.embedding_dimensions - len(vector)))
            except Exception:
                pass

        return self._hash_embedding(normalized, dim=self.embedding_dimensions)

    @staticmethod
    def _hash_embedding(text: str, dim: int) -> list[float]:
        vec = [0.0] * dim
        for token in text.lower().split():
            idx = abs(hash(token)) % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        size = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(size))
        na = math.sqrt(sum(a[i] * a[i] for i in range(size)))
        nb = math.sqrt(sum(b[i] * b[i] for i in range(size)))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def _canonical(value: str) -> str:
        return " ".join(value.lower().strip().split())

    @staticmethod
    def _as_uuid(raw: str, field_name: str) -> str:
        try:
            return str(UUID(raw))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {field_name}.",
            )


memory_graph_service = MemoryGraphService()
