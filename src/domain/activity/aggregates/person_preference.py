from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from domain.common.aggregate import AggregateRoot
from domain.common.identifier import Identifier

from ..enums.signoff_reminder_policy import SignoffReminderPolicy


class PersonPreference(AggregateRoot):
    """
    Aggregate root representing an individual person's operational preferences.

    Maintains preferences such as sign-off reminder behavior and an
    optional preferred IANA timezone override.
    """

    def __init__(
        self,
        *,
        person_id: str,
        reminders_after_signoff: SignoffReminderPolicy | str = SignoffReminderPolicy.CONTINUE,
        preferred_timezone: str | None = None,
        identifier: Identifier | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__(
            identifier=identifier or Identifier(),
            metadata=dict(metadata or {}),
        )

        if created_at is not None:
            self.created_at = created_at
        if updated_at is not None:
            self.updated_at = updated_at

        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a non-empty string.")

        if isinstance(reminders_after_signoff, str):
            try:
                normalized_policy = SignoffReminderPolicy(
                    reminders_after_signoff.lower()
                )
            except ValueError as err:
                raise ValueError(
                    f"Invalid SignoffReminderPolicy: {reminders_after_signoff}"
                ) from err
        elif isinstance(reminders_after_signoff, SignoffReminderPolicy):
            normalized_policy = reminders_after_signoff
        else:
            raise ValueError(
                f"Unsupported type for SignoffReminderPolicy: {type(reminders_after_signoff)}"
            )

        validated_tz: str | None = None
        if preferred_timezone is not None:
            if not isinstance(preferred_timezone, str) or not preferred_timezone.strip():
                raise ValueError("preferred_timezone cannot be an empty string.")
            cleaned_tz = preferred_timezone.strip()
            try:
                ZoneInfo(cleaned_tz)
            except Exception as err:
                raise ValueError(f"Invalid timezone: {preferred_timezone}") from err
            validated_tz = cleaned_tz

        self.person_id = person_id
        self.reminders_after_signoff = normalized_policy
        self.preferred_timezone = validated_tz

    @classmethod
    def create(
        cls,
        *,
        person_id: str,
        reminders_after_signoff: SignoffReminderPolicy | str = SignoffReminderPolicy.CONTINUE,
        preferred_timezone: str | None = None,
        business_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PersonPreference:
        """
        Create a new PersonPreference aggregate.
        """
        return cls(
            identifier=Identifier(business_id=business_id),
            person_id=person_id,
            reminders_after_signoff=reminders_after_signoff,
            preferred_timezone=preferred_timezone,
            metadata=metadata,
        )

    def update_reminders_after_signoff(
        self,
        policy: SignoffReminderPolicy | str,
    ) -> None:
        """
        Update the sign-off reminder policy.
        """
        if isinstance(policy, str):
            try:
                normalized_policy = SignoffReminderPolicy(policy.lower())
            except ValueError as err:
                raise ValueError(
                    f"Invalid SignoffReminderPolicy: {policy}"
                ) from err
        elif isinstance(policy, SignoffReminderPolicy):
            normalized_policy = policy
        else:
            raise ValueError(
                f"Unsupported type for SignoffReminderPolicy: {type(policy)}"
            )

        self.reminders_after_signoff = normalized_policy
        self.touch()

    def update_preferred_timezone(
        self,
        timezone: str | None,
    ) -> None:
        """
        Update or clear the preferred IANA timezone.
        """
        if timezone is not None:
            if not isinstance(timezone, str) or not timezone.strip():
                raise ValueError("preferred_timezone cannot be an empty string.")
            cleaned_tz = timezone.strip()
            try:
                ZoneInfo(cleaned_tz)
            except Exception as err:
                raise ValueError(f"Invalid timezone: {timezone}") from err
            validated_tz: str | None = cleaned_tz
        else:
            validated_tz = None

        self.preferred_timezone = validated_tz
        self.touch()
