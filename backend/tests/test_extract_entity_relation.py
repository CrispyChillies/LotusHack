from app.services.extract_entity_relation import (
    EntityRelationExtractor,
    ExtractionResult,
    build_graphiti_compatible_payload,
)


def test_rule_extraction_has_entities_and_edges():
    extractor = EntityRelationExtractor()
    result = extractor._extract_with_rules(
        note_text="Sarah felt happy at the birthday party with Anna.",
        existing_entities=["Anna"],
    )

    assert isinstance(result, ExtractionResult)
    names = {node.name for node in result.nodes}
    assert "Sarah" in names
    assert "Anna" in names
    assert any(node.node_type == "Emotion" and node.name == "happy" for node in result.nodes)
    assert any(edge.relation_type in {"attended", "feels"} for edge in result.edges)


def test_graphiti_payload_shape():
    extractor = EntityRelationExtractor()
    result = extractor._extract_with_rules(
        note_text="Anna was happy during camping.",
        existing_entities=[],
    )
    payload = build_graphiti_compatible_payload(result)

    assert "nodes" in payload
    assert "edges" in payload
    assert "meta" in payload
    assert isinstance(payload["nodes"], list)
