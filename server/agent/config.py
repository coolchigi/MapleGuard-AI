"""Deployment config — the config-swappable seam between offline dev and live AWS.

One `Deployment` record decides which memory backend and which session store the agent uses.
The default is fully offline (dev memory, file sessions), so everything runs and tests with
no AWS. Setting a few env vars (or fields) flips individual seams to Bedrock / S3 without
touching orchestration code. The AWS-backed builders construct the real clients; they are not
faked, so they simply require live creds to answer.

Env vars (all optional; absence = offline dev):
  MAPLEGUARD_MEMORY_BACKEND   dev | bedrock_kb | none      (default dev)
  MAPLEGUARD_KB_ID            Bedrock Knowledge Base id     (required if bedrock_kb)
  MAPLEGUARD_KB_REGION        AWS region for the KB
  MAPLEGUARD_SESSION_BACKEND  file | s3 | agentcore | none  (default file)
  MAPLEGUARD_SESSION_DIR      dir for file sessions
  MAPLEGUARD_SESSION_BUCKET   S3 bucket (required if s3)
  MAPLEGUARD_SESSION_PREFIX   S3 key prefix
  MAPLEGUARD_MEMORY_ID        AgentCore Memory id (required if session_backend=agentcore)
  MAPLEGUARD_MEMORY_REGION    AWS region for AgentCore Memory
  MAPLEGUARD_ACTOR_ID         per-user actor id for the longitudinal profile (default from
                              session_id)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Deployment:
    """Which backends the agent uses. Defaults are offline dev, no AWS."""
    memory_backend: str = "dev"          # "dev" | "bedrock_kb" | "none"
    knowledge_base_id: Optional[str] = None
    kb_region: Optional[str] = None
    seed_corpus: bool = True             # seed the dev corpus from noc.OCCUPATIONS
    session_backend: str = "file"        # "file" | "s3" | "agentcore" | "none"
    session_dir: Optional[str] = None    # file sessions dir (None = SDK default)
    s3_bucket: Optional[str] = None
    s3_prefix: str = ""
    memory_id: Optional[str] = None      # AgentCore Memory id (session_backend=agentcore)
    memory_region: Optional[str] = None  # AWS region for AgentCore Memory
    actor_id: Optional[str] = None       # per-user id for the longitudinal profile

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "Deployment":
        e = os.environ if env is None else env
        return cls(
            memory_backend=e.get("MAPLEGUARD_MEMORY_BACKEND", "dev"),
            knowledge_base_id=e.get("MAPLEGUARD_KB_ID"),
            kb_region=e.get("MAPLEGUARD_KB_REGION"),
            seed_corpus=e.get("MAPLEGUARD_SEED_CORPUS", "1") not in ("0", "false", "False"),
            session_backend=e.get("MAPLEGUARD_SESSION_BACKEND", "file"),
            session_dir=e.get("MAPLEGUARD_SESSION_DIR"),
            s3_bucket=e.get("MAPLEGUARD_SESSION_BUCKET"),
            s3_prefix=e.get("MAPLEGUARD_SESSION_PREFIX", ""),
            memory_id=e.get("MAPLEGUARD_MEMORY_ID"),
            memory_region=e.get("MAPLEGUARD_MEMORY_REGION"),
            actor_id=e.get("MAPLEGUARD_ACTOR_ID"),
        )

    @property
    def is_offline(self) -> bool:
        """True when no seam reaches AWS (safe to run anywhere)."""
        return (self.memory_backend in ("dev", "none")
                and self.session_backend in ("file", "none"))


def build_memory(config: Deployment):
    """The MemoryManager for this deployment, or None if memory is disabled.

    dev -> seeded TestMemoryStore (offline). bedrock_kb -> real BedrockKnowledgeBaseStore
    (needs live Bedrock). Returns (MemoryManager, store) or None.
    """
    if config.memory_backend == "none":
        return None
    if config.memory_backend == "dev":
        from .memory import build_test_memory
        return build_test_memory(seed=config.seed_corpus)
    if config.memory_backend == "bedrock_kb":
        if not config.knowledge_base_id:
            raise ValueError("memory_backend=bedrock_kb requires knowledge_base_id "
                             "(set MAPLEGUARD_KB_ID)")
        from .memory import build_kb_memory
        extra = {"region_name": config.kb_region} if config.kb_region else {}
        return build_kb_memory(config.knowledge_base_id, **extra)
    raise ValueError(f"unknown memory_backend {config.memory_backend!r}")


def build_session_manager(session_id: str, config: Deployment) -> Optional[Any]:
    """The SessionManager for this deployment, or None if sessions are disabled.

    file -> FileSessionManager (offline, dev/demo). s3 -> S3SessionManager (needs AWS).
    agentcore -> AgentCoreMemorySessionManager, the longitudinal per-user profile across
    sessions (needs AWS). The demo uses file; each swap is config only. Verified importable
    against strands-agents 1.54.0 and bedrock-agentcore 1.22.0.
    """
    if config.session_backend == "none":
        return None
    if config.session_backend == "file":
        from strands.session.file_session_manager import FileSessionManager
        kwargs = {"storage_dir": config.session_dir} if config.session_dir else {}
        return FileSessionManager(session_id=session_id, **kwargs)
    if config.session_backend == "s3":
        if not config.s3_bucket:
            raise ValueError("session_backend=s3 requires s3_bucket (set MAPLEGUARD_SESSION_BUCKET)")
        from strands.session.s3_session_manager import S3SessionManager
        return S3SessionManager(session_id=session_id, bucket=config.s3_bucket,
                                prefix=config.s3_prefix)
    if config.session_backend == "agentcore":
        if not config.memory_id:
            raise ValueError("session_backend=agentcore requires memory_id "
                             "(set MAPLEGUARD_MEMORY_ID)")
        from .memory import build_agentcore_session_manager
        return build_agentcore_session_manager(
            memory_id=config.memory_id, session_id=session_id,
            actor_id=config.actor_id or session_id, region_name=config.memory_region)
    raise ValueError(f"unknown session_backend {config.session_backend!r}")
