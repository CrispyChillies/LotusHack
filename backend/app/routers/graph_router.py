from fastapi import APIRouter

from app.schemas.graph import ExtractPreviewRequest, ExtractPreviewResponse
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
