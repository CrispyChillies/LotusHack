from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()


_ALLOWED_NODE_TYPES = {"Person", "Event", "Object", "Emotion", "Place", "Time"}
_ALLOWED_RELATIONS = {
    "is_daughter_of",
    "is_son_of",
    "is_child_of",
    "is_parent_of",
    "is_spouse_of",
    "is_sibling_of",
    "happened_at",
    "feels",
    "related_to",
    "before",
    "after",
    "owns",
    "attended",
}


@dataclass(frozen=True)
class EntityNode:
    node_type: str
    name: str
    confidence: float = 0.8
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class RelationEdge:
    source_name: str
    target_name: str
    relation_type: str
    confidence: float = 0.8
    evidence: str | None = None
    temporal_hint: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    nodes: list[EntityNode]
    edges: list[RelationEdge]
    summary: str
    extracted_at: datetime
    model: str


class EntityRelationExtractor:
    """
    Extract entities and relations from image + note context.

    Strategy:
    - If OpenAI config is available, use LLM JSON extraction (best quality).
    - Fallback to deterministic rule-based extraction for reliability.
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY")
        self._llm_model = os.getenv("OPENAI_LLM_MODEL", "gpt-4.1-mini")

    def extract_from_memory_item(
        self,
        *,
        note_text: str,
        image_url: str | None = None,
        existing_entities: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        if self._api_key:
            llm_result = self._extract_with_llm(
                note_text=note_text,
                image_url=image_url,
                existing_entities=existing_entities or [],
                context=context or {},
            )
            if llm_result is not None:
                return llm_result

        return self._extract_with_rules(note_text=note_text, existing_entities=existing_entities or [])

    def _extract_with_llm(
        self,
        *,
        note_text: str,
        image_url: str | None,
        existing_entities: list[str],
        context: dict[str, Any],
    ) -> ExtractionResult | None:
        try:
            from openai import OpenAI
        except Exception:
            return None

        client = OpenAI(api_key=self._api_key)
        schema_description = {
            "nodes": [
                {
                    "node_type": "Person|Event|Object|Emotion|Place|Time",
                    "name": "string",
                    "confidence": "0..1",
                    "attributes": {"optional": "object"},
                }
            ],
            "edges": [
                {
                    "source_name": "node name",
                    "target_name": "node name",
                    "relation_type": "is_daughter_of|is_son_of|is_child_of|is_parent_of|is_spouse_of|is_sibling_of|happened_at|feels|related_to|before|after|owns|attended",
                    "confidence": "0..1",
                    "evidence": "short quote",
                    "temporal_hint": "optional",
                }
            ],
            "summary": "one-line summary",
        }

        system_prompt = (
            "You extract graph entities and relations for memory retrieval. "
            "Use concise normalized names, re-use existing entities when semantically the same, "
            "and return only valid JSON."
        )

        user_payload: dict[str, Any] = {
            "existing_entities": existing_entities,
            "context": context,
            "note_text": note_text,
            "output_schema": schema_description,
        }

        content: list[dict[str, Any]] = [
            {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)}
        ]
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        try:
            response = client.chat.completions.create(
                model=self._llm_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return self._normalize_extraction_payload(data, model=self._llm_model)
        except Exception:
            return None

    def _extract_with_rules(self, *, note_text: str, existing_entities: list[str]) -> ExtractionResult:
        text = note_text.strip()
        if not text:
            return ExtractionResult(
                nodes=[],
                edges=[],
                summary="",
                extracted_at=datetime.now(timezone.utc),
                model="rules-v1",
            )

        person_candidates = re.findall(r"\b[A-Z][a-z]{1,30}\b", text)
        emotion_keywords = {
            "happy": "happy",
            "sad": "sad",
            "angry": "angry",
            "excited": "excited",
            "worried": "worried",
        }
        event_keywords = {
            "birthday": "birthday",
            "camping": "camping trip",
            "wedding": "wedding",
            "graduation": "graduation",
            "party": "party",
        }

        nodes: list[EntityNode] = []
        seen: set[tuple[str, str]] = set()

        def add_node(node_type: str, name: str, confidence: float = 0.7) -> None:
            canonical = self._canonical_name(name)
            key = (node_type, canonical)
            if key in seen:
                return
            seen.add(key)
            nodes.append(EntityNode(node_type=node_type, name=name.strip(), confidence=confidence, attributes=None))

        for person in person_candidates:
            merged = self._merge_with_existing(person, existing_entities)
            add_node("Person", merged, 0.65)

        lower = text.lower()
        for kw, label in event_keywords.items():
            if kw in lower:
                add_node("Event", label, 0.75)
        for kw, label in emotion_keywords.items():
            if kw in lower:
                add_node("Emotion", label, 0.8)

        edges: list[RelationEdge] = []
        persons = [n.name for n in nodes if n.node_type == "Person"]
        events = [n.name for n in nodes if n.node_type == "Event"]
        emotions = [n.name for n in nodes if n.node_type == "Emotion"]

        if persons and events:
            edges.append(
                RelationEdge(
                    source_name=persons[0],
                    target_name=events[0],
                    relation_type="attended",
                    confidence=0.6,
                    evidence=text[:140],
                )
            )
        if persons and emotions:
            edges.append(
                RelationEdge(
                    source_name=persons[0],
                    target_name=emotions[0],
                    relation_type="feels",
                    confidence=0.65,
                    evidence=text[:140],
                )
            )

        summary = text[:220]
        return ExtractionResult(
            nodes=nodes,
            edges=edges,
            summary=summary,
            extracted_at=datetime.now(timezone.utc),
            model="rules-v1",
        )

    def _normalize_extraction_payload(self, payload: dict[str, Any], *, model: str) -> ExtractionResult:
        nodes: list[EntityNode] = []
        edges: list[RelationEdge] = []

        for raw_node in payload.get("nodes", []):
            node_type = str(raw_node.get("node_type", "")).strip()
            name = str(raw_node.get("name", "")).strip()
            if not node_type or not name:
                continue
            if node_type not in _ALLOWED_NODE_TYPES:
                continue
            confidence = float(raw_node.get("confidence", 0.8))
            confidence = max(0.0, min(1.0, confidence))
            attrs = raw_node.get("attributes")
            nodes.append(EntityNode(node_type=node_type, name=name, confidence=confidence, attributes=attrs))

        for raw_edge in payload.get("edges", []):
            relation_type = str(raw_edge.get("relation_type", "")).strip()
            source_name = str(raw_edge.get("source_name", "")).strip()
            target_name = str(raw_edge.get("target_name", "")).strip()
            if not relation_type or not source_name or not target_name:
                continue
            if relation_type not in _ALLOWED_RELATIONS:
                relation_type = "related_to"
            confidence = float(raw_edge.get("confidence", 0.8))
            confidence = max(0.0, min(1.0, confidence))
            edges.append(
                RelationEdge(
                    source_name=source_name,
                    target_name=target_name,
                    relation_type=relation_type,
                    confidence=confidence,
                    evidence=raw_edge.get("evidence"),
                    temporal_hint=raw_edge.get("temporal_hint"),
                )
            )

        summary = str(payload.get("summary", "")).strip()
        return ExtractionResult(
            nodes=nodes,
            edges=edges,
            summary=summary,
            extracted_at=datetime.now(timezone.utc),
            model=model,
        )

    @staticmethod
    def _canonical_name(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _merge_with_existing(self, candidate: str, existing_entities: list[str]) -> str:
        canonical = self._canonical_name(candidate)
        for existing in existing_entities:
            if self._canonical_name(existing) == canonical:
                return existing
        return candidate


def build_graphiti_compatible_payload(result: ExtractionResult) -> dict[str, Any]:
    """
    Return a Graphiti-like payload shape so you can plug into Zep Graphiti later
    without rewriting extraction output.
    """
    return {
        "nodes": [
            {
                "type": node.node_type,
                "name": node.name,
                "attributes": node.attributes or {},
                "confidence": node.confidence,
            }
            for node in result.nodes
        ],
        "edges": [
            {
                "source": edge.source_name,
                "target": edge.target_name,
                "relation": edge.relation_type,
                "confidence": edge.confidence,
                "evidence": edge.evidence,
                "temporal_hint": edge.temporal_hint,
            }
            for edge in result.edges
        ],
        "meta": {
            "summary": result.summary,
            "extracted_at": result.extracted_at.isoformat(),
            "model": result.model,
        },
    }
