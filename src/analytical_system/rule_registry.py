from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleSpec:
    name:str
    domain:str
    requires:tuple[str,...]
    produces:tuple[str,...]
    priority:float=.5

    def to_dict(self): return asdict(self)


class RuleRegistry:
    VERSION="0.1"
    def __init__(self,rules): self.rules=list(rules)

    @classmethod
    def default(cls):
        # Import lazily to avoid a circular import: the domain rule modules
        # use RuleSpec from this module, while the registry aggregates them.
        from .rules import DEFAULT_RULES
        return cls(DEFAULT_RULES)

    def summary(self):
        return {"version":self.VERSION,"rules":[x.to_dict() for x in self.rules],"count":len(self.rules)}

    def for_domain(self,domain): return [x for x in self.rules if x.domain==domain]
