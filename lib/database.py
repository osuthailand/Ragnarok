import aiomysql
import settings

from typing import Any, AsyncIterable, Optional


class Database:
    def __init__(self):
        self.pool = None

    async def connect(self) -> None:
        self.pool = await aiomysql.create_pool(
            host=settings.DB_HOST,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            db=settings.DB_DATABASE,
            autocommit=True,
        )  # type: ignore

    async def disconnect(self) -> None:
        self.pool.close()
        await self.pool.wait_closed()

    async def _fetch(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] | Any = None,
        _dict: bool = False,
    ):
        if _dict:
            cursor = aiomysql.DictCursor
        else:
            cursor = aiomysql.Cursor

        async with self.pool.acquire() as conn:
            async with conn.cursor(cursor) as cur:
                await cur.execute(query, params)

                return conn, cur

    async def execute(
        self, query: str, params: Optional[tuple[Any, ...]] | Any = None
    ) -> int:
        conn, cur = await self._fetch(query, params)

        await conn.commit()
        return cur.lastrowid

    async def fetchall(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] | Any = None,
        _dict: bool = False,
    ) -> dict[str, Any]:
        _, cur = await self._fetch(query, params, _dict)

        return await cur.fetchall()

    async def fetch(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] | Any = None,
        _dict: bool = True,
    ) -> dict[str, Any]:
        _, cur = await self._fetch(query, params, _dict)

        return await cur.fetchone()

    async def iterall(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] | Any = None,
        _dict: bool = True,
    ) -> AsyncIterable[dict[str, Any]]:
        _, cur = await self._fetch(query, params, _dict)

        async for row in cur:
            yield row
