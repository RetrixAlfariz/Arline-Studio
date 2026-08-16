from __future__ import annotations

from typing import Any

from .writer_context import WriterContext


class TraceResolver:
    @staticmethod
    def options(context:WriterContext)->list[tuple[str,str]]:
        out=[]
        for trace_id,data in sorted(context.trace_index.items()):
            writer=data.get("writer_fact")
            if writer: out.append((writer,trace_id))
        return out

    @staticmethod
    def resolve(context:WriterContext,trace_id:str)->dict[str,Any]:
        return dict(context.trace_index.get(trace_id) or {})
