from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from .renderer import WCFRenderer
from .writer_context import WriterContext, WriterContextItem


class TokenCounter:
    """Token counting interface with a deterministic fallback heuristic."""
    def __init__(self, tokenizer: Callable[[str], int] | None = None, *, source: str = "heuristic"):
        self.tokenizer=tokenizer
        self.source=source

    @classmethod
    def from_lmstudio(cls, model_key: str):
        """Use the selected loaded model's real tokenizer when SDK is available."""
        try:
            import lmstudio as lms
            model = lms.llm(model_key)
            return cls(lambda text: len(model.tokenize(text)), source="lmstudio_model_tokenizer")
        except Exception:
            return cls()

    def count(self,text:str)->int:
        if self.tokenizer:
            try: return int(self.tokenizer(text))
            except Exception: pass
        # Conservative language-agnostic-ish approximation: words/punctuation
        # plus a small multiplier for subword fragmentation.
        units=len(re.findall(r"\w+|[^\w\s]",text,flags=re.UNICODE))
        return max(1,int(units*1.22))


@dataclass(slots=True)
class ContextBudget:
    model_context_length:int=32768
    max_output_tokens:int=3072
    system_prompt_tokens:int=1200
    safety_margin:int=1536
    minimum_writer_context:int=2048

    @property
    def writer_context_budget(self):
        return max(self.minimum_writer_context, self.model_context_length-self.max_output_tokens-self.system_prompt_tokens-self.safety_margin)


class ContextBudgeter:
    """Prune semantic items by priority; never raw-truncate the WCF string."""
    def __init__(self,counter:TokenCounter|None=None):
        self.counter=counter or TokenCounter(); self.renderer=WCFRenderer.default()

    def fit(self,context:WriterContext,budget:ContextBudget):
        rendered=self.renderer.render(context)
        count=self.counter.count(rendered.text)
        if count<=budget.writer_context_budget:
            rendered.metadata.update({"estimated_tokens":count,"budget_tokens":budget.writer_context_budget,"pruned":False,"token_counter":self.counter.source})
            return context,rendered

        # P0/P1 are never removed. Remove latent highest-number priority first.
        pools=[]
        for collection_name in ("scene","world","current","locked"):
            collection=getattr(context,collection_name)
            for item in collection:
                pools.append((item.priority,collection_name,item))
        for cname,items in context.characters.items():
            for item in items: pools.append((item.priority,"characters:"+cname,item))
        pools.sort(key=lambda x:x[0],reverse=True)

        removed=[]
        for priority,where,item in pools:
            if priority<2: continue
            if where.startswith("characters:"):
                cname=where.split(":",1)[1]
                if item in context.characters.get(cname,[]): context.characters[cname].remove(item)
            else:
                collection=getattr(context,where)
                if item in collection: collection.remove(item)
            removed.append(item.key)
            rendered=self.renderer.render(context); count=self.counter.count(rendered.text)
            if count<=budget.writer_context_budget: break

        # Projections are useful but non-canonical. Drop low-priority visual
        # projections before sacrificing P0/P1 canonical facts.
        for projection in sorted(list(context.projections), key=lambda x:x.priority, reverse=True):
            if count<=budget.writer_context_budget: break
            if projection.priority < 2: continue
            if projection in context.projections:
                context.projections.remove(projection)
                removed.append(projection.key)
                rendered=self.renderer.render(context); count=self.counter.count(rendered.text)

        # Last resort: remove lower-value derivables/history before touching canonical P0/P1.
        while count>budget.writer_context_budget and context.derivable:
            context.derivable.pop(); rendered=self.renderer.render(context); count=self.counter.count(rendered.text)
        while count>budget.writer_context_budget and len(context.history)>2:
            context.history.pop(); rendered=self.renderer.render(context); count=self.counter.count(rendered.text)

        # If the prompt is extremely dense, even P1 projections yield before
        # canonical P0/P1 state. The facts that produced them remain available.
        while count>budget.writer_context_budget and context.projections:
            projection=context.projections.pop()
            removed.append(projection.key)
            rendered=self.renderer.render(context); count=self.counter.count(rendered.text)

        rendered.metadata.update({"estimated_tokens":count,"budget_tokens":budget.writer_context_budget,"pruned":bool(removed),"removed_keys":removed,"token_counter":self.counter.source})
        return context,rendered
