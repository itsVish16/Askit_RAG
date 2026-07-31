# app/evals.py
import pandas as pd
from opik.evaluation import evaluate
from opik.evaluation.metrics import (
    AnswerRelevance,
    ContextPrecision,
    ContextRecall,
    Hallucination,
)

from app.config import settings
from app.main import app_agent

# Load the test split — each item carries its ground-truth answer.
# "expected_output" lets Opik score our answer AGAINST the real answer,
# instead of only judging whether the answer sounds plausible.
df = pd.read_parquet(settings.EVAL_PARQUET_PATH).head(settings.EVAL_SAMPLE_SIZE)
test_dataset = [
    {"input": row["question"], "expected_output": row["response"]}
    for _, row in df.iterrows()
]


def my_rag_task(dataset_item: dict):
    question = dataset_item["input"]
    print(f"\nEvaluating Question: {question}")

    final_state = app_agent.invoke({"question": question})

    # The exact format Opik expects to grade the metrics below.
    return {"output": final_state["answer"], "context": final_state["context"]}


if __name__ == "__main__":
    print("Starting Automated Evals...")
    from opik import Opik
    from opik.evaluation.models import LiteLLMChatModel

    client = Opik()
    # One dataset per experiment, so runs never contaminate each other.
    dataset = client.get_or_create_dataset(name=settings.EVAL_DATASET_NAME)
    dataset.clear()  # drop any stale items from previous runs
    dataset.insert(test_dataset)

    # Judge: our Fireworks model, not OpenAI.
    custom_judge = LiteLLMChatModel(
        model_name=f"fireworks_ai/{settings.FIREWORKS_MODEL_NAME}",
        api_key=settings.FIREWORKS_API_KEY,
    )

    # (GEval was rejected: it needs top_logprobs=20, Fireworks caps at 5.)
    hallucination_metric = Hallucination(model=custom_judge)
    relevance_metric = AnswerRelevance(model=custom_judge)
    context_recall = ContextRecall(model=custom_judge)
    context_precision = ContextPrecision(model=custom_judge)

    # WARMUP: materialize heavy resources in THIS (main) process BEFORE
    # evaluate() forks parallel workers. Children inherit the parent's
    # memory via fork(), so the BM25 index + reranker load ONCE here
    # instead of once per worker (~4GB total vs ~12GB, no OOM).
    from app.db.retrievers import get_bm25_retriever, rerank_texts

    print("Warming up BM25 index + reranker in main process...")
    get_bm25_retriever(k=settings.K_RETRIEVE)  # BM25 corpus index into RAM
    rerank_texts("warmup query", ["warmup document"], k_final=1)  # loads reranker
    print("Warmup done.")

    evaluate(
        dataset=dataset,
        task=my_rag_task,
        scoring_metrics=[
            hallucination_metric,
            relevance_metric,
            context_recall,
            context_precision,
        ],
    )
    print("Evals complete! Check your Opik Dashboard.")
