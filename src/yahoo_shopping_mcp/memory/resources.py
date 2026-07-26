from __future__ import annotations

import json

from yahoo_shopping_mcp.memory.ontology import ontology_document

SCHEMA_RESOURCE_URI = "memory://yahoo-shopping/schema/v1"
INSTRUCTIONS_RESOURCE_URI = "memory://yahoo-shopping/instructions/v1"
PROFILE_SUMMARY_RESOURCE_URI = "memory://yahoo-shopping/profile/current/summary"

MEMORY_INSTRUCTIONS = """\
このグラフは、ユーザーの購買嗜好、購入意図、適用条件、根拠、優先関係、競合、変更履歴を表す。

MemorySpace は検索範囲であり、意味関係そのものではない。
Claim は判断可能な主張、Context は適用条件、Concept は主張の対象、Evidence は根拠を表す。

新規 Node を提案する前に route_memory_spaces と search_claim_candidates を使い、
必要な候補だけ get_claim_neighborhood で確認すること。全グラフを要求しないこと。
書き込みは preview_preference_memory_update で Preview 検査し、ユーザーの明示確認後だけ
apply_preference_memory_update を呼ぶこと。client は Cypher、任意 label/relation、
subject ID、永続 ID を指定しないこと。
"""


def schema_resource_text() -> str:
    return json.dumps(ontology_document(), ensure_ascii=False, indent=2)
