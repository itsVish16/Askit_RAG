"""LLM-as-a-Judge evaluation harness (Opik).

Scores the agent against the COVID-QA test split on Hallucination,
AnswerRelevance, ContextRecall, ContextPrecision. The judge is our Fireworks
model (not OpenAI). GEval was rejected: it needs top_logprobs=20, Fireworks
caps at 5.
"""
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

# Each item carries its ground-truth answer so Opik scores against the real
# answer, not just plausibility.
df = pd.read_parquet(settings.EVAL_PARQUET_PATH).head(settings.EVAL_SAMPLE_SIZE)
test_dataset = [
    {"input": row["question"], "expected_output": row["response"]}
    for _, row in df.iterrows()
]


def my_rag_task(dataset_item: dict):
    question = dataset_item["input"]
    logger.info(f"\nEvaluating Question: {question}")
    final_state = app_agent.invoke({"question": question})
    return {"output": final_state["answer"], "context": final_state["context"]}


def run_eval_pipeline_if_needed() -> None:
    from app.evaluation.results import latest_eval_results

    if latest_eval_results() is not None:
        logger.info("[evals] Eval results already cached in database. Skipping automated evals.")
        return

    logger.info("Starting Automated Evals...")
    from opik import Opik
    from opik.evaluation.models import LiteLLMChatModel

    client = Opik()
    dataset = client.get_or_create_dataset(name=settings.EVAL_DATASET_NAME)
    dataset.clear()  # one dataset per experiment — runs never contaminate each other
    dataset.insert(test_dataset)

    custom_judge = LiteLLMChatModel(
        model_name=f"fireworks_ai/{settings.FIREWORKS_MODEL_NAME}",
        api_key=settings.FIREWORKS_API_KEY,
    )

    hallucination_metric = Hallucination(model=custom_judge)
    relevance_metric = AnswerRelevance(model=custom_judge)
    context_recall = ContextRecall(model=custom_judge)
    context_precision = ContextPrecision(model=custom_judge)

    # Warmup: materialize heavy resources in THIS (main) process BEFORE
    # evaluate() forks parallel workers. Children inherit via fork(), so BM25
    # + reranker load ONCE here instead of once per worker (~4GB vs ~12GB).
    import asyncio

    logger.info("Warming up BM25 index + reranker in main process...")
    # Using a new event loop for synchronous execution in the background thread
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(get_bm25_retriever(k=settings.K_RETRIEVE))
        else:
            loop.run_until_complete(get_bm25_retriever(k=settings.K_RETRIEVE))
    except RuntimeError:
        asyncio.run(get_bm25_retriever(k=settings.K_RETRIEVE))

    try:
        get_reranker()
    except Exception as exc:
        logger.error(f"Warmup failed: {exc}")
    logger.info("Warmup done.")

    experiment = evaluate(
        dataset=dataset,
        task=my_rag_task,
        scoring_metrics=[hallucination_metric, relevance_metric, context_recall, context_precision],
    )

    # Persist the per-metric averages so the frontend can display cached
    # results without re-running the (paid) eval. Opik's evaluate() returns an
    # experiment whose summary exposes metric averages.
    metrics: dict[str, float] = {}
    try:
        summary = experiment.summary()
        # summary() returns a dataframe-like object with a 'average_score' per metric.
        for row in summary:
            name = row.get("name") or row.get("metric") or row.get("metric_name")
            score = row.get("average_score")
            if name is not None and score is not None:
                metrics[str(name)] = float(score)
    except Exception as exc:
        logger.warning(f"[evals] could not extract metric summary: {exc}")

    if metrics:
        from app.evaluation.results import save_eval_results

        save_eval_results(metrics)
        logger.info(f"  [evals] cached metrics: {metrics}")
    logger.info("Evals complete! Check your Opik Dashboard.")

if __name__ == "__main__":
    run_eval_pipeline_if_needed()
