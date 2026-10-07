## Using the UoW in use cases

Use cases receive the factory, not an instance. I'm assuming repo methods like add, get and list_by_book, so adapt them to your ports.

```python
@dataclass(frozen=True)
class ImportBookCommand:
    title: str
    author: str
    chapters: list[tuple[str, str]]  # (title, text)


class ImportBookUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, cmd: ImportBookCommand) -> BookId:
        book = Book.create(title=cmd.title, author=cmd.author)
        chapters = [
            Chapter.create(book_id=book.id, title=t, text=x) for t, x in cmd.chapters
        ]
        job = IndexingJob.create(book_id=book.id)

        async with self._uow_factory() as uow:
            await uow.books.add(book)
            for chapter in chapters:
                await uow.chapters.add(chapter)
            await uow.jobs.add(job)
            await uow.commit()  # atomic: book + chapters + job, or nothing

        return book.id
```

## For the slow background job, use short UoWs and keep the heavy work outside them:

```python
class IndexBookUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory, embedder: Embedder) -> None:
        self._uow_factory = uow_factory
        self._embedder = embedder

    async def execute(self, job_id: JobId) -> None:
        # 1. short read
        async with self._uow_factory() as uow:
            job = await uow.jobs.get(job_id)
            chapters = await uow.chapters.list_by_book(job.book_id)
            job.mark_running()
            await uow.commit()

        # 2. slow work, no transaction open
        chunks = [c for ch in chapters for c in chunk_chapter(ch)]
        vectors = await self._embedder.embed([c.text for c in chunks])

        # 3. short write
        async with self._uow_factory() as uow:
            for chunk, vec in zip(chunks, vectors, strict=True):
                await uow.chunks.add(chunk.with_embedding(vec))
            job = await uow.jobs.get(job_id)
            job.mark_done()
            await uow.commit()
```

Read-only use cases still use async with but skip commit(); the session is closed and rolled back on exit.
