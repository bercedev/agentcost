"""agentcost public API."""

from importlib.metadata import PackageNotFoundError, version as _metadata_version

from agentcost.cost import TokenUsage, CostBreakdown, calculate_cost, summarize_usage
from agentcost.parsers import ClaudeCodeParser, CodexParser, HermesParser, OpenCodeParser
from agentcost.hermes_output import HermesOutputParser
from agentcost.discovery import LogDiscovery
from agentcost.report import ReportGenerator
from agentcost.persistence import CostPersistence
from agentcost.forecasting import Forecast, ForecastPoint, forecast

try:
    __version__ = _metadata_version("agentcost-py")
except PackageNotFoundError:  # running from a source checkout, not an install
    __version__ = "0.0.0.dev0"

__all__ = [
    "TokenUsage",
    "CostBreakdown",
    "calculate_cost",
    "summarize_usage",
    "ClaudeCodeParser",
    "CodexParser",
    "HermesParser",
    "OpenCodeParser",
    "HermesOutputParser",
    "LogDiscovery",
    "ReportGenerator",
    "CostPersistence",
    "Forecast",
    "ForecastPoint",
    "forecast",
]
