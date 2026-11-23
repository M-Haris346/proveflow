"""THE pinned corpus sources (Phase 6 step 3). docs/DATASETS.md (Haris's review, 2026-11-23) is
the AUTHORITY: this module encodes its decisions and pins, it does not re-decide them.

Each source is fetched at ONE pinned revision; every file it may fetch is listed with the
sha256 its bytes must have (computed at pin time, 2026-11-23, from the pinned commit). The
licence file is fetched and checksummed too. A file that is not listed is never fetched.

LLMail-Inject is NOT here, on purpose: its dataset card body was read on 2026-11-23 and
reported, and Haris has not yet ruled on it (docs/DATASETS.md: blocking for that dataset).

BIPIA is the ATTACK FILES ONLY: the four ``benchmark/*_attack_*.json`` files, BIPIA's own
text under the repository's MIT. Every context directory is REFUSED BY NAME
(``BIPIA_REFUSED_CONTEXTS``): those hold the carved-out datasets, two of them CC BY-SA 4.0
(share-alike), the single place a share-alike licence could enter this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The licence of every record of each source, as docs/DATASETS.md states it. A record whose
# licence is absent or not this one fails ingest (records.CorpusRecord).
TABLE_LICENSES: dict[str, str] = {"injecagent": "MIT", "bipia": "MIT", "agentdojo": "MIT"}

# Upstream order of docs/DATASETS.md's table; the DEDUP winner is the earlier source
# (dedup.py). LLMail-Inject keeps its place although it is not ingested.
SOURCE_PRIORITY: tuple[str, ...] = ("llmail_inject", "injecagent", "bipia", "agentdojo")

BIPIA_REFUSED_CONTEXTS: tuple[str, ...] = ("email", "table", "code", "qa", "abstract")

# AgentDojo: EVERY default suite's injection_tasks.py (11 files; a scan of all 99 Python files
# under src/agentdojo at the pin found registrations in these and nowhere else, 2026-11-23),
# plus upstream's benchmark-version table. Injection tasks are resolved to ONE benchmark
# version by AgentDojo's own rule (loaders.load_agentdojo). examples/ is not the benchmark and
# is not fetched.
AGENTDOJO_TABLE = "src/agentdojo/task_suite/load_suites.py"


@dataclass(frozen=True)
class Source:
    name: str
    repo: str  # owner/name on GitHub
    revision: str  # the pinned commit
    licence_file: str  # fetched by this EXACT name and checksummed
    files: dict[str, str] = field(default_factory=dict)  # path -> sha256 of its bytes

    def raw_url(self, path: str) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.revision}/{path}"


INJECAGENT = Source(
    name="injecagent",
    repo="uiuc-kang-lab/InjecAgent",
    revision="f19c9f2c79a41046eb13c03c51a24c567a8ffa07",  # main, 2024-07-02
    licence_file="LICENCE",  # British spelling: fetched by that exact name
    files={
        "LICENCE": "b48589499dbb84caa796b00b4ea652b0443e49660282c44d890fd473b8c0674e",
        "data/attacker_cases_dh.jsonl": "999d52e15af3c80a3303a09430af0f3878d1f91e4c573ca7b477a91cdfa6b991",  # noqa: E501 (a pinned sha256 is not wrapped)
        "data/attacker_cases_ds.jsonl": "87952398c989d8ca841724e38ecdbb789676d3841e19dfc44aac7b710df9cb1f",  # noqa: E501 (a pinned sha256 is not wrapped)
    },
)

BIPIA = Source(
    name="bipia",
    repo="microsoft/BIPIA",
    revision="a004b69ec0dd446e0afd461d98cb5e96e120a5d0",  # archived 2026-09-16; last push
    licence_file="LICENSE",
    files={
        "LICENSE": "57cf81c45e0929899bc18051cf90134f00e55963ddecc7b37cfc5ea1494b1e8b",
        "benchmark/text_attack_train.json": "63f95d3e67eac4178cdabdbdaf192cd05f2b6ed0702b578f1d30d556e5155670",  # noqa: E501 (a pinned sha256 is not wrapped)
        "benchmark/text_attack_test.json": "75750e7b4e8b34e8f9d88d89b357aeaaf02bd07f9e493ccd37eda74a0cd7c7f8",  # noqa: E501 (a pinned sha256 is not wrapped)
        "benchmark/code_attack_train.json": "fe515080b6da2b5c0b67ca7ba2a3b3c2ce57c48f45733c475ebc813cba118484",  # noqa: E501 (a pinned sha256 is not wrapped)
        "benchmark/code_attack_test.json": "892545c5aaec0645b1ded65dc7816b3d70e9ef4eadcba2301a7a3db93676b6e0",  # noqa: E501 (a pinned sha256 is not wrapped)
    },
)

AGENTDOJO = Source(
    name="agentdojo",
    repo="ethz-spylab/agentdojo",
    revision="089ed468cf3ed0322acc66b0211f26d9d90dbf60",  # main, 2026-06-02
    licence_file="LICENSE",
    files={
        "LICENSE": "4285a071f2d382338e52b4fb0a186d952984a34d43a33d8872e1a1d8cb43401e",
        "src/agentdojo/default_suites/v1/banking/injection_tasks.py": "fa2dedf8e66c95ffadb54f5a26648728b08c56f302858de4ee9a5cc0b3891618",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1/slack/injection_tasks.py": "d5775da1689e13192b665837e72cee88ed76f622e9b998e9def18b700fdc5afc",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1/travel/injection_tasks.py": "9252be834b0ae0e28fe06744e052987d71d8ad3666b8d0b1f65f2875f998fca8",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1/workspace/injection_tasks.py": "03e0894ffb544a79fd0bfd2c62cc5f90b19a2b1d429068d800239bfd020b6dcc",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_1_1/travel/injection_tasks.py": "23f325aa0821c7982991657588ee0b58057423559e97d6ebd6febc8274b5ac1b",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_1_2/travel/injection_tasks.py": "d8688a8896736e4807b649340b84af65eb7b36f34d082073690333445a410b39",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_1_2/workspace/injection_tasks.py": "3ffccf1e54362377a3d02955010b041a572c64aa209bb3e8b70c1fe5fc76fdad",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_2/banking/injection_tasks.py": "3e678ad165f911dbc16c8307de761dcc15da274716bec7ac0d05db167ec2c311",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_2/travel/injection_tasks.py": "15b8ccee487223bfc6afc58cf05591e3a96fb668eee39d7d47ac2fd98f5173c0",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_2/workspace/injection_tasks.py": "d11a9a4aa86085a1b0e8cea20652dd20f903adedfc6065175a0ead858c29e4a3",  # noqa: E501 (a pinned sha256 is not wrapped)
        "src/agentdojo/default_suites/v1_2_1/workspace/injection_tasks.py": "5a30d439850b58cfb834840bdfe7bbdf4405859bb1899e59ef476f29156078e8",  # noqa: E501 (a pinned sha256 is not wrapped)
        # upstream's benchmark-version table: the resolution TARGET is upstream's fact
        AGENTDOJO_TABLE: "e9c97813ed8295f25526733df044e9adf8ba18567eaeec3455591c4fbc1caa12",
    },
)

SOURCES: dict[str, Source] = {s.name: s for s in (INJECAGENT, BIPIA, AGENTDOJO)}
