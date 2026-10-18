"""Isolated LangGraph adapter with optional SQLite recovery checkpointing."""

import sqlite3
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, END, StateGraph

from purrfect.guidance import GuidanceDefinition
from purrfect.stateful import TaskState, Turn, advance


class GraphState(TypedDict):
    started: bool
    answers: dict
    turn: Turn
    response: object


class LangGraphConversation:
    def __init__(self, definition: GuidanceDefinition, db_path: str | Path | None = None):
        self.definition = definition
        self._connection = (
            sqlite3.connect(str(db_path), check_same_thread=False)
            if db_path is not None else None
        )
        checkpointer = (
            SqliteSaver(self._connection) if self._connection is not None
            else MemorySaver()
        )

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
        self.graph = builder.compile(checkpointer=checkpointer)

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def send(self, session_id: str, turn: Turn):
        if not session_id:
            raise ValueError("Session ID required")
        result = self.graph.invoke(
            {"turn": turn}, config={"configurable": {"thread_id": session_id}}
        )
        return result["response"]
