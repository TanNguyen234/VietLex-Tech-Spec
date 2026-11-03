import builtins
import pytest
import numpy as np
import subprocess
import sys

from app.evaluation.qwen_lora_embedder import QwenLoraEmbedder, DEFAULT_ADAPTER_DIR


def test_optional_ml_runtime_is_not_needed_to_import_module():
    script = r"""
import builtins
real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "torch" or name.startswith("torch.") or name in {"transformers", "peft"}:
        raise AssertionError(f"optional ML dependency imported at module load: {name}")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import app.evaluation.qwen_lora_embedder
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


def test_missing_torch_is_reported_when_embedder_is_created(monkeypatch):
    real_import = builtins.__import__

    def without_torch(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_torch)
    with pytest.raises(RuntimeError, match="optional PyTorch dependency"):
        QwenLoraEmbedder(adapter_path=None)


@pytest.mark.live
def test_qwen_lora_adapter_exists():
    assert DEFAULT_ADAPTER_DIR.exists(), f"Adapter dir not found: {DEFAULT_ADAPTER_DIR}"
    assert (DEFAULT_ADAPTER_DIR / "adapter_model.safetensors").exists(), "Missing adapter_model.safetensors"
    assert (DEFAULT_ADAPTER_DIR / "adapter_config.json").exists(), "Missing adapter_config.json"


@pytest.mark.live
def test_qwen_lora_embedder_semantic_scoring():
    embedder = QwenLoraEmbedder(device="cpu")
    assert embedder.vector_size == 1024

    query = "thời hạn góp vốn thành lập công ty tnhh"
    pos_doc = "Thành viên phải góp vốn cho công ty đủ và đúng loại tài sản đã cam kết trong thời hạn 90 ngày kể từ ngày được cấp Giấy chứng nhận đăng ký doanh nghiệp."
    neg_doc = "Người điều khiển xe mô tô, xe gắn máy vi phạm nồng độ cồn vượt quá 0.4 miligam/1 lít khí thở sẽ bị phạt tiền và tước quyền sử dụng giấy phép lái xe."

    q_vec = np.array(embedder.embed_query(query))
    docs_vec = embedder.embed_texts([pos_doc, neg_doc])

    # Check vector properties
    assert q_vec.shape == (1024,)
    assert docs_vec.shape == (2, 1024)
    assert np.isclose(np.linalg.norm(q_vec), 1.0, atol=1e-3), "Query vector not L2 normalized"
    assert np.isclose(np.linalg.norm(docs_vec[0]), 1.0, atol=1e-3), "Doc 0 vector not L2 normalized"
    assert np.isclose(np.linalg.norm(docs_vec[1]), 1.0, atol=1e-3), "Doc 1 vector not L2 normalized"

    # Compute cosine similarity
    sim_pos = float(np.dot(q_vec, docs_vec[0]))
    sim_neg = float(np.dot(q_vec, docs_vec[1]))

    print("\n[Qwen3 LoRA Semantic Check]")
    print(f"Similarity (Query, Positive Legal Chunk): {sim_pos:.4f}")
    print(f"Similarity (Query, Negative Distractor):   {sim_neg:.4f}")
    print(f"Delta Margin:                           {sim_pos - sim_neg:.4f}")

    assert sim_pos > sim_neg, f"Expected pos ({sim_pos}) > neg ({sim_neg})"
    assert (sim_pos - sim_neg) > 0.1, f"Margin too small: {sim_pos - sim_neg}"


if __name__ == "__main__":
    test_qwen_lora_adapter_exists()
    test_qwen_lora_embedder_semantic_scoring()
    print("Preflight test PASSED successfully!")
