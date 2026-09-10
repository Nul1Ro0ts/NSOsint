# --- nsoint/modules/phone.py ---
"""Phone number intelligence: carrier, region, type, timezone."""

from __future__ import annotations

from typing import Any

import phonenumbers
from phonenumbers import carrier, geocoder
from phonenumbers import timezone as pn_tz

from ..core import Result


def _line_type(parsed: phonenumbers.PhoneNumber) -> str:
    ntype = phonenumbers.number_type(parsed)
    return {
        phonenumbers.PhoneNumberType.MOBILE: "mobile",
        phonenumbers.PhoneNumberType.FIXED_LINE: "fixed_line",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
        phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
        phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium_rate",
        phonenumbers.PhoneNumberType.VOIP: "voip",
        phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "personal",
        phonenumbers.PhoneNumberType.PAGER: "pager",
        phonenumbers.PhoneNumberType.UAN: "uan",
        phonenumbers.PhoneNumberType.VOICEMAIL: "voicemail",
    }.get(ntype, "unknown")


def scan_phone(number: str, region: str | None = None) -> Result:
    try:
        parsed = phonenumbers.parse(number, region)
    except phonenumbers.NumberParseException as exc:
        return Result("phone.info", number, False, error=str(exc))

    if not phonenumbers.is_valid_number(parsed):
        return Result("phone.info", number, False, error="invalid_number")

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    data: dict[str, Any] = {
        "e164": e164,
        "international": phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        ),
        "country_code": parsed.country_code,
        "national_number": parsed.national_number,
        "region": phonenumbers.region_code_for_number(parsed) or None,
        "carrier": carrier.name_for_number(parsed, "en") or None,
        "location": geocoder.description_for_number(parsed, "en") or None,
        "timezones": sorted(pn_tz.time_zones_for_number(parsed)),
        "line_type": _line_type(parsed),
        "possible": phonenumbers.is_possible_number(parsed),
        "valid": True,
    }
    return Result("phone.info", number, True, data=data)
