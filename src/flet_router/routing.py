from dataclasses import dataclass
import inspect
from enum import Enum
import re
from typing import Any, Callable, Coroutine, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode
from pathlib import PurePath
import flet as ft


@dataclass
class Location:
    name: Union[str, Enum]
    params: Optional[dict] = None
    query: Optional[dict] = None

    def build_path(self, route_path: str) -> str:
        if self.params:
            for key, value in self.params.items():
                route_path = route_path.replace(f"{{{key}}}", str(value))
        if self.query:
            query_string = urlencode(self.query)
            route_path = f"{route_path}?{query_string}"
        return route_path


FletRouterHandler = Callable[..., Coroutine[Any, Any, ft.View]]

RoutePath = Union[str, dict, Enum, Location]

MiddlewareResponse = Union[None, bool, RoutePath]

MiddlewareHandler = Callable[..., Coroutine[Any, Any, MiddlewareResponse]]


class FletRoute:
    def __init__(
        self,
        handler: FletRouterHandler,
        name: Union[str, Enum],
        path: str,
        middlewares: List[MiddlewareHandler],
    ):
        self.handler = handler
        self.name = name
        self.path = path
        self.middlewares = middlewares

        patter_path = re.sub(r"{([^/]+)}", r"(?P<\1>[^/]+)", path)
        try:
            self.pattern = re.compile("^" + patter_path + "$")
        except re.error as e:
            raise ValueError(f"Invalid path pattern: {path}")

    def extract_params(self, path: str) -> dict:
        params = {}

        path_only = path
        query_string = ""

        if "?" in path:
            path_only, query_string = path.split("?")

        match = re.match(self.pattern, path_only)
        if match:
            path_params = match.groupdict()
            params.update(path_params)

        if query_string:
            query_params = parse_qs(query_string)
            params.update(query_params)

        return params

    def match(self, path: str):
        only_path = path.split("?")[0]
        return bool(re.match(self.pattern, only_path))

    async def view(
        self,
        path: str,
        page: ft.Page,
        router: "FletRouter",
    ) -> ft.View:

        handler_params = inspect.signature(self.handler).parameters

        kwargs = {}
        if "page" in handler_params:
            kwargs["page"] = page
        if "router" in handler_params:
            kwargs["router"] = router

        path_params = self.extract_params(path)

        for key, param in handler_params.items():
            if key not in path_params:
                continue

            value = path_params[key]

            if param.annotation == inspect.Parameter.empty:
                kwargs[key] = value
                continue

            if (
                (not getattr(param.annotation, "__origin__", None) is list)
                and isinstance(value, list)
                and len(value) == 1
            ):
                value = value[0]

            try:
                kwargs[key] = param.annotation(value)
            except ValueError:
                raise TypeError(
                    f"Cannot convert {path_params[key]} to {param.annotation}"
                )

        view: ft.View = await self.handler(**kwargs)
        return view


class FletRouter:

    def __init__(
        self,
        prefix: str = "",
        middlewares: Optional[list] = None,
        page: Optional[ft.Page] = None,
    ):
        self.prefix = prefix
        self.middlewares = middlewares
        self.page = page

        self.routes: list[FletRoute] = []
        self.history: list[str] = []
        self.current_path: Optional[str] = None
        self.current_route: Optional[FletRoute] = None

    def add_route(
        self,
        handler: FletRouterHandler,
        name: Union[str, Enum],
        path: str,
        middlewares: list,
    ):
        pure_path = PurePath(
            "/",
            self.prefix.lstrip("/"),
            path.lstrip("/"),
        )
        route = FletRoute(
            handler=handler,
            name=name,
            path=str(pure_path),
            middlewares=middlewares,
        )
        self.routes.append(route)

    def route(
        self,
        name: Union[str, Enum] = "",
        path: str = "",
        middlewares: Optional[list] = None,
    ):
        def decorator(
            func: FletRouterHandler,
        ):
            self.add_route(
                handler=func,
                name=name,
                path=path,
                middlewares=middlewares or list(),
            )
            return func

        return decorator

    def include_router(self, router: "FletRouter"):
        for route in router.routes:
            new_middlewares = []
            if self.middlewares:
                new_middlewares.extend(self.middlewares)
            if route.middlewares:
                new_middlewares.extend(route.middlewares)
            self.add_route(
                handler=route.handler,
                name=route.name,
                path=route.path,
                middlewares=new_middlewares,
            )

    def _resolve(self, path: RoutePath) -> Tuple[Optional[FletRoute], str]:
        if isinstance(path, Enum):
            path = Location(name=path)
        if isinstance(path, dict):
            path = Location(**path)
        if isinstance(path, Location):
            for route in self.routes:
                if route.name == path.name:
                    return route, path.build_path(route.path)
        if isinstance(path, str):
            for route in self.routes:
                if route.match(path):
                    return route, path
        return None, ""

    async def _process_middleware(
        self,
        to_route: FletRoute,
        from_route: Optional[FletRoute],
        middleware_handler: MiddlewareHandler,
    ):
        handler_params = inspect.signature(middleware_handler).parameters

        kwargs = {}
        if "to_route" in handler_params:
            kwargs["to_route"] = to_route
        if "from_route" in handler_params:
            kwargs["from_route"] = from_route
        if "router" in handler_params:
            kwargs["router"] = self
        if "page" in handler_params:
            kwargs["page"] = self.page

        result = await middleware_handler(**kwargs)

        if result is None or result is True:
            return True

        if result is not False:
            self.go_root(result)

        return False

    async def _go_task(
        self,
        path: RoutePath,
        replace: bool = False,
    ):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")

        route, path = self._resolve(path)

        if route and route.middlewares:
            for middleware in route.middlewares:
                result = await self._process_middleware(
                    to_route=route,
                    from_route=self.current_route,
                    middleware_handler=middleware,
                )
                if result is False:
                    return

        self.current_route = route

        if route is None:
            view = ft.View()
        else:
            view = await route.view(path, self.page, self)

        if replace and self.page.views:
            self.page.views.pop()
        if not replace:
            self.history.append(str(self.page.route))

        self.current_path = path
        self.page.route = path
        self.page.views.append(view)
        self.page.update()

    def go_push(self, path: RoutePath):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")

        self.page.run_task(
            self._go_task,
            path,
        )

    def go_replace(self, path: RoutePath):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")

        self.page.run_task(
            self._go_task,
            path,
            True,
        )

    def go_root(self, path: RoutePath):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")

        self.page.views.clear()
        self.history.clear()

        self.page.run_task(
            self._go_task,
            path,
            True,
        )

    def back(self):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")

        if not self.history:
            return

        self.page.views.pop()
        prev_path = self.history.pop()
        self.page.route = prev_path

        self.page.run_task(
            self._go_task,
            prev_path,
            True,
        )

    def _render(
        self,
        default_path: Optional[str],
    ):
        if self.page is None:
            raise ValueError("Router is not mounted to a page")
        if default_path:
            self.page.route = default_path
        self.go_root(str(self.page.route))

    @classmethod
    def mount(
        cls,
        page: ft.Page,
        routes: List[FletRoute],
        default_path: Optional[str] = None,
    ):
        router = cls(page=page)

        for route in routes:
            router.add_route(
                handler=route.handler,
                name=route.name,
                path=route.path,
                middlewares=route.middlewares,
            )

        router._render(default_path)

        def on_connect(e: ft.ControlEvent):
            router._render(default_path)

        def on_route_change(e: ft.RouteChangeEvent):
            if router.current_path != e.route:
                router.go_root(e.route)

        page.on_connect = on_connect
        page.on_route_change = on_route_change

        return router
