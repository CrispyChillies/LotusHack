from fastapi import APIRouter

from app.schemas.graph import (
    ExtractPreviewRequest,
    ExtractPreviewResponse,
    GraphQueryRequest,
    GraphQueryResponse,
)
from app.services.extract_entity_relation import build_graphiti_compatible_payload
from app.services.memory_graph_service import memory_graph_service

router = APIRouter()


@router.post("/extract-preview", response_model=ExtractPreviewResponse)
async def extract_preview(payload: ExtractPreviewRequest):
    extraction = memory_graph_service.extractor.extract_from_memory_item(
        note_text=payload.note_text,
        image_url=payload.image_url,
        existing_entities=payload.existing_entities,
        context=payload.context,
    )

    graphiti_payload = build_graphiti_compatible_payload(extraction)
    return ExtractPreviewResponse(
        nodes=[
            {
                "node_type": n.node_type,
                "name": n.name,
                "confidence": n.confidence,
                "attributes": n.attributes or {},
            }
            for n in extraction.nodes
        ],
        edges=[
            {
                "source_name": e.source_name,
                "target_name": e.target_name,
                "relation_type": e.relation_type,
                "confidence": e.confidence,
                "evidence": e.evidence,
                "temporal_hint": e.temporal_hint,
            }
            for e in extraction.edges
        ],
        summary=extraction.summary,
        extracted_at=extraction.extracted_at.isoformat(),
        model=extraction.model,
        llm_error=memory_graph_service.extractor.last_llm_error,
        graphiti_payload=graphiti_payload,
    )


@router.post("/query", response_model=GraphQueryResponse)
async def graph_query(payload: GraphQueryRequest):
    if payload.use_advanced:
        advanced_result = await memory_graph_service.advanced_memory_query(
            family_id=str(payload.family_id),
            query=payload.query,
            required_entities=payload.required_entities,
            required_relations=payload.required_relations,
            max_hops=payload.max_hops,
            top_k=payload.top_k,
        )
        return GraphQueryResponse(
            mode="advanced",
            query=payload.query,
            family_id=payload.family_id,
            results=advanced_result.get("results", []),
            graph_context=advanced_result.get("graph_context"),
        )

    hybrid_items = await memory_graph_service.hybrid_search(
        family_id=str(payload.family_id),
        query=payload.query,
        top_k=payload.top_k,
        node_types=payload.node_types or None,
        relation_types=payload.relation_types or None,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )

    return GraphQueryResponse(
        mode="hybrid",
        query=payload.query,
        family_id=payload.family_id,
        results=[item.__dict__ for item in hybrid_items],
        graph_context=None,
    )
