"""The normalized corpus record (Phase 6 step 3; docs/DATASETS.md "Per-record requirements").

Every record carries: ``source_dataset``, ``source_id``, ``license`` (that record's source
licence, which must be the one docs/DATASETS.md states for the source), ``sha256`` of its
text, the dataset ``revision`` pin and the ``fetch_sha256`` of the file it came from. The
``text`` is the upstream payload text VERBATIM; ``sha256`` is computed from it as ingested
and re-checked by the validator, so a text altered after hashing cannot exist as a record.

``attack_family`` is each SOURCE'S OWN taxonomy and carries THREE different kinds of thing:
* BIPIA: the category, an obfuscation or content TECHNIQUE ("Anagramming", "Base Encoding",
  "Clickbait");
* InjecAgent: the "Attack Type", a HARM class ("Financial Harm", "Physical Data");
* AgentDojo: the suite, an application DOMAIN ("banking", "workspace").
It is NOT a comparable axis across sources: never stratify, group or report across sources
by it (a BIPIA technique, an InjecAgent harm class and an AgentDojo domain are not the same
kind of thing). Within one source it is that source's taxonomy; across sources, use
``source_dataset`` (docs/METHODOLOGY.md threat 13).
"""

from __future__ import annotations

import hashlib

from pydantic import Field, model_validator

from proveflow.core._base import FrozenModel
from proveflow.core.attacks import Payload
from proveflow.corpus.sources import TABLE_LICENSES

# No source states a language and proveflow detects none (no dependency for it), so every
# record is "und" (BCP 47: undetermined). Reported as such; never guessed.
UNDETERMINED = "und"


class LicenseRefused(ValueError):
    """A record with no licence, or a licence that is not its source's in docs/DATASETS.md."""


class CorpusRecord(FrozenModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_dataset: str
    source_id: str = Field(min_length=1)
    license: str
    attack_family: str = Field(min_length=1)
    language: str = UNDETERMINED
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    fetch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _checked(self) -> CorpusRecord:
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("the record's sha256 is not the sha256 of its text")
        self._check_license()
        return self

    def _check_license(self) -> None:
        want = TABLE_LICENSES.get(self.source_dataset)
        if not self.license or want is None or self.license != want:
            raise LicenseRefused(
                f"{self.source_dataset}:{self.source_id}: licence {self.license!r} is not the "
                f"source's licence in docs/DATASETS.md ({want!r})"
            )

    def payload(self) -> Payload:
        """The core ``Payload`` an Attack is instantiated from (corpus.instantiate)."""
        return Payload(id=self.id, text=self.text, source_dataset=self.source_dataset,
                       source_id=self.source_id, license=self.license,
                       attack_family=self.attack_family, language=self.language,
                       sha256=self.sha256)  # fmt: skip


def make_record(*, source: str, source_id: str, text: str, attack_family: str, license: str,
                revision: str, fetch_sha256: str) -> CorpusRecord:  # fmt: skip
    """The ONE constructor loaders use: the text as given (verbatim), hashed here."""
    return CorpusRecord(
        id=f"{source}:{source_id}", text=text, source_dataset=source, source_id=source_id,
        license=license, attack_family=attack_family,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), revision=revision,
        fetch_sha256=fetch_sha256,
    )  # fmt: skip
