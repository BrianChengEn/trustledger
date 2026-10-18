from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from app.adapters.synthetic import load_transactions
from app.core.auth import require_admin
from app.core.demo_edit import DemoEditor
from app.schemas.demo_admin import (
    ROW_CAP, DemoLogEntry, DemoRow, DemoStatus, DemoTransactionIn, DemoTransactionPatch, ResetResult,
    ScenarioName, ScenarioResult,
)

router = APIRouter(prefix="/api/v1/admin/demo", tags=["local-admin"], dependencies=[Depends(require_admin)])
TransactionId = Annotated[str, Path(min_length=1, max_length=80, pattern=r"^txn_[A-Za-z0-9_-]+$")]


def enabled(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.allow_demo_edit:
        raise HTTPException(403, "demo_edit_disabled")
    if settings.transaction_provider != "synthetic":
        # With a Nessie-backed workspace the transactions shown are not these rows, so editing them would mislead.
        raise HTTPException(409, "not_synthetic_mode")


def editor(request: Request) -> DemoEditor:
    return DemoEditor(request.app.state.store, request.app.state.settings.demo_user_id)


Editor = Annotated[DemoEditor, Depends(editor)]
Enabled = Depends(enabled)


@router.get("/status", response_model=DemoStatus)
def status(request: Request, demo: Editor):
    settings = request.app.state.settings
    usable = settings.allow_demo_edit and settings.transaction_provider == "synthetic"
    return DemoStatus(enabled=usable, rows=len(demo.rows()) if usable else 0, cap=ROW_CAP)


@router.get("/transactions", response_model=list[DemoRow], dependencies=[Enabled])
def list_rows(demo: Editor):
    return demo.rows()


@router.post("/transactions", response_model=DemoRow, status_code=201, dependencies=[Enabled])
def create(body: DemoTransactionIn, demo: Editor):
    return demo.create(body)


@router.patch("/transactions/{tx_id}", response_model=DemoRow, dependencies=[Enabled])
def update(tx_id: TransactionId, body: DemoTransactionPatch, demo: Editor):
    return demo.update(tx_id, body)


@router.delete("/transactions/{tx_id}", status_code=204, dependencies=[Enabled])
def delete(tx_id: TransactionId, demo: Editor):
    demo.delete(tx_id)
    return Response(status_code=204)


@router.post("/scenarios/{name}", response_model=ScenarioResult, dependencies=[Enabled])
def scenario(name: ScenarioName, demo: Editor):
    return ScenarioResult(scenario=name, created=demo.scenario(name))


@router.post("/reset", response_model=ResetResult, dependencies=[Enabled])
def reset(request: Request, demo: Editor):
    return demo.reset(load_transactions(None, request.app.state.settings.demo_user_id))


@router.get("/log", response_model=list[DemoLogEntry], dependencies=[Enabled])
def log(demo: Editor, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return demo.log(limit)
