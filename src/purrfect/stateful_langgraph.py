"""Isolated LangGraph adapter; domain state remains framework-independent."""

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, StateGraph

from purrfect.guidance import GuidanceDefinition
from purrfect.stateful import TaskState, Turn, advance


class GraphState(TypedDict):
    started: bool
    answers: dict
    turn: Turn
    response: object


class LangGraphConversation:
    def __init__(self, definition: GuidanceDefinition):
        self.definition = definition

        def process(state: GraphState):
            new_state, response = advance(
                self.definition,
                TaskState(dict(state.get("answers", {})), state.get("started", False)),
                state["turn"],
            )
            return {
                "started": new_state.started,
                "answers": new_state.answers,
                "response": response,
            }

        builder = StateGraph(GraphState)
        builder.add_node("guide", process)
        builder.add_edge(START, "guide")
        builder.add_edge("guide", END)
        self.graph = builder.compile(checkpointer=MemorySaver())

    def send(self, session_id: str, turn: Turn):
        result = self.graph.invoke(
            {"turn": turn}, config={"configurable": {"thread_id": session_id}}
        )
        return result["response"]
