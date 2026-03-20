from app.services.memory_graph_service import MemoryGraphService


def test_hash_embedding_and_cosine_similarity():
    service = MemoryGraphService()
    v1 = service._hash_embedding("sarah birthday happy", dim=64)
    v2 = service._hash_embedding("sarah birthday happy", dim=64)
    v3 = service._hash_embedding("different content entirely", dim=64)

    assert len(v1) == 64
    assert service._cosine_similarity(v1, v2) > 0.99
    assert service._cosine_similarity(v1, v3) < 0.95


def test_canonical_normalization():
    service = MemoryGraphService()
    assert service._canonical("  Sarah   Johnson ") == "sarah johnson"
