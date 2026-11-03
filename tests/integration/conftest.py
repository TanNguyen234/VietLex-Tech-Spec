import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def close_live_clients():
    # Each live test has its own event loop; close pooled clients on that loop.
    from app.services.clients import close_clients

    try:
        yield
    finally:
        await close_clients()
