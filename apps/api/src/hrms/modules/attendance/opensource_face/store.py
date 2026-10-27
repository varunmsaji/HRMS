"""Persistence of OPENSOURCE-engine embeddings (`face_embedding`, migration 20261022090000).

Embeddings are biometric templates: they are stored only as AES-256-GCM ciphertext under the
environment data key (`PiiCryptoService`, AAD bound to table / column / row id, so a ciphertext
copied to another row or column fails to decrypt), only ever read by `engine.py` for a 1:1
comparison, and never reach an API schema, a log line or an audit row. Row-level security scopes
every statement to the company; `person_ref` + `employee_id` make ownership explicit."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings
from hrms.core.crypto.service import PiiCryptoService
from hrms.core.db.session import session_scope
from hrms.modules.attendance.models import FaceEmbedding
from hrms.modules.attendance.opensource_face.similarity import normalise

_TABLE = "face_embedding"
_COLUMN = "embedding_enc"


def _aad_record_id(
    *,
    row_id: UUID,
    company_id: UUID,
    employee_id: UUID,
    person_ref: UUID,
    sample_index: int,
    model_version: str,
) -> UUID:
    """The `record_id` fed to the PII crypto service's AAD (`table:column:record_id`). The shared
    DEK is per environment, not per tenant, and the AAD would otherwise bind only the row id - so
    anyone able to UPDATE the ownership columns could re-point a stored template at another
    employee and it would still decrypt. Folding every ownership / interpretation column into this
    id makes such an edit fail GCM authentication (fail closed) instead."""
    parts = (row_id, company_id, employee_id, person_ref, sample_index, model_version)
    name = "face_embedding|" + "|".join(str(p) for p in parts)
    return uuid5(NAMESPACE_URL, name)


class SampleLimitError(Exception):
    """The person already holds the maximum number of enrollment captures."""


class PersonNotFoundError(Exception):
    """No stored embeddings for this person in this company."""


@dataclass(frozen=True)
class StoredEmbedding:
    employee_id: UUID
    model_version: str
    embedding: tuple[float, ...]


class EmbeddingStore(Protocol):
    async def create_person(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
    ) -> None: ...

    async def add_sample(
        self,
        *,
        company_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
        max_samples: int,
    ) -> None: ...

    async def load(self, *, company_id: UUID, person_ref: UUID) -> list[StoredEmbedding]: ...

    async def delete_person(self, *, company_id: UUID, person_ref: UUID) -> None: ...


class DbEmbeddingStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._crypto = PiiCryptoService(settings)

    async def _insert(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        person_ref: UUID,
        sample_index: int,
        model_version: str,
        embedding: Sequence[float],
    ) -> None:
        row_id = uuid4()
        encrypted = await self._crypto.encrypt_column(
            session,
            plaintext=json.dumps([round(float(v), 7) for v in embedding]),
            table=_TABLE,
            column=_COLUMN,
            record_id=_aad_record_id(
                row_id=row_id,
                company_id=company_id,
                employee_id=employee_id,
                person_ref=person_ref,
                sample_index=sample_index,
                model_version=model_version,
            ),
        )
        assert encrypted is not None
        session.add(
            FaceEmbedding(
                id=row_id,
                company_id=company_id,
                employee_id=employee_id,
                person_ref=person_ref,
                sample_index=sample_index,
                model_version=model_version,
                embedding_enc=encrypted,
            )
        )
        await session.flush()

    async def create_person(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
    ) -> None:
        async with session_scope(self._settings, company_id=str(company_id)) as session:
            await self._insert(
                session,
                company_id=company_id,
                employee_id=employee_id,
                person_ref=person_ref,
                sample_index=0,
                model_version=model_version,
                embedding=embedding,
            )

    async def add_sample(
        self,
        *,
        company_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
        max_samples: int,
    ) -> None:
        async with session_scope(self._settings, company_id=str(company_id)) as session:
            rows = (
                await session.execute(
                    select(FaceEmbedding.employee_id, func.max(FaceEmbedding.sample_index))
                    .where(
                        FaceEmbedding.company_id == company_id,
                        FaceEmbedding.person_ref == person_ref,
                    )
                    .group_by(FaceEmbedding.employee_id)
                )
            ).all()
            if not rows:
                raise PersonNotFoundError()
            employee_id, top = rows[0]
            if int(top) + 1 >= max_samples:
                raise SampleLimitError()
            await self._insert(
                session,
                company_id=company_id,
                employee_id=employee_id,
                person_ref=person_ref,
                sample_index=int(top) + 1,
                model_version=model_version,
                embedding=embedding,
            )

    async def load(self, *, company_id: UUID, person_ref: UUID) -> list[StoredEmbedding]:
        async with session_scope(self._settings, company_id=str(company_id)) as session:
            rows = (
                (
                    await session.execute(
                        select(FaceEmbedding)
                        .where(
                            FaceEmbedding.company_id == company_id,
                            FaceEmbedding.person_ref == person_ref,
                        )
                        .order_by(FaceEmbedding.sample_index)
                    )
                )
                .scalars()
                .all()
            )
            out: list[StoredEmbedding] = []
            for row in rows:
                plain = await self._crypto.decrypt_column(
                    session,
                    ciphertext=row.embedding_enc,
                    table=_TABLE,
                    column=_COLUMN,
                    record_id=_aad_record_id(
                        row_id=row.id,
                        company_id=row.company_id,
                        employee_id=row.employee_id,
                        person_ref=row.person_ref,
                        sample_index=row.sample_index,
                        model_version=row.model_version,
                    ),
                )
                assert plain is not None
                out.append(
                    StoredEmbedding(
                        row.employee_id, row.model_version, normalise(json.loads(plain))
                    )
                )
            return out

    async def delete_person(self, *, company_id: UUID, person_ref: UUID) -> None:
        async with session_scope(self._settings, company_id=str(company_id)) as session:
            await session.execute(
                delete(FaceEmbedding).where(
                    FaceEmbedding.company_id == company_id,
                    FaceEmbedding.person_ref == person_ref,
                )
            )


class InMemoryEmbeddingStore:
    """Test double with the same semantics (no encryption; tests must not assume otherwise)."""

    def __init__(self) -> None:
        self.rows: list[tuple[UUID, UUID, UUID, int, str, tuple[float, ...]]] = []

    async def create_person(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
    ) -> None:
        self.rows.append((company_id, employee_id, person_ref, 0, model_version, tuple(embedding)))

    async def add_sample(
        self,
        *,
        company_id: UUID,
        person_ref: UUID,
        model_version: str,
        embedding: Sequence[float],
        max_samples: int,
    ) -> None:
        mine = [r for r in self.rows if r[0] == company_id and r[2] == person_ref]
        if not mine:
            raise PersonNotFoundError()
        if len(mine) >= max_samples:
            raise SampleLimitError()
        self.rows.append(
            (company_id, mine[0][1], person_ref, len(mine), model_version, tuple(embedding))
        )

    async def load(self, *, company_id: UUID, person_ref: UUID) -> list[StoredEmbedding]:
        return [
            StoredEmbedding(r[1], r[4], r[5])
            for r in self.rows
            if r[0] == company_id and r[2] == person_ref
        ]

    async def delete_person(self, *, company_id: UUID, person_ref: UUID) -> None:
        self.rows = [r for r in self.rows if not (r[0] == company_id and r[2] == person_ref)]
