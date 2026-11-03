from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence, Union

import numpy as np


def _load_torch():
    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as error:
        raise RuntimeError(
            "QwenLoraEmbedder requires the optional PyTorch dependency 'torch'."
        ) from error
    return torch, functional

DEFAULT_ADAPTER_DIR = Path(
    r"d:\Download\Kaggle\projects\vietlegal-retriever\results\v29_output\output\adapter"
)
DEFAULT_BASE_MODEL = "Qwen/Qwen3-Embedding-0.6B"


def last_token_pool(
    last_hidden_states: Any, attention_mask: Any
) -> Any:
    """Extract embeddings from the last non-padding token (matching Qwen3-Embedding pooling)."""
    torch, _ = _load_torch()
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[
        torch.arange(batch_size, device=last_hidden_states.device),
        sequence_lengths,
    ]


class QwenLoraEmbedder:
    """Embedder using fine-tuned Qwen3-Embedding-0.6B with LoRA adapter."""

    def __init__(
        self,
        adapter_path: Union[str, Path, None] = DEFAULT_ADAPTER_DIR,
        base_model_name: str = DEFAULT_BASE_MODEL,
        device: str | None = None,
    ) -> None:
        torch, functional = _load_torch()
        self._torch = torch
        self._functional = functional
        self.adapter_path = Path(adapter_path).resolve() if adapter_path else None
        self.base_model_name = base_model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.vector_size = 1024

        try:
            from transformers import AutoModel, AutoTokenizer
            from peft import PeftModel
        except ImportError as error:
            raise RuntimeError(
                "QwenLoraEmbedder requires the optional 'transformers' and 'peft' dependencies."
            ) from error

        tok_path = str(self.adapter_path) if (self.adapter_path and (self.adapter_path / "tokenizer.json").exists()) else self.base_model_name
        self.tokenizer = AutoTokenizer.from_pretrained(
            tok_path,
            trust_remote_code=True,
        )
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        base_model = AutoModel.from_pretrained(
            self.base_model_name,
            trust_remote_code=True,
            torch_dtype=torch.float32 if self.device == "cpu" else torch.bfloat16,
        )
        if self.adapter_path:
            self.model = PeftModel.from_pretrained(
                base_model,
                str(self.adapter_path),
            )
        else:
            self.model = base_model
        self.model.to(self.device)
        self.model.eval()

    def embed_texts(
        self,
        texts: Sequence[str],
        batch_size: int = 16,
        max_length: int = 384,
    ) -> np.ndarray:
        """Embed a list of text strings with batching and return L2-normalized float32 vectors."""
        all_embeddings: list[np.ndarray] = []
        n_total = len(texts)
        with self._torch.no_grad():
            for i in range(0, n_total, batch_size):
                if i > 0 and (i // batch_size) % 4 == 0:
                    print(f"  Embedded {i}/{n_total} chunks...")
                batch_texts = list(texts[i : i + batch_size])
                # Ensure non-empty strings
                batch_texts = [t.strip() if t.strip() else " " for t in batch_texts]
                encoded = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                input_ids = encoded["input_ids"].to(self.device)
                attention_mask = encoded["attention_mask"].to(self.device)

                model_output = self.model(
                    input_ids=input_ids, attention_mask=attention_mask
                )
                # First element is last_hidden_state
                last_hidden = (
                    model_output[0]
                    if isinstance(model_output, tuple)
                    else model_output.last_hidden_state
                )
                pooled = last_token_pool(last_hidden, attention_mask)
                normalized = self._functional.normalize(pooled, p=2, dim=1)
                all_embeddings.append(normalized.cpu().to(self._torch.float32).numpy())

        if not all_embeddings:
            return np.empty((0, self.vector_size), dtype=np.float32)
        return np.vstack(all_embeddings)

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string into a list of 1024 floats."""
        res = self.embed_texts([query], batch_size=1)
        return res[0].tolist()

    def embed_documents(
        self, texts: Sequence[str], batch_size: int = 16
    ) -> list[list[float]]:
        """Embed multiple documents into a list of 1024-dim vectors."""
        res = self.embed_texts(texts, batch_size=batch_size)
        return [row.tolist() for row in res]
