"""Repairs platform for Nordic Parcel integration."""

from __future__ import annotations

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


class StaleTrackingRepairFlow(RepairsFlow):
    """Repair flow to remove a stale tracking entry."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show confirmation to remove stale tracking."""
        if user_input is not None:
            tracking_id = self.data["tracking_id"]
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.state is not ConfigEntryState.LOADED:
                    continue
                coordinator = entry.runtime_data
                if tracking_id in (coordinator.data or {}):
                    await coordinator.remove_tracking(tracking_id)
                    break

            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="init")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repair flow for fixable issues."""
    if issue_id.startswith("stale_tracking_"):
        flow = StaleTrackingRepairFlow()
        flow.data = data or {}
        return flow
    raise data_entry_flow.UnknownHandler
