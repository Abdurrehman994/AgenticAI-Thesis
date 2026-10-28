"""Route (approval workflow) calls, from the dsrt 1.0.0 paths section of the Routes Web Services spec.

Read-only so far. Creating, starting and deleting routes waits for the request-body schemas in the spec's
components section (docs/openapi/dsrt-1.0.0.json, not saved yet): a guessed body would write to the shared tenant.
Verified on the tenant: GET /routes/search answers {"success": true, "statusCode": 200, "data": [...]}.
"""
from .session import PLMSession

ROUTES = "/dsrt/routes"
DEFAULT_STATES = ("Define", "In Process")  # the service's own default for routeStateFilter
ALL_STATES = ("Define", "In Process", "Complete")


class Routes:
    def __init__(self, session: PLMSession):
        self.session = session

    def search(self, search_str: str = "", *, states: tuple[str, ...] = DEFAULT_STATES, top: int = 50, skip: int = 0) -> list[dict]:
        """Indexed search; returns the latest revision of each route. Like item search, it lags behind creates."""
        params = {"routeStateFilter": ",".join(states), "$top": top, "$skip": skip}
        if search_str:
            params["searchStr"] = search_str
        return self.session.request("GET", f"{ROUTES}/search", params=params).get("data", [])

    def get(self, route_id: str, *, include_tasks: bool = True) -> dict:
        """One route; with include_tasks the reviewers' tasks and their states come along."""
        params = {"$include": "tasks"} if include_tasks else None
        data = self.session.request("GET", f"{ROUTES}/{route_id}", params=params).get("data", [])
        return data[0] if data else {}

    def contents(self, route_id: str) -> list[dict]:
        """The objects attached to the route, e.g. the Engineering Items under review."""
        return self.session.request("GET", f"{ROUTES}/{route_id}/contents").get("data", [])
