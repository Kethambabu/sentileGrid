from backend.rag.loaders.document_loader import load_documents_from_dir
from backend.rag.seed_knowledge_base import MSDS_DIR, SOPS_DIR


def test_load_sops_from_dir():
    docs = load_documents_from_dir(SOPS_DIR)
    assert len(docs) == 2
    assert all(doc.text.strip() for doc in docs)
    names = {d.source_name for d in docs}
    assert "reactor_high_pressure_response" in names
    assert "cooling_water_system_maintenance" in names


def test_load_msds_from_dir():
    docs = load_documents_from_dir(MSDS_DIR)
    assert len(docs) == 2
    assert all(doc.text.strip() for doc in docs)
