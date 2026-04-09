"""Home Assistant GoodWe SEMS Curtailment integration.

Controls GoodWe solar inverter output via the SEMS Portal API based on
Amber Electric pricing, preventing unwanted solar export when prices are negative.

Requires ha-custom-amber-integration (hacs-custom-amber-integration) to be
installed and running — this integration reads Amber price helpers that are
populated by that project.

This __init__.py exists to satisfy the HACS custom_components structure requirement.
All logic runs via HA automations and shell scripts.
"""
