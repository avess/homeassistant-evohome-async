#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""evohomeasync provides an async client for the *original* Evohome API."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime as dt
from http import HTTPMethod
from typing import TYPE_CHECKING, NoReturn

import aiohttp

from .broker import Broker, _LocnDataT, _SessionIdT, _UserDataT, _UserInfoT
from .exceptions import DeprecationError, InvalidSchema

if TYPE_CHECKING:
    from .schema import (
        _DeviceDictT,
        _DhwIdT,
        _EvoListT,
        _LocationIdT,
        _SystemModeT,
        _TaskIdT,
        _ZoneIdT,
        _ZoneNameT,
    )


_LOGGER = logging.getLogger(__name__)


class EvohomeClientDeprecated:
    """Deprecated attributes and methods removed from the evohome-client namespace."""

    @property
    def user_data(self) -> _UserDataT | None:
        raise DeprecationError(
            "EvohomeClient.user_data is deprecated, use .user_info"
            " (session_id is now .broker.session_id)"
        )

    @property
    def full_data(self) -> _UserDataT | None:
        raise DeprecationError(
            "EvohomeClient.full_data is deprecated, use .location_data"
        )

    @property
    def headers(self) -> str:
        raise DeprecationError("EvohomeClient.headers is deprecated")

    @property
    def hostname(self) -> str:
        raise DeprecationError(
            "EvohomeClient.hostanme is deprecated, use .broker.hostname"
        )

    @property
    def postdata(self) -> str:
        raise DeprecationError("EvohomeClient.postdata is deprecated")

    async def _wait_for_put_task(self, response: aiohttp.ClientResponse) -> None:
        """This functionality is deprecated, but remains here as documentation."""

        async def get_task_status(task_id: _TaskIdT) -> str:
            await self._populate_locn_data()

            url = f"/commTasks?commTaskId={task_id}"
            response = await self._do_request(HTTPMethod.GET, url)

            ret: str = dict(await response.json())["state"]
            return ret

        task_id: _TaskIdT

        assert response.method == HTTPMethod.PUT

        ret = await response.json()
        task_id = ret[0]["id"] if isinstance(ret, list) else ret["id"]

        # FIXME: could wait forvever?
        while await get_task_status(task_id) != "Succeeded":
            await asyncio.sleep(1)

    # Not deprecated, just a placeholder for self._wait_for_put_task()
    async def _do_request(self, *args, **kwargs) -> aiohttp.ClientResponse:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    # Not deprecated, just a placeholder for self._wait_for_put_task()
    async def _populate_locn_data(self, force_refresh: bool = True) -> _LocnDataT:
        raise NotImplementedError

    async def get_system_modes(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.get_modes() is deprecated, "
            "use .get_system_modes() or .get_zone_modes()"
        )

    async def set_status_away(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_away() is deprecated, use .set_mode_away()"
        )

    async def set_status_custom(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_custom() is deprecated, use .set_mode_custom()"
        )

    async def set_status_dayoff(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_dayoff() is deprecated, use .set_mode_dayoff()"
        )

    async def set_status_eco(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_eco() is deprecated, use .set_mode_eco()"
        )

    async def set_status_heatingoff(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_heatingoff() is deprecated, use .set_mode_heatingoff()"
        )

    async def set_status_normal(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.set_status_normal() is deprecated, use .set_mode_auto()"
        )

    async def temperatures(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.temperatures() is deprecated, use .get_temperatures()"
        )

    async def cancel_temp_override(self, *args, **kwargs) -> NoReturn:  # type: ignore[no-untyped-def]
        raise DeprecationError(
            "EvohomeClient.cancel_temp_override() is deprecated, use .set_zone_auto()"
        )


# nay API request invokes self._populate_user_data()             (for authentication)
# - every API GET invokes self._populate_locn_data(refresh=True) (for up-to-date state)
# - every API PUT invokes self._populate_locn_data()             (for config)


class EvohomeClient(EvohomeClientDeprecated):
    """Provide a client to access the Honeywell TCC API (assumes a single TCS)."""

    user_info: _UserInfoT  # user_data["UserInfo"] only (i.e. *without* "sessionID")
    location_data: _LocnDataT  # of the first location (config and status) in list

    def __init__(
        self,
        username: str,
        password: str,
        /,
        *,
        session_id: _SessionIdT | None = None,
        session: aiohttp.ClientSession | None = None,
        hostname: str | None = None,  # is a URL
        debug: bool = False,
    ) -> None:
        """Construct the v1 EvohomeClient object.

        If a session_id is provided it will be used to avoid calling the
        authentication service, which is known to be rate limited.
        """
        if debug:
            _LOGGER.setLevel(logging.DEBUG)
            _LOGGER.debug("Debug mode is explicitly enabled.")

        self.user_info = {}
        self.location_data = {}
        self.location_id: _LocationIdT = None  # type: ignore[assignment]

        self.devices: dict[_ZoneIdT, _DeviceDictT] = {}  # dhw or zone by id
        self.named_devices: dict[_ZoneNameT, _DeviceDictT] = {}  # zone by name

        self.broker = Broker(
            username,
            password,
            _LOGGER,
            session_id=session_id,
            hostname=hostname,
            session=session,
        )

    @property
    def user_data(self) -> _UserDataT | None:  # TODO: deprecate?
        """Return the user data used for HTTP authentication."""

        if not self.broker.session_id:
            return None
        return {
            "sessionId": self.broker.session_id,
            "userInfo": self.user_info,
        }

    # User methods...

    async def _populate_user_data(
        self, force_refresh: bool = False
    ) -> dict[str, bool | int | str]:
        """Retrieve the cached user data (excl. the session ID).

        Pull the latest JSON from the web only if force_refresh is True.
        """

        if not self.user_info or force_refresh:
            user_data = await self.broker.populate_user_data()
            self.user_info = user_data["userInfo"]  # type: ignore[assignment]

        return self.user_info  # excludes session ID

    async def _get_user(self) -> _UserInfoT:
        """Return the user (if needed, get the JSON)."""

        # only retrieve the config data if we don't already have it
        if not self.user_info:
            await self._populate_user_data(force_refresh=False)
        return self.user_info

    # Location methods...

    async def _populate_locn_data(self, force_refresh: bool = True) -> _LocnDataT:
        """Retrieve the latest system data.

        Pull the latest JSON from the web unless force_refresh is False.
        """

        if not self.location_data or force_refresh:
            full_data = await self.broker.populate_full_data()
            self.location_data = full_data[0]

            self.location_id = self.location_data["locationID"]

            self.devices = {d["deviceID"]: d for d in self.location_data["devices"]}
            self.named_devices = {d["name"]: d for d in self.location_data["devices"]}

        return self.location_data

    async def get_temperatures(
        self, force_refresh: bool = True
    ) -> _EvoListT:  # a convenience function
        """Retrieve the latest details for each zone (incl. DHW)."""

        set_point: float
        status: str

        await self._populate_locn_data(force_refresh=force_refresh)

        result = []

        try:
            for device in self.location_data["devices"]:
                temp = float(device["thermostat"]["indoorTemperature"])
                values = device["thermostat"]["changeableValues"]

                if "heatSetpoint" in values:
                    set_point = float(values["heatSetpoint"]["value"])
                    status = values["heatSetpoint"]["status"]
                else:
                    set_point = 0
                    status = values["status"]

                result.append(
                    {
                        "thermostat": device["thermostatModelType"],
                        "id": device["deviceID"],
                        "name": device["name"],
                        "temp": None if temp == 128 else temp,
                        "setpoint": set_point,
                        "status": status,
                        "mode": values["mode"],
                    }
                )

        # harden code against unexpected schema (JSON structure)
        except (LookupError, TypeError, ValueError) as exc:
            raise InvalidSchema(str(exc)) from exc
        return result

    async def get_system_modes(self) -> NoReturn:
        """Return the set of modes the system can be assigned."""
        raise NotImplementedError

    async def _set_system_mode(
        self, status: _SystemModeT, until: dt | None = None
    ) -> None:
        """Set the system mode."""

        # just want id, so retrieve the config data only if we don't already have it
        await self._populate_locn_data(force_refresh=False)  # get self.location_id

        data = {"QuickAction": status}
        if until:
            data |= {"QuickActionNextTime": until.strftime("%Y-%m-%dT%H:%M:%SZ")}

        url = f"/evoTouchSystems?locationId={self.location_id}"
        await self.broker.make_request(HTTPMethod.PUT, url, data=data)

    async def set_mode_auto(self) -> None:
        """Set the system to normal operation."""
        await self._set_system_mode("Auto")

    async def set_mode_away(self, until: dt | None = None) -> None:
        """Set the system to the away mode."""
        await self._set_system_mode("Away", until)

    async def set_mode_custom(self, until: dt | None = None) -> None:
        """Set the system to the custom programme."""
        await self._set_system_mode("Custom", until)

    async def set_mode_dayoff(self, until: dt | None = None) -> None:
        """Set the system to the day off mode."""
        await self._set_system_mode("DayOff", until)

    async def set_mode_eco(self, until: dt | None = None) -> None:
        """Set the system to the eco mode."""
        await self._set_system_mode("AutoWithEco", until)

    async def set_mode_heatingoff(self, until: dt | None = None) -> None:
        """Set the system to the heating off mode."""
        await self._set_system_mode("HeatingOff", until)

    # Zone methods...

    async def _get_zone(self, id_or_name: _ZoneIdT | _ZoneNameT) -> _DeviceDictT:
        """Return the location's zone by its id or name (if needed, get the JSON).

        Raise an exception if the zone is not found.
        """

        device: _DeviceDictT

        # just want id, so retrieve the config data only if we don't already have it
        await self._populate_locn_data(force_refresh=False)

        if isinstance(id_or_name, int):
            device = self.devices.get(id_or_name)  # type: ignore[assignment]
        else:
            device = self.named_devices.get(id_or_name)  # type: ignore[assignment]

        if device is None:
            raise InvalidSchema(f"No zone {id_or_name} in location {self.location_id}")

        if (model := device["thermostatModelType"]) != "EMEA_ZONE":
            raise InvalidSchema(f"Zone {id_or_name} is not an EMEA_ZONE: {model}")

        assert device is not None  # mypy check

        return device

    async def get_zone_modes(self, zone: _ZoneNameT) -> list[str]:
        """Return the set of modes the zone can be assigned."""

        device = await self._get_zone(zone)

        ret: list[str] = device["thermostat"]["allowedModes"]
        return ret

    async def _set_heat_setpoint(
        self,
        zone: _ZoneIdT | _ZoneNameT,
        status: str,  # "Scheduled" | "Temporary" | "Hold
        value: float | None = None,
        next_time: dt | None = None,  # "%Y-%m-%dT%H:%M:%SZ"
    ) -> None:
        """Set zone setpoint, either indefinitely, or until a set time."""

        zone_id: _ZoneIdT = (await self._get_zone(zone))["deviceID"]

        if next_time is None:
            data = {"Status": "Hold", "Value": value}
        else:
            data = {
                "Status": status,
                "Value": value,
                "NextTime": next_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        url = f"/devices/{zone_id}/thermostat/changeableValues/heatSetpoint"
        await self.broker.make_request(HTTPMethod.PUT, url, data=data)

    async def set_temperature(
        self, zone: _ZoneIdT | _ZoneNameT, temperature: float, until: dt | None = None
    ) -> None:
        """Override the setpoint of a zone, for a period of time, or indefinitely."""

        if until:
            await self._set_heat_setpoint(
                zone, "Temporary", value=temperature, next_time=until
            )
        else:
            await self._set_heat_setpoint(zone, "Hold", value=temperature)

    async def set_zone_auto(self, zone: _ZoneIdT | _ZoneNameT) -> None:
        """Set a zone to follow its schedule."""
        await self._set_heat_setpoint(zone, status="Scheduled")

    # DHW methods...

    async def _get_dhw(self) -> _DeviceDictT:
        """Return the locations's DHW, if there is one (if needed, get the JSON).

        Raise an exception if the DHW is not found.
        """

        # just want id, so retrieve the config data only if we don't already have it
        await self._populate_locn_data(force_refresh=False)

        for device in self.location_data["devices"]:
            if device["thermostatModelType"] == "DOMESTIC_HOT_WATER":
                ret: _DeviceDictT = device
                return ret

        raise InvalidSchema(f"No DHW in location {self.location_id}")

    async def _set_dhw(
        self,
        status: str,  # "Scheduled" | "Hold"
        mode: str | None = None,  # "DHWOn" | "DHWOff
        next_time: dt | None = None,  # "%Y-%m-%dT%H:%M:%SZ"
    ) -> None:
        """Set DHW to Auto, or On/Off, either indefinitely, or until a set time."""

        dhw_id: _DhwIdT = (await self._get_dhw())["deviceID"]

        data = {
            "Status": status,
            "Mode": mode,  # "NextTime": None,
            # "SpecialModes": None, "HeatSetpoint": None, "CoolSetpoint": None,
        }
        if next_time:
            data |= {"NextTime": next_time.strftime("%Y-%m-%dT%H:%M:%SZ")}

        url = f"/devices/{dhw_id}/thermostat/changeableValues"
        await self.broker.make_request(HTTPMethod.PUT, url, data=data)

    async def set_dhw_on(self, until: dt | None = None) -> None:
        """Set DHW to On, either indefinitely, or until a specified time.

        When On, the DHW controller will work to keep its target temperature at/above
        its target temperature.  After the specified time, it will revert to its
        scheduled behaviour.
        """

        await self._set_dhw(status="Hold", mode="DHWOn", next_time=until)

    async def set_dhw_off(self, until: dt | None = None) -> None:
        """Set DHW to Off, either indefinitely, or until a specified time.

        When Off, the DHW controller will ignore its target temperature. After the
        specified time, it will revert to its scheduled behaviour.
        """

        await self._set_dhw(status="Hold", mode="DHWOff", next_time=until)

    async def set_dhw_auto(self) -> None:
        """Allow DHW to switch between On and Off, according to its schedule."""
        await self._set_dhw(status="Scheduled")
