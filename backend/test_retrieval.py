import asyncio
from app.agent.tools import retrieve_docs_async

async def main():
    # Provide a dummy user_id or None to see if it searches.
    # We will use "test_user" or we can fetch a user from DB.
    # Wait, retrieve_docs_async uses user_id.
    res = await retrieve_docs_async("what is RAG", "some_user_id")
    print(res)

asyncio.run(main())
