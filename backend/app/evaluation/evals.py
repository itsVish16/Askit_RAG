"""Opik LLM-as-a-Judge evaluation harness for COVID-QA."""

import asyncio
import os
import uuid

import pandas as pd
from opik.evaluation import evaluate
from opik.evaluation.metrics import (
    AnswerRelevance,
    ContextPrecision,
    ContextRecall,
    Hallucination,
)

from app.agent.graph import agent as app_agent
from app.config import settings
from app.core.logger import get_logger
from app.db.retrievers import get_bm25_retriever, get_reranker

logger = get_logger(__name__)


def _load_test_dataset() -> list[dict]:
    if not os.path.exists(settings.EVAL_PARQUET_PATH):
        raise FileNotFoundError(f"Eval parquet not found: {settings.EVAL_PARQUET_PATH}")
    df = pd.read_parquet(settings.EVAL_PARQUET_PATH).head(settings.EVAL_SAMPLE_SIZE)
    return [
        {"input": row["question"], "expected_output": row["response"]}
        for _, row in df.iterrows()
    ]


def my_rag_task(dataset_item: dict) -> dict:
    question = dataset_item["input"]
    logger.info(f"[evals] Evaluating: {question}")
    thread_id = str(uuid.uuid4())
    final_state = asyncio.run(
        app_agent.ainvoke(
            {"question": question, "corpus_scope": "shared"},
            config={"configurable": {"thread_id": thread_id}},
        )
    )
    return {
        "output": final_state.get("answer", ""),
        "context": final_state.get("context", []),
    }


def run_eval_pipeline_if_needed() -> None:
    from app.evaluation.results import latest_eval_results, save_eval_results

    if latest_eval_results() is not None:
        logger.info("[evals] Eval results already cached. Skipping.")
        return

    if not os.path.exists(settings.EVAL_PARQUET_PATH):
        logger.warning(f"[evals] Skipping automated evals — parquet not found at {settings.EVAL_PARQUET_PATH}.")
        return

    test_dataset = _load_test_dataset()
    logger.info(f"[evals] Starting evaluation on {len(test_dataset)} questions...")

    from opik import Opik
    from opik.evaluation.models import LiteLLMChatModel

    client = Opik()
    dataset = client.get_or_create_dataset(name=settings.EVAL_DATASET_NAME)
    dataset.clear()
    dataset.insert(test_dataset)

    judge_model_name = settings.EVAL_JUDGE_MODEL or f"fireworks_ai/{settings.FIREWORKS_MODEL_NAME}"
    custom_judge = LiteLLMChatModel(
        model_name=judge_model_name,
        api_key=settings.FIREWORKS_API_KEY,
    )

    metrics_list = [
        Hallucination(model=custom_judge),
        AnswerRelevance(model=custom_judge),
        ContextRecall(model=custom_judge),
        ContextPrecision(model=custom_judge),
    ]

    try:
        asyncio.run(get_bm25_retriever(k=settings.K_RETRIEVE))
        get_reranker()
    except Exception as exc:
        logger.warning(f"[evals] Warmup warning: {exc}")

    experiment = evaluate(
        dataset=dataset,
        task=my_rag_task,
        scoring_metrics=metrics_list,
    )

    metrics: dict[str, float] = {}
    try:
        summary = experiment.summary()
        for row in summary:
            name = row.get("name") or row.get("metric") or row.get("metric_name")
            score = row.get("average_score")
            if name is not None and score is not None:
                metrics[str(name)] = float(score)
    except Exception as exc:
        logger.warning(f"[evals] Could not extract metric summary: {exc}")

    if metrics:
        save_eval_results(metrics)
        logger.info(f"[evals] Cached metrics: {metrics}")


if __name__ == "__main__":
    run_eval_pipeline_if_needed()
