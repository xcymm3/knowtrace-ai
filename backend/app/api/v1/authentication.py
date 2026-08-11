from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_username_sign_in_service
from app.features.authentication.schemas import (
    UsernameAvailabilityResponse,
    UsernameSignInRequest,
    UsernameSignInResponse,
    UsernameSignUpRequest,
)
from app.features.authentication.service import UsernameSignInService

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get(
    "/username-availability",
    response_model=UsernameAvailabilityResponse,
    summary="Check whether a username is available",
)
async def username_availability(
    username: str = Query(min_length=3, max_length=32),
    service: UsernameSignInService = Depends(get_username_sign_in_service),
) -> UsernameAvailabilityResponse:
    return service.username_availability(username)


@router.post(
    "/sign-in",
    response_model=UsernameSignInResponse,
    summary="Sign in with a username",
)
async def sign_in(
    payload: UsernameSignInRequest,
    service: UsernameSignInService = Depends(get_username_sign_in_service),
) -> UsernameSignInResponse:
    return await service.sign_in(payload)


@router.post(
    "/sign-up",
    response_model=UsernameSignInResponse,
    summary="Create a username-only account",
)
async def sign_up(
    payload: UsernameSignUpRequest,
    service: UsernameSignInService = Depends(get_username_sign_in_service),
) -> UsernameSignInResponse:
    return await service.sign_up(payload)
