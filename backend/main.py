from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from backend.src.api_models import ChatRequest, ChatResponse
from backend.src.config import Settings
from backend.src.graph import create_graph


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "graph", None) is None:
        app.state.graph = create_graph()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
    return {"app": settings.app_name}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _chat_response(result: dict[str, Any]) -> ChatResponse:
    advisory = result.get("response")
    if advisory is None:
        raise ValueError("Graph completed without an advisory response")
    return ChatResponse(
        status=advisory.status,
        message=advisory.message,
        resolved_context=advisory.resolved_context,
        resolved_location=result.get("resolved_location"),
        target_time=result.get("target_time"),
        weather=advisory.weather,
        candidate_policy_ids=result["evidence_plan"].candidate_policy_ids,
        policy_evaluations=result.get("policy_evaluations", []),
        matched_policies=advisory.matched_policies,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    try:
        result = await request.app.state.graph.ainvoke(
            {
                "latest_user_message": payload.message,
                "session_id": payload.session_id,
            },
            config={"configurable": {"thread_id": payload.session_id}},
        )
        return _chat_response(result)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The advisory service could not complete the request.",
        ) from exc
