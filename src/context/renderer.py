from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .writer_context import WriterContext, WriterContextItem, WriterProjectionItem


@dataclass(slots=True)
class RenderedWriterContext:
    version: str
    text: str
    metadata: dict[str, Any]


class WCFRenderer:
    VERSION = "0.2"
    SECTION_ORDER = [
        "SCENE", "STYLE", "CHARACTERS", "WORLD", "CURRENT", "RELATIONS", "HISTORY",
        "KNOWLEDGE", "BELIEFS", "NORMS", "LOCKED", "NEGATIVE", "TRANSITIONS",
        "UNKNOWN", "PROJECTION", "DERIVABLE", "AUTHORIAL FREEDOM", "SCENE GOAL",
        "BEAT STATE", "SURFACE",
    ]

    @classmethod
    def default(cls): return cls()

    def render(self, context: WriterContext) -> RenderedWriterContext:
        sections: list[tuple[str,list[str]]] = []
        sections.append(("SCENE", self._items(context.scene)))
        sections.append(("STYLE", self._mapping(context.style)))

        char_lines=[]
        for name in sorted(context.characters):
            char_lines.append(f"{name}:")
            char_lines.extend("  - "+self._item_line(item) for item in context.characters[name])
        sections.append(("CHARACTERS", char_lines))
        sections.append(("WORLD", self._items(context.world)))
        sections.append(("CURRENT", self._items(context.current)))
        sections.append(("RELATIONS", ["- "+x for x in context.relations]))
        sections.append(("HISTORY", ["- "+x for x in context.history]))
        sections.append(("KNOWLEDGE", ["- "+x for x in context.knowledge]))
        sections.append(("BELIEFS", ["- "+x for x in context.beliefs]))
        sections.append(("NORMS", ["- "+x for x in context.norms]))
        sections.append(("LOCKED", ["- "+x.label+" must remain exactly as specified in the sections above or in its transition target" for x in context.locked]))
        sections.append(("NEGATIVE", ["- "+x for x in context.negative]))

        transition_lines=[]
        for i,tr in enumerate(context.transitions,1):
            transition_lines.append(f"{i}. {tr.get('event')}" + (f" — target: {tr.get('target')}" if tr.get('target') else ""))
            for key,title in (("preconditions","requires"),("changes","changes"),("invalidates","invalidates"),("preserves","preserves"),("side_effects","side effects")):
                values=tr.get(key) or []
                if values:
                    transition_lines.append(f"   {title}:")
                    for value in values:
                        transition_lines.append("   - "+self._value(value))
        sections.append(("TRANSITIONS", transition_lines))
        sections.append(("UNKNOWN", ["- "+x+"  # exact value/endpoint remains intentionally unspecified" for x in context.unknown]))
        sections.append(("PROJECTION", self._projections(context.projections)))
        sections.append(("DERIVABLE", ["- "+x for x in context.derivable]))
        sections.append(("AUTHORIAL FREEDOM", self._mapping(context.freedom)))
        sections.append(("SCENE GOAL", self._mapping(context.scene_goal)))
        sections.append(("BEAT STATE", self._mapping(context.beat_state)))
        sections.append(("SURFACE", ["- "+x for x in context.surface]))

        lines=[f"@ARLINE-WRITER-CONTEXT {self.VERSION}", ""]
        rendered_sections=[]
        for name,body in sections:
            if not body:
                continue
            rendered_sections.append(name)
            lines.append(f"[{name}]")
            lines.extend(body)
            lines.append("")
        text="\n".join(lines).rstrip()+"\n"
        return RenderedWriterContext(
            version=self.VERSION,
            text=text,
            metadata={
                "wcf_version":self.VERSION,
                "sections":rendered_sections,
                "characters":len(text),
                "lines":len(text.splitlines()),
            },
        )


    def _projections(self, projections: list[WriterProjectionItem]):
        lines=[]
        for index,item in enumerate(projections,1):
            lines.append(
                f"{index}. {item.label} ≈ {self._value(item.value)} "
                f"(confidence {item.confidence:.2f}; non-canonical)"
            )
            if item.applies_after:
                lines.append(f"   applies after: {item.applies_after}")
            if item.target_unknown:
                lines.append(f"   approximates: {item.target_unknown}; exact value remains UNKNOWN")
            if item.assumptions:
                lines.append("   assumptions:")
                for assumption in item.assumptions:
                    lines.append("   - "+str(assumption))
            if item.language_hint:
                lines.append("   surface: "+str(item.language_hint))
            if item.exact_claim_forbidden:
                lines.append("   precision rule: use approximate/relative language; do not promote this projection to an exact fact")
        return lines

    def _items(self, items):
        return ["- "+self._item_line(x) for x in items]

    def _item_line(self,item:WriterContextItem):
        value=self._value(item.value)
        marker={"inferred":"~", "estimated":"≈", "runtime":"="}.get(item.epistemic,"=")
        return f"{item.label} {marker} {value}"

    def _mapping(self,mapping):
        out=[]
        for key in sorted(mapping):
            value=mapping[key]
            if value in (None, [], {}, ""): continue
            out.append(f"- {str(key).replace('_',' ')}: {self._value(value)}")
        return out

    def _value(self,value):
        if isinstance(value,dict):
            return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(", ",": "))
        if isinstance(value,list):
            return ", ".join(self._value(x) for x in value)
        if value is True: return "yes"
        if value is False: return "no"
        if value is None: return "unknown"
        return str(value)
