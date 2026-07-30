# app/evals.py
import pandas as pd
from opik.evaluation import evaluate
from opik.evaluation.metrics import (
    AnswerRelevance,
    ContextPrecision,
    ContextRecall,
    Hallucination,
)

from app.main import app_agent

# 1. Load 50 test questions, each with its ground-truth answer.
# "expected_output" lets Opik score our answer AGAINST the real answer,
# instead of only judging whether the answer sounds plausible.
df = pd.read_parquet("data/ragbench/covidqa/test-00000-of-00001.parquet").head(50)
test_dataset = [
    {"input": row["question"], "expected_output": row["response"]}
    for _, row in df.iterrows()
]


def my_rag_task(dataset_item: dict):
    question = dataset_item["input"]
    print(f"\nEvaluating Question: {question}")

    # Run our LangGraph agent!
    initial_state = {"question": question}
    final_state = app_agent.invoke(initial_state)

    # Return the exact format Opik expects to grade Faithfulness & Hallucination
    return {"output": final_state["answer"], "context": final_state["context"]}


if __name__ == "__main__":
    print("Starting Automated Evals...")
    from opik import Opik
    from opik.evaluation.models import LiteLLMChatModel  # <-- New import

    from app.config import settings  # <-- Import settings

    client = Opik()
    # One dataset per experiment, so runs never contaminate each other:
    # "COVID-QA-hybrid" vs "COVID-QA-dense" — compare them side by side
    # in the Opik dashboard.
    dataset = client.get_or_create_dataset(name="COVID-QA-hybrid")
    dataset.clear()  # drop any stale items from previous runs
    dataset.insert(test_dataset)

    # 1. Create a Custom Judge Model using our Fireworks API Key
    custom_judge = LiteLLMChatModel(
        model_name=f"fireworks_ai/{settings.FIREWORKS_MODEL_NAME}",
        api_key=settings.FIREWORKS_API_KEY,
    )

    # 2. Tell the metrics to use our Custom Judge instead of OpenAI!
    hallucination_metric = Hallucination(model=custom_judge)
    relevance_metric = AnswerRelevance(model=custom_judge)
    # Retrieval quality — the two metrics that consume "expected_output":
    #   ContextRecall: did we retrieve everything the correct answer needs?
    #   ContextPrecision: how much of what we retrieved is actually relevant?
    # These are the headline numbers for the dense-vs-hybrid experiment.
    # (GEval was rejected: it needs top_logprobs=20, Fireworks caps at 5.)
    context_recall = ContextRecall(model=custom_judge)
    context_precision = ContextPrecision(model=custom_judge)

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
