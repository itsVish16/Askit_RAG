"""Prompt definitions — code is the single source of truth.

Each prompt here is (a) used directly by the graph at runtime and
(b) versioned in Opik as a named prompt history via scripts/seed_prompts.py,
so every iteration is tracked and you can diff wording changes over time
without redeploying code. The PROMPT_SPECS registry keeps the Opik name
paired with each template in one place.
"""

from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# 1. Answer generation
# ---------------------------------------------------------------------------
RAG_PROMPT_NAME = "askit-rag-generation"
RAG_SYSTEM_TEXT = (
    "You are a helpful research assistant answering from retrieved context.\n"
    "Rules:\n"
    "1. If the context fully answers the question, answer directly.\n"
    "2. If the context only PARTIALLY answers it, give what the context "
    "supports, then briefly note what is missing.\n"
    "3. Only reply 'I don't have context to answer this question.' if the "
    "context is entirely irrelevant to the question.\n"
    "4. Never invent facts that are not in the context.\n\n"
    "Context:\n{context}"
)
RAG_HUMAN_TEMPLATE = "{question}"
RAG_PROMPT = ChatPromptTemplate.from_messages(
    [("system", RAG_SYSTEM_TEXT), ("human", RAG_HUMAN_TEMPLATE)]
)

# ---------------------------------------------------------------------------
# 2. Keyword extraction (feeds BM25)
# ---------------------------------------------------------------------------
KEYWORD_PROMPT_NAME = "askit-keyword-extraction"
KEYWORD_SYSTEM_TEXT = (
    "You are a keyword extraction assistant helping a lexical search "
    "engine (BM25) find biomedical research documents.\n"
    "Given a user question, extract 5-8 specific keywords, entities, "
    "and scientific synonyms a paper would likely contain.\n"
    "Rules:\n"
    "- Capture entities, diseases, genes, viruses, methods, and key terms.\n"
    "- Include synonyms/variants (e.g. 'COVID-19' AND 'SARS-CoV-2').\n"
    "- Prefer formal scientific terminology over everyday language.\n"
    "- One keyword/phrase per line. No bullets, numbering, or explanations."
)
KEYWORD_HUMAN_TEMPLATE = "{question}"
KEYWORD_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [("system", KEYWORD_SYSTEM_TEXT), ("human", KEYWORD_HUMAN_TEMPLATE)]
)

# ---------------------------------------------------------------------------
# 3. Multi-query expansion (feeds dense retrieval)
# ---------------------------------------------------------------------------
MULTI_QUERY_PROMPT_NAME = "askit-multi-query"
MULTI_QUERY_SYSTEM_TEXT = (
    "You are a search query expansion assistant for a biomedical research "
    "retrieval system. Given a user question, generate {n} alternative "
    "versions of that question to retrieve relevant scientific documents.\n"
    "Rules:\n"
    "- Preserve the question's INTENT exactly; vary wording and angle only.\n"
    "- Use domain terms and synonyms a scientific paper would use "
    "  (e.g. 'COVID-19' -> 'SARS-CoV-2', 'coronavirus').\n"
    "- One question per line. No numbering, bullets, or explanations."
)
MULTI_QUERY_HUMAN_TEMPLATE = "{question}"
MULTI_QUERY_PROMPT = ChatPromptTemplate.from_messages(
    [("system", MULTI_QUERY_SYSTEM_TEXT), ("human", MULTI_QUERY_HUMAN_TEMPLATE)]
)

# Registry: Opik prompt name -> (system_text, human_template).
# scripts/seed_prompts.py iterates this to create one versioned entry per
# prompt in the Opik UI (each run adds a new commit to that prompt's history).
PROMPT_SPECS = [
    (RAG_PROMPT_NAME, RAG_SYSTEM_TEXT, RAG_HUMAN_TEMPLATE),
    (KEYWORD_PROMPT_NAME, KEYWORD_SYSTEM_TEXT, KEYWORD_HUMAN_TEMPLATE),
    (MULTI_QUERY_PROMPT_NAME, MULTI_QUERY_SYSTEM_TEXT, MULTI_QUERY_HUMAN_TEMPLATE),
]
