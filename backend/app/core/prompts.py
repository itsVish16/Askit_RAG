"""Prompt definitions — code is the single source of truth.

Each prompt is (a) used by the graph at runtime and (b) versioned in Opik via
scripts/seed_prompts.py, so wording changes are tracked and diffable over time.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 1. Answer generation
RAG_PROMPT_NAME = "askit-rag-generation"
RAG_SYSTEM_TEXT = (
    "You are a helpful research assistant answering from retrieved context.\n"
    "Rules:\n"
    "1. If the context fully answers the question, answer directly.\n"
    "2. If the context only PARTIALLY answers it, give what the context "
    "supports, then briefly note what is missing.\n"
    "3. Only reply 'I don't have context to answer this question.' if the "
    "context is entirely irrelevant to the question.\n"
    "4. Never invent facts that are not in the context.\n"
    "5. If a conversation history is provided, use it to disambiguate "
    "follow-up questions (e.g. 'it', 'that study', 'the same virus') — "
    "but never let prior history override the retrieved context.\n\n"
    "Context:\n{context}"
)
RAG_HUMAN_TEMPLATE = "{question}"
RAG_PROMPT = ChatPromptTemplate.from_messages(
    [("system", RAG_SYSTEM_TEXT), MessagesPlaceholder("history", optional=True), ("human", RAG_HUMAN_TEMPLATE)]
)

# 2. Search Expansion (feeds both BM25 and Dense Retrieval)
SEARCH_EXPANSION_PROMPT_NAME = "askit-search-expansion"
SEARCH_EXPANSION_SYSTEM_TEXT = (
    "You are a search query expansion assistant for a document retrieval system.\n"
    "Given a user question, your goal is to analyze its complexity and generate search parameters.\n"
    "Rules:\n"
    "1. is_complex: Set to true ONLY if the question is complex, ambiguous, or multifaceted enough to require multiple search queries to find the answer. Set to false for simple, direct queries.\n"
    "2. keywords: Extract 5-8 specific keywords, entities, and synonyms that a document answering the question would likely contain.\n"
    "3. variants: IF is_complex is true, generate exactly 3 alternative versions of the question to maximize retrieval probability. Preserve the exact intent and do not invent names or domains. IF is_complex is false, return an empty array.\n"
)
SEARCH_EXPANSION_HUMAN_TEMPLATE = "{question}"
SEARCH_EXPANSION_PROMPT = ChatPromptTemplate.from_messages(
    [("system", SEARCH_EXPANSION_SYSTEM_TEXT), ("human", SEARCH_EXPANSION_HUMAN_TEMPLATE)]
)

# 4. Route classifier — decides whether to use fast or full path
ROUTE_PROMPT_NAME = "askit-route-classifier"
ROUTE_SYSTEM_TEXT = (
    "You classify user questions for a RAG system. Reply with exactly one word.\n"
    'Respond with "simple" if the question is a direct factual lookup that '
    "a single document can answer.\n"
    'Respond with "hard" if the question requires synthesis across multiple '
    "documents, comparison, multi-step reasoning, or implicit inference.\n"
    'Do not respond with anything else — no punctuation, no explanation.'
)
ROUTE_HUMAN_TEMPLATE = "{question}"
ROUTE_PROMPT = ChatPromptTemplate.from_messages(
    [("system", ROUTE_SYSTEM_TEXT), ("human", ROUTE_HUMAN_TEMPLATE)]
)

# Registry: Opik prompt name -> (system_text, human_template).
# scripts/seed_prompts.py iterates this to create one versioned entry per prompt.
PROMPT_SPECS = [
    (RAG_PROMPT_NAME, RAG_SYSTEM_TEXT, RAG_HUMAN_TEMPLATE),
    (SEARCH_EXPANSION_PROMPT_NAME, SEARCH_EXPANSION_SYSTEM_TEXT, SEARCH_EXPANSION_HUMAN_TEMPLATE),
    (ROUTE_PROMPT_NAME, ROUTE_SYSTEM_TEXT, ROUTE_HUMAN_TEMPLATE),
]
