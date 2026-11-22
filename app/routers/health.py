from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    from ..config import VERSION

    return {"status": "ok", "version": VERSION}
