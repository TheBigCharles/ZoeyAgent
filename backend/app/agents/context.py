"""Reusable context assembly for LLM nodes and planner prompts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.schemas.graph import ContextConfig, ContextPacket, ContextProfile, PromptTemplateSpec, TravelPlanState


@dataclass(slots=True)
class ContextAssemblyResult:
    selected_packets: list[ContextPacket]
    text: str
    total_tokens: int


class ContextAssembler:
    def __init__(self, config: ContextConfig | None = None) -> None:
        self.config = config or ContextConfig()

    def assemble(
        self,
        state: TravelPlanState,
        profile: ContextProfile,
        prompt_template: PromptTemplateSpec | None = None,
    ) -> ContextAssemblyResult:
        packets = self._candidate_packets(state)
        selected = self._select_packets(packets, profile)
        sections = self._structure_sections(selected, profile, prompt_template)
        return ContextAssemblyResult(
            selected_packets=selected,
            text="\n\n".join(sections),
            total_tokens=sum(packet.token_count for packet in selected),
        )

    def _candidate_packets(self, state: TravelPlanState) -> list[ContextPacket]:
        packets = list(state.get("context_packets", []))
        now = datetime.now(timezone.utc)

        request = state.get("request")
        if request is not None:
            packets.append(
                ContextPacket(
                    content=(
                        f"Cities: {', '.join(request.cities)}; dates: {request.start_date} to {request.end_date}; "
                        f"budget: {request.budget}; extra requirements: {request.extra_requirements}"
                    ),
                    timestamp=now,
                    token_count=40,
                    relevance_score=1.0,
                    recency_score=1.0,
                    importance=1.0,
                    confidence=1.0,
                    source="request",
                )
            )

        for memory in state.get("semantic_memories", []):
            packets.append(self._packet_from_value(memory, source="semantic", timestamp=now))
        for memory in state.get("episodic_memories", []):
            packets.append(self._packet_from_value(memory, source="episodic", timestamp=now))
        for observation in state.get("tool_observations", []):
            packets.append(self._packet_from_value(observation, source="tool", timestamp=now))
        for error in state.get("validation_errors", []):
            packets.append(self._packet_from_value(error, source="validation", timestamp=now))

        return packets

    def _packet_from_value(self, value: Any, source: str, timestamp: datetime) -> ContextPacket:
        content = value if isinstance(value, str) else str(value)
        return ContextPacket(
            content=content,
            timestamp=timestamp,
            token_count=max(1, len(content.split())),
            relevance_score=0.8,
            recency_score=0.8,
            importance=0.7,
            confidence=0.7,
            source=source,
        )

    def _select_packets(self, packets: list[ContextPacket], profile: ContextProfile) -> list[ContextPacket]:
        allowed_sources = set(profile.allowed_sources)
        budget = min(profile.max_tokens, int(self.config.max_tokens * (1 - self.config.reserve_ratio)))
        selected: list[ContextPacket] = []
        used_tokens = 0

        eligible = [
            packet
            for packet in packets
            if (not allowed_sources or packet.source in allowed_sources)
            and packet.relevance_score >= self.config.min_relevance
        ]
        eligible.sort(key=self._score_packet, reverse=True)

        for packet in eligible:
            remaining = budget - used_tokens
            if remaining <= 0:
                break
            if packet.token_count <= remaining:
                selected.append(packet)
                used_tokens += packet.token_count
                continue
            if self.config.enable_compression and remaining > 0:
                selected.append(self._compress_packet(packet, remaining))
                used_tokens += remaining
                break

        return selected

    def _score_packet(self, packet: ContextPacket) -> float:
        return (
            packet.relevance_score * self.config.relevance_weight
            + packet.recency_score * self.config.recency_weight
            + packet.importance * self.config.importance_weight
            + packet.confidence * self.config.confidence_weight
        )

    def _compress_packet(self, packet: ContextPacket, token_budget: int) -> ContextPacket:
        words = packet.content.split()
        compressed_content = " ".join(words[:token_budget])
        return packet.model_copy(update={"content": compressed_content, "token_count": token_budget})

    def _structure_sections(
        self,
        packets: list[ContextPacket],
        profile: ContextProfile,
        prompt_template: PromptTemplateSpec | None,
    ) -> list[str]:
        section_by_source = {
            "request": "User Request",
            "semantic": "Known User Preferences",
            "episodic": "Relevant Past Decisions",
            "tool": "Tool Observations",
            "validation": "Validation Errors",
        }
        content_by_section: dict[str, list[str]] = {}
        for packet in packets:
            section = section_by_source.get(packet.source, packet.source)
            content_by_section.setdefault(section, []).append(packet.content)

        sections = []
        for section in profile.required_sections:
            contents = content_by_section.pop(section, [])
            body = "\n".join(contents) if contents else "(none)"
            sections.append(f"[{section}]\n{body}")

        for section, contents in content_by_section.items():
            sections.append(f"[{section}]\n" + "\n".join(contents))

        if prompt_template is not None:
            sections.append(f"[Output Schema]\n{prompt_template.output_schema_name}")
        return sections


async def assemble_planner_context(state: TravelPlanState) -> dict[str, Any]:
    profile = ContextProfile(
        profile_name="global_planner",
        max_tokens=3000,
        allowed_sources=["request", "semantic", "episodic", "tool", "validation"],
        required_sections=[
            "User Request",
            "Known User Preferences",
            "Relevant Past Decisions",
            "Tool Observations",
            "Validation Errors",
        ],
        output_schema_name="TripPlan",
    )
    prompt = PromptTemplateSpec(
        template_name="global_planner",
        role="You are a travel planner.",
        task="Generate a valid TripPlan.",
        output_schema_name="TripPlan",
    )
    result = ContextAssembler().assemble(state, profile=profile, prompt_template=prompt)
    return {
        "context_packets": result.selected_packets,
        "planner_context": result.text,
    }
