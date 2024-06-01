import abc
from dataclasses import dataclass
import inspect
from enum import Enum
import re
from typing import (
    Any,
    Callable,
    Coroutine,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from urllib.parse import parse_qs, urlencode
import flet as ft


class RouteView(abc.ABC):

    @abc.abstractmethod
    async def build(*args, **kwargs) -> ft.View:
        raise NotImplementedError

    @abc.abstractmethod
    async def before_enter(*args, **kwargs):
        pass

    @abc.abstractmethod
    async def before_leave(*args, **kwargs):
        pass


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


RouteCallableHandler = Callable[..., Coroutine[Any, Any, ft.View]]

RouteHandler = Union[RouteCallableHandler, RouteView, Type[RouteView]]

RoutePath = Union[str, dict, Enum, Location]

MiddlewareResponse = Union[None, bool, RoutePath]

MiddlewareHandler = Callable[..., Coroutine[Any, Any, MiddlewareResponse]]


class Route:
    def __init__(
        self,
        handler: RouteHandler,
        name: Union[str, Enum],
        path: str,
        middlewares: List[MiddlewareHandler],
    ):
        self.handler = handler
        self.name = name
        self.path = path
        self.middlewares = middlewares

        self._before_enter = None
        self._before_leave = None

        if (
            inspect.isclass(self.handler)
            and not isinstance(self.handler, RouteView)
            and issubclass(self.handler, RouteView)
        ):
            # initialize handler class
            self.handler = self.handler()

        if inspect.isfunction(self.handler):
            self._build = self.handler
        elif isinstance(self.handler, RouteView):
            _build: Optional[RouteCallableHandler] = getattr(
                self.handler, "build", None
            )
            if _build is None:
                raise ValueError(
                    f"Class {self.handler.__name__} must implement a build method"
                )
            self._build = _build
            self._before_enter = getattr(self.handler, "before_enter", None)
            self._before_leave = getattr(self.handler, "before_leave", None)
        else:
            raise ValueError(
                f"Invalid handler type in route {self.name}: {self.handler}"
            )

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

    def _prepare_kwargs(self, func, path, page, router):

        handler_params = inspect.signature(func).parameters

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

        return kwargs

    async def before_leave(self, path: str, page: ft.Page, router: "Router"):
        if self._before_leave is None:
            return

        kwargs = self._prepare_kwargs(self._before_leave, path, page, router)
        await self._before_leave(**kwargs)

    async def before_enter(self, path: str, page: ft.Page, router: "Router"):
        if self._before_enter is None:
            return

        kwargs = self._prepare_kwargs(self._before_enter, path, page, router)
        await self._before_enter(**kwargs)

    async def view(
        self,
        path: str,
        page: ft.Page,
        router: "Router",
    ) -> ft.View:
        kwargs = self._prepare_kwargs(self._build, path, page, router)
        view: ft.View = await self._build(**kwargs)
        return view

    def __str__(self) -> str:
        return f"FletRoute({self.name}, {self.path})"

    def __repr__(self) -> str:
        return str(self)


class Router:

    def __init__(
        self,
        prefix: str = "",
        middlewares: Optional[list] = None,
        page: Optional[ft.Page] = None,
    ):
        self.prefix = prefix
        self.middlewares = middlewares
        self.page = page

        self.routes: list[Route] = []
        self.history: list[str] = []
        self.current_path: Optional[str] = None
        self.current_route: Optional[Route] = None

    def _create_url_path(self, *segments: str):
        return "/" + "/".join(
            segment.strip("/") for segment in segments if segment.strip("/")
        )

    def add_route(
        self,
        handler: RouteHandler,
        name: Union[str, Enum],
        path: str,
        middlewares: list,
    ):
        path = self._create_url_path(self.prefix, path)
        route = Route(
            handler=handler,
            name=name,
            path=path,
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
            handler: RouteHandler,
        ):
            self.add_route(
                handler=handler,
                name=name,
                path=path,
                middlewares=middlewares or list(),
            )
            return handler

        return decorator

    def include_router(self, router: "Router"):
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

    def _resolve(self, path: RoutePath) -> Tuple[Optional[Route], str]:
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
        to_route: Route,
        from_route: Optional[Route],
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

        if self.current_route:
            await self.current_route.before_leave(
                path,
                self.page,
                self,
            )

        self.current_route = route

        if route is None:
            view = ft.View(
                bgcolor=f"{self.page.bgcolor}",
            )
        else:
            await route.before_enter(
                path,
                self.page,
                self,
            )
            view = await route.view(
                path,
                self.page,
                self,
            )

        if replace and self.page.views:
            self.page.views.pop()
        if not replace:
            self.history.append(str(self.page.route))

        self.current_path = path
        self.page.route = path
        self.page.views.append(view)
        self.page.update()

    def go_push(self, path: RoutePath):
        """
        path: route name, route path or Location object
        """
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
        if self.page.controls:
            self.page.controls.clear()
        if default_path:
            self.page.route = default_path
        self.go_root(self.page.route)

    @classmethod
    def mount(
        cls,
        page: ft.Page,
        routes: List[Route],
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

        router._render(default_path or page.route)

        # def on_connect(e: ft.ControlEvent):
        #     router._render(default_path or page.route)

        def on_route_change(e: ft.RouteChangeEvent):
            if router.current_path != e.route:
                router.go_root(e.route)

        # page.on_connect = on_connect
        page.on_route_change = on_route_change

        return router
