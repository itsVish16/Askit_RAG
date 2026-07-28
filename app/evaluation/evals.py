# app/evals.py
import pandas as pd
import opik
from opik.evaluation import evaluate
from opik.evaluation.metrics import Hallucination, AnswerRelevance
from app.main import app_agent 

# 1. Load the first 5 questions from the Parquet dataset
df = pd.read_parquet("data/ragbench/covidqa/validation-00000-of-00001.parquet").head(5)
test_dataset = [{"input": row["question"]} for _, row in df.iterrows()]

def my_rag_task(dataset_item: dict):
    question = dataset_item["input"]
    print(f"\nEvaluating Question: {question}")
    
    # Run our LangGraph agent!
    initial_state = {"question": question}
    final_state = app_agent.invoke(initial_state)
    
    # Return the exact format Opik expects to grade Faithfulness & Hallucination
    return {
        "output": final_state["answer"],
        "context": final_state["context"] 
    }

if __name__ == "__main__":
    print("Starting Automated Evals...")
    from opik import Opik
    from opik.evaluation.models import LiteLLMChatModel  # <-- New import
    from app.config import settings                      # <-- Import settings
    
    client = Opik()
    dataset = client.get_or_create_dataset(name="COVID-QA-Subset")
    dataset.insert(test_dataset)
    
    # 1. Create a Custom Judge Model using our Fireworks API Key
    custom_judge = LiteLLMChatModel(
        model_name=f"fireworks_ai/{settings.FIREWORKS_MODEL_NAME}",
        api_key=settings.FIREWORKS_API_KEY
    )
    
    # 2. Tell the metrics to use our Custom Judge instead of OpenAI!
    hallucination_metric = Hallucination(model=custom_judge)
    relevance_metric = AnswerRelevance(model=custom_judge)
    
    evaluate(
        dataset=dataset,
        task=my_rag_task,
        scoring_metrics=[hallucination_metric, relevance_metric]
    )
    print("Evals complete! Check your Opik Dashboard.")

