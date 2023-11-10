#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""evohomeasync provides an async client for the *original* Evohome API."""
from __future__ import annotations

import logging
from collections.abc import Callable
from http import HTTPMethod, HTTPStatus
from typing import Any, Final, TypeAlias

import aiohttp

from .exceptions import (
    AuthenticationFailed,
    RateLimitExceeded,
    RequestFailed,
)

_SessionIdT: TypeAlias = str
_UserIdT: TypeAlias = int

_UserInfoT: TypeAlias = dict[str, bool | int | str]
_UserDataT: TypeAlias = dict[str, _SessionIdT | _UserInfoT]
_LocnDataT: TypeAlias = dict[str, Any]


URL_HOST = "https://tccna.honeywell.com"
_APP_ID = "91db1612-73fd-4500-91b2-e63b069b185c"

_LOGGER = logging.getLogger(__name__)


class Broker:
    """Provide a client to access the Honeywell TCC API (assumes a single TCS)."""

    _user_data: _UserDataT
    _full_data: list[_LocnDataT]

    def __init__(
        self,
        username: str,
        password: str,
        logger: logging.Logger,
        /,
        *,
        session_id: _SessionIdT | None = None,
        hostname: str | None = None,  # is a URL
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """A class for interacting with the v1 Evohome API."""

        self.username = username
        self._logger = logger

        self._session_id: _SessionIdT | None = session_id
        self._user_id: _UserIdT | None = None

        self.hostname: Final[str] = hostname or URL_HOST
        self._session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )

        self._headers: dict[str, str] = {
            "content-type": "application/json"
        }  # NB: no sessionId yet
        self._POST_DATA: Final[dict[str, str]] = {
            "Username": self.username,
            "Password": password,
            "ApplicationId": _APP_ID,
        }

        self._user_data = {}
        self._full_data = []

    @property
    def session_id(self) -> _SessionIdT | None:
        """Return the session id used for HTTP authentication."""
        return self._session_id

    async def populate_user_data(self) -> _UserDataT:
        """Return the latest user data as retrieved from the web."""

        user_data: _UserDataT

        user_data, _ = await self._populate_user_data()
        return user_data

    async def _populate_user_data(self) -> tuple[_UserDataT, aiohttp.ClientResponse]:
        """Return the latest user data as retrieved from the web."""

        url = "/session"
        response = await self.make_request(HTTPMethod.POST, url, data=self._POST_DATA)

        self._user_data: _UserDataT = await response.json()

        user_id: _UserIdT = self._user_data["userInfo"]["userID"]  # type: ignore[assignment,index]
        session_id: _SessionIdT = self._user_data["sessionId"]  # type: ignore[assignment]

        self._user_id = user_id
        self._session_id = self._headers["sessionId"] = session_id

        _LOGGER.info(f"user_data = {self._user_data}")
        return self._user_data, response

    async def populate_full_data(self) -> list[_LocnDataT]:
        """Return the latest location data exactly as retrieved from the web."""

        if not self._user_id:  # not yet authenticated
            # maybe was instantiated with a bad session_id, so must check user_id
            await self.populate_user_data()

        url = f"/locations?userId={self._user_id}&allData=True"
        response = await self.make_request(HTTPMethod.GET, url, data=self._POST_DATA)

        self._full_data: list[_LocnDataT] = await response.json()

        _LOGGER.info(f"full_data = {self._full_data}\r\n")
        return self._full_data

    async def _make_request(
        self,
        func: Callable,
        url: str,
        /,
        *,
        data: dict | None = None,
        _dont_reauthenticate: bool = False,  # used only with recursive call
    ) -> aiohttp.ClientResponse:
        """Perform an HTTP request, with an optional retry if re-authenticated."""

        response: aiohttp.ClientResponse

        async with func(url, json=data, headers=self._headers) as response:  # NB: json=
            response_text = await response.text()  # why cant I move this below the if?

            # if 401/unauthorized, may need to refresh sessionId (expires in 15 mins?)
            if response.status != HTTPStatus.UNAUTHORIZED or _dont_reauthenticate:
                return response

            # TODO: use response.content_type to determine whether to use .json()
            if "code" not in response_text:  # don't use .json() yet: may be plain text
                return response

            response_json = await response.json()
            if response_json[0]["code"] != "Unauthorized":
                return response

            if "sessionId" not in self._headers:  # no value trying to re-authenticate
                return response  # ...because: the username/password must be invalid

            _LOGGER.debug(f"Session now expired/invalid ({self._session_id})...")
            self._headers = {"content-type": "application/json"}  # remove the sessionId

            _, response = await self._populate_user_data()  # Get a fresh sessionId
            assert self._session_id is not None  # mypy hint

            _LOGGER.debug(f"... success: new sessionId = {self._session_id}\r\n")
            self._headers["sessionId"] = self._session_id

            if "session" in url:  # retry not needed for /session
                return response

            # NOTE: this is a recursive call, used only after re-authenticating
            response = await self._make_request(
                func, url, data=data, _dont_reauthenticate=True
            )
            return response

    async def make_request(
        self,
        method: HTTPMethod,
        url: str,
        /,
        *,
        data: dict | None = None,
    ) -> aiohttp.ClientResponse:
        """Perform an HTTP request, will authenticate if required."""

        url = self.hostname + "/WebAPI/api" + url

        if method == HTTPMethod.GET:
            func = self._session.get
        elif method == HTTPMethod.PUT:
            func = self._session.put
        elif method == HTTPMethod.POST:
            func = self._session.post

        try:
            response = await self._make_request(func, url, data=data)

        except aiohttp.ClientError as exc:
            if method == HTTPMethod.POST:  # using response will cause UnboundLocalError
                raise AuthenticationFailed(str(exc)) from exc
            raise RequestFailed(str(exc)) from exc

        try:
            response.raise_for_status()

        # response.method, response.url, response.status, response._body
        # POST,    /session, 429, [{code: TooManyRequests, message: Request count limitation exceeded...}]
        # GET/PUT  /???????, 401, [{code: Unauthorized,    message: Unauthorized}]

        except aiohttp.ClientResponseError as exc:
            if response.method == HTTPMethod.POST:  # POST only used when authenticating
                raise AuthenticationFailed(
                    str(exc), status=exc.status
                ) from exc  # could be TOO_MANY_REQUESTS
            if response.status != HTTPStatus.TOO_MANY_REQUESTS:
                raise RateLimitExceeded(str(exc), status=exc.status) from exc
            raise RequestFailed(str(exc), status=exc.status) from exc

        except aiohttp.ClientError as exc:
            if response.method == HTTPMethod.POST:  # POST only used when authenticating
                raise AuthenticationFailed(str(exc)) from exc
            raise RequestFailed(str(exc)) from exc

        return response