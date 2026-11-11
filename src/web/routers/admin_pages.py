from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse

from src.web.deps import require_admin_user_page

router = APIRouter(tags=["web"], dependencies=[Depends(require_admin_user_page)])


# Перенаправляет с корня админки на вкладку заказов (в шапке доступны обе вкладки).
@router.get("/internal/admin", include_in_schema=False)
async def admin_index() -> RedirectResponse:
    return RedirectResponse(
        url="/internal/admin/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
