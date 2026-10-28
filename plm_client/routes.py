"""Route (approval workflow) calls, built against docs/openapi/dsroute_v1.openapi.json (dsrt 1.0.0).

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
        """One route; with include_tasks each task comes with approvalStatus and comments."""
        params = {"$include": "tasks"} if include_tasks else None
        data = self.session.request("GET", f"{ROUTES}/{route_id}", params=params).get("data", [])
        return data[0] if data else {}

    def contents(self, route_id: str) -> list[dict]:
        """The objects attached to the route, e.g. the Engineering Items under review."""
        return self.session.request("GET", f"{ROUTES}/{route_id}/contents").get("data", [])

    def create(self, route: dict) -> dict:
        """Create one route (requestBodies/routes): title, description, contentIds ("id1|id2"), tasks, ..."""
        data = self.session.request("POST", ROUTES, json={"data": [route]}).get("data", [])
        return data[0] if data else {}

    def start(self, route_id: str) -> dict:
        """Define -> In Process: the tasks reach the assignees' inboxes."""
        data = self.session.request("POST", f"{ROUTES}/{route_id}/start").get("data", [])
        return data[0] if data else {}

    def delete(self, route_ids: list[str]) -> dict:
        return self.session.request("POST", f"{ROUTES}/delete", json={"data": [{"id": i} for i in route_ids]})

    def current_username(self) -> str:
        """The logged-in user's platform name, as task assignees are given (pno person service)."""
        person = self.session.request("GET", "/person", params={"current": "true"}, base="/resources/modeler/pno")
        return person.get("name", "")
