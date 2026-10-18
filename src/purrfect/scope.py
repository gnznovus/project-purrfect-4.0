"""Scope-down over installed product evidence and everyday WP knowledge."""

import json
from dataclasses import dataclass

from purrfect.brain import TextModel
from purrfect.guidance import GuidanceResponse, InputKind, Interaction, Option
from purrfect.knowledge import Evidence, SiteKnowledge


@dataclass(frozen=True, slots=True)
class ScopeAnswer:
    scope: str
    response: GuidanceResponse
    evidence: tuple[Evidence, ...] = ()


class ScopeGuide:
    def __init__(self, model: TextModel, knowledge: SiteKnowledge):
        self.model = model
        self.knowledge = knowledge

    async def answer(self, message: str) -> ScopeAnswer:
        if not message.strip():
            raise ValueError("Request cannot be empty")
        ids = tuple(self.knowledge.products)
        catalog = [
            {"id": p.id, "capabilities": list(p.capabilities)}
            for p in self.knowledge.products.values()
        ]
        raw = await self.model.complete(
            "Classify into exactly one scope: product, wordpress, clarify, unsupported. "
            "For product return product_ids from the given catalog only. "
            "For unclear overlap select clarify. Do not invent capabilities or solutions. "
            "Return JSON with exactly scope and product_ids.",
            json.dumps({"request": message, "registered_products": catalog}),
        )
        try:
            data = json.loads(raw)
            if (not isinstance(data, dict) or set(data) != {"scope", "product_ids"}
                    or data["scope"] not in ("product", "wordpress", "clarify", "unsupported")
                    or not isinstance(data["product_ids"], list)
                    or any(not isinstance(pid, str) or pid not in ids
                           for pid in data["product_ids"])
                    or len(set(data["product_ids"])) != len(data["product_ids"])
                    or (data["scope"] == "product" and not data["product_ids"])
                    or (data["scope"] != "product" and data["product_ids"])):
                raise ValueError("Invalid scope")
        except (TypeError, ValueError, KeyError):
            return self._clarify(ids)
        if data["scope"] == "clarify":
            return self._clarify(ids)
        if data["scope"] == "unsupported":
            return ScopeAnswer("unsupported", GuidanceResponse(
                "That is beyond my supported product and everyday WordPress guidance.",
                "unsupported",
            ))
        scope = data["scope"]
        evidence = self.knowledge.search(
            message, product_ids=tuple(data["product_ids"]),
            general_wp=(scope == "wordpress"),
        )
        if not evidence:
            return ScopeAnswer(scope, GuidanceResponse(
                "I don't have verified guidance for that specific issue. "
                "Could you describe which feature and problem you're seeing?",
                "clarification",
            ))
        # Evidence is quoted from approved records, not improvised by a model.
        return ScopeAnswer(scope, GuidanceResponse(
            "\n\n".join(item.text for item in evidence), "grounded",
        ), evidence)

    def choose(self, message: str, choice: str) -> ScopeAnswer:
        """Consume an explicit selection from the offered scope choices."""
        if not message.strip():
            raise ValueError("Request cannot be empty")
        if choice == "other":
            return ScopeAnswer("unsupported", GuidanceResponse(
                "That is outside my registered-product and everyday WordPress support.",
                "unsupported",
            ))
        if choice == "wordpress":
            scope, evidence = "wordpress", self.knowledge.search(message, general_wp=True)
        elif choice in self.knowledge.products:
            scope, evidence = "product", self.knowledge.search(
                message, product_ids=(choice,),
            )
        else:
            return self._clarify(tuple(self.knowledge.products))
        if not evidence:
            return ScopeAnswer(scope, GuidanceResponse(
                "I don't have verified guidance for that issue yet. "
                "Which feature are you trying to use?",
                "clarification",
            ))
        return ScopeAnswer(scope, GuidanceResponse(
            "\\n\\n".join(item.text for item in evidence), "grounded",
        ), evidence)

    @staticmethod
    def _clarify(ids: tuple[str, ...]) -> ScopeAnswer:
        options = tuple([Option(pid, pid) for pid in ids] + [
            Option("wordpress", "General WordPress"), Option("other", "Something else"),
        ])
        return ScopeAnswer("clarify", GuidanceResponse(
            "Is the problem with one of these installed products, or with WordPress itself?",
            "needs_input",
            Interaction(InputKind.SINGLE_SELECT, "support_scope", options),
        ))
