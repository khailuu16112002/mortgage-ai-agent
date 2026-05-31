"""
ONNX Runtime inference pipeline.

Provides:
  - NERInference: named-entity recognition (person, org, location, date, money)
  - ClassifierInference: zero-shot document classification
  - PyTorch fallback when ONNX is unavailable

Usage:
  from pipelines.onnx_inference import get_ner_pipeline, get_classifier_pipeline
  ner = get_ner_pipeline()
  entities = ner.predict("Patrick Durst lives at 463 S Washington St")
"""
from __future__ import annotations
import os
import time
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from config import get_settings, get_logger

logger = get_logger(__name__)


@dataclass
class Entity:
    text: str
    label: str
    score: float
    start: int
    end: int


@dataclass
class ClassificationResult:
    label: str
    score: float
    all_scores: dict[str, float]


# ── ONNX NER Inference ─────────────────────────────────────────────────────────
class ONNXNERInference:
    """
    NER using ONNX Runtime with a HuggingFace token classification model.
    Model: dslim/bert-base-NER (or any ONNX-exported TokenClassification model)
    """

    def __init__(self, model_path: str):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        cfg = get_settings().onnx
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if cfg.use_cuda \
                    else ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(model_path, providers=providers)
        self.tokenizer = AutoTokenizer.from_pretrained(Path(model_path).parent)
        self.id2label: dict[int, str] = {}
        self._load_label_map(Path(model_path).parent)
        logger.info(f"ONNX NER loaded: {model_path}")

    def _load_label_map(self, model_dir: Path) -> None:
        import json
        config_path = model_dir / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text())
            self.id2label = {int(k): v for k, v in cfg.get("id2label", {}).items()}

    def predict(self, text: str, max_length: int = 512) -> list[Entity]:
        import numpy as np

        t0 = time.perf_counter()
        inputs = self.tokenizer(
            text, return_tensors="np", truncation=True,
            max_length=max_length, return_offsets_mapping=True,
        )
        offset_mapping = inputs.pop("offset_mapping")[0]

        ort_inputs = {k: v for k, v in inputs.items()
                      if k in [inp.name for inp in self.session.get_inputs()]}
        outputs = self.session.run(None, ort_inputs)
        logits = outputs[0][0]  # shape: (seq_len, num_labels)

        import numpy as np
        scores = np.exp(logits) / np.exp(logits).sum(axis=-1, keepdims=True)
        pred_ids = scores.argmax(axis=-1)

        entities: list[Entity] = []
        tokens = self.tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])

        current_entity: dict | None = None
        for i, (pred_id, score_vec, token, offsets) in enumerate(
            zip(pred_ids, scores, tokens, offset_mapping)
        ):
            if token in ("[CLS]", "[SEP]", "[PAD]"):
                continue
            label = self.id2label.get(int(pred_id), "O")
            conf = float(score_vec[int(pred_id)])

            if label.startswith("B-"):
                if current_entity:
                    entities.append(Entity(**current_entity))
                current_entity = {
                    "text": text[offsets[0]: offsets[1]],
                    "label": label[2:],
                    "score": conf,
                    "start": int(offsets[0]),
                    "end": int(offsets[1]),
                }
            elif label.startswith("I-") and current_entity:
                current_entity["text"] += text[current_entity["end"]: offsets[1]]
                current_entity["end"] = int(offsets[1])
                current_entity["score"] = (current_entity["score"] + conf) / 2
            else:
                if current_entity:
                    entities.append(Entity(**current_entity))
                    current_entity = None

        if current_entity:
            entities.append(Entity(**current_entity))

        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug(f"ONNX NER inference: {elapsed:.1f}ms, {len(entities)} entities")
        return entities


class ONNXClassifierInference:
    """
    Zero-shot text classification using ONNX Runtime.
    Model: facebook/bart-large-mnli (ONNX exported)
    """

    def __init__(self, model_path: str):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        cfg = get_settings().onnx
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if cfg.use_cuda \
                    else ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(model_path, providers=providers)
        self.tokenizer = AutoTokenizer.from_pretrained(Path(model_path).parent)
        logger.info(f"ONNX Classifier loaded: {model_path}")

    def predict(self, text: str, candidate_labels: list[str]) -> ClassificationResult:
        import numpy as np

        t0 = time.perf_counter()
        scores_dict: dict[str, float] = {}

        for label in candidate_labels:
            hypothesis = f"This document is a {label}."
            inputs = self.tokenizer(
                text, hypothesis, return_tensors="np",
                truncation=True, max_length=512,
            )
            ort_inputs = {k: v for k, v in inputs.items()
                          if k in [inp.name for inp in self.session.get_inputs()]}
            outputs = self.session.run(None, ort_inputs)
            # NLI output: [contradiction, neutral, entailment]
            logits = outputs[0][0]
            probs = np.exp(logits) / np.exp(logits).sum()
            scores_dict[label] = float(probs[2])  # entailment score

        # Normalize
        total = sum(scores_dict.values())
        if total > 0:
            scores_dict = {k: v / total for k, v in scores_dict.items()}

        best = max(scores_dict, key=scores_dict.get)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug(f"ONNX Classifier: {elapsed:.1f}ms, best={best}")
        return ClassificationResult(label=best, score=scores_dict[best], all_scores=scores_dict)


# ── PyTorch Fallback ───────────────────────────────────────────────────────────
class HFNERFallback:
    """PyTorch/HuggingFace NER fallback when ONNX is unavailable."""

    def __init__(self, model_name: str = "dslim/bert-base-NER"):
        from transformers import pipeline
        self._pipe = pipeline("ner", model=model_name, aggregation_strategy="simple")
        logger.info(f"HF NER fallback loaded: {model_name}")

    def predict(self, text: str, **_) -> list[Entity]:
        results = self._pipe(text)
        return [Entity(
            text=r["word"], label=r["entity_group"],
            score=r["score"], start=r["start"], end=r["end"],
        ) for r in results]


class SimpleRegexNER:
    """
    Ultra-lightweight regex NER — zero dependencies.
    Used as last resort when neither ONNX nor HuggingFace is available.
    """
    import re as _re

    PATTERNS = {
        "MONEY": r"\$[\d,]+(?:\.\d{2})?",
        "DATE": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b",
        "ZIP": r"\b\d{5}(?:-\d{4})?\b",
        "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
        "PHONE": r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
        "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    }

    def predict(self, text: str, **_) -> list[Entity]:
        import re
        entities: list[Entity] = []
        for label, pattern in self.PATTERNS.items():
            for m in re.finditer(pattern, text):
                entities.append(Entity(
                    text=m.group(), label=label,
                    score=0.99, start=m.start(), end=m.end(),
                ))
        return sorted(entities, key=lambda e: e.start)


# ── Factory / Singleton ────────────────────────────────────────────────────────
_ner_instance = None
_classifier_instance = None


def get_ner_pipeline():
    """Return best available NER pipeline."""
    global _ner_instance
    if _ner_instance is not None:
        return _ner_instance

    cfg = get_settings().onnx
    if cfg.enabled:
        model_dir = Path(cfg.model_dir)
        ner_path = model_dir / "ner_model.onnx"
        if ner_path.exists():
            try:
                _ner_instance = ONNXNERInference(str(ner_path))
                return _ner_instance
            except Exception as e:
                logger.warning(f"ONNX NER failed to load, trying fallback: {e}")

    # Try HuggingFace
    try:
        _ner_instance = HFNERFallback(cfg.ner_model)
        return _ner_instance
    except Exception as e:
        logger.warning(f"HF NER fallback failed: {e}. Using regex NER.")

    _ner_instance = SimpleRegexNER()
    return _ner_instance


def get_classifier_pipeline():
    """Return best available classifier pipeline."""
    global _classifier_instance
    if _classifier_instance is not None:
        return _classifier_instance

    cfg = get_settings().onnx
    if cfg.enabled:
        model_dir = Path(cfg.model_dir)
        clf_path = model_dir / "classifier_model.onnx"
        if clf_path.exists():
            try:
                _classifier_instance = ONNXClassifierInference(str(clf_path))
                return _classifier_instance
            except Exception as e:
                logger.warning(f"ONNX Classifier load failed: {e}")

    # Return None — callers should handle gracefully
    logger.info("No classifier pipeline available — using LLM only")
    return None


def export_model_to_onnx(model_name: str, output_dir: str, task: str = "ner") -> str:
    """
    Export a HuggingFace model to ONNX format.
    Requires: optimum[onnxruntime], transformers
    Returns path to exported model.
    """
    from optimum.onnxruntime import ORTModelForTokenClassification, ORTModelForSequenceClassification
    from transformers import AutoTokenizer

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    logger.info(f"Exporting {model_name} → ONNX at {output_dir}")
    if task == "ner":
        model = ORTModelForTokenClassification.from_pretrained(model_name, export=True)
        out_path = out / "ner_model.onnx"
    else:
        model = ORTModelForSequenceClassification.from_pretrained(model_name, export=True)
        out_path = out / "classifier_model.onnx"

    model.save_pretrained(str(out))
    AutoTokenizer.from_pretrained(model_name).save_pretrained(str(out))
    logger.info(f"Model exported to {out}")
    return str(out)
