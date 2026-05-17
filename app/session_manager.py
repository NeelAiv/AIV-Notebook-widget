"""
Global orchestrator holder.

Originally this module managed multiple per-tab sessions keyed by X-Session-ID.
For the current single-user-per-deployment model we keep a single shared
IncidentOrchestrator instance instead.
"""

from app.orchestrator import IncidentOrchestrator

orchestrator = IncidentOrchestrator()

