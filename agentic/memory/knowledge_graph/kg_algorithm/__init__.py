"""
agentic/memory/kg_algorithm

Algorithmic operations on the knowledge graph.

Unlike kg_writer (extractor-driven CREATE / MERGE) and kg_retriever
(read paths), this package owns operations that traverse or rewrite
the graph based on rules instead of new user input:

    supersession.py
        ``supersede_thought`` -- replace a :Thought with its reframed
        successor and link the two via :SUPERSEDES, preserving the
        bi-temporal trajectory.

    decay.py
        ``run_memory_decay`` -- nightly forgetting curve for :Memory
        nodes. Halves importance after 60 days of no access; flips
        active to false after 180.

Both functions used to live in kg_writer; they were moved here so the
"write a new fact" responsibility stays distinct from the "rewrite
graph state under a rule" responsibility. kg_writer re-exports both
names so existing callers do not break.
"""

from __future__ import annotations

from agentic.memory.knowledge_graph.kg_algorithm.supersession import supersede_thought
from agentic.memory.knowledge_graph.kg_algorithm.decay        import run_memory_decay

__all__ = [
    "supersede_thought",
    "run_memory_decay",
]
