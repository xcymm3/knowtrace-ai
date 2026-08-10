from fastapi import APIRouter, Depends

from app.api.dependencies import get_username_sign_in_service
from app.features.authentication.schemas import UsernameSignInRequest, UsernameSignInResponse
from app.features.authentication.service import UsernameSignInService

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/sign-in",
    response_model=UsernameSignInResponse,
    summary="Sign in with email or username",
)
async def sign_in(
    payload: UsernameSignInRequest,
    service: UsernameSignInService = Depends(get_username_sign_in_service),
) -> UsernameSignInResponse:
    return await service.sign_in(payload)
