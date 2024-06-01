from typing import final
import flet as ft
import flet_router as fr

router = fr.Router(
    prefix="/app",
)


@router.route(
    name="home_page",
)
async def home_page(
    router: fr.Router,
    page: ft.Page,
):

    def on_click_1(e):
        router.go_push("/app/second/123/value?query_variable=hello")

    def on_click_2(e):
        router.go_push(
            {
                "name": "second_page",
                "params": {"variable": 123},
                "query": {"query_variable": "hello"},
            }
        )

    def on_click_3(e):
        router.go_push(
            fr.Location(
                name="second_page",
                params={"variable": 123},
                query={"query_variable": "hello"},
            )
        )

    def on_click_4(e):
        router.go_push("/app/class")

    def on_click_5(e):
        router.go_push("/app/protected")

    def on_change(e: ft.ControlEvent):
        page.session.set("allow_access", e.data == "true")

    return ft.View(
        controls=[
            ft.ElevatedButton("Go to second page by path", on_click=on_click_1),
            ft.ElevatedButton("Go to second page by dict", on_click=on_click_2),
            ft.ElevatedButton("Go to second page by Location", on_click=on_click_3),
            ft.ElevatedButton("Go to class route page", on_click=on_click_4),
            ft.ElevatedButton("Go to protected page", on_click=on_click_5),
            ft.Switch(
                label="Allow access to protected page",
                on_change=on_change,
                value=page.session.get("allow_access"),
            ),
        ],
    )


@router.route(
    name="second_page",
    path="/second/{variable}/value",
)
async def second_page(
    router: fr.Router,
    variable: int,
    query_variable: str = "Not defined",
):

    def on_back(e):
        router.back()

    def on_click(e):
        router.go_push("/app/protected")

    return ft.View(
        controls=[
            ft.Text("Second page"),
            ft.Text(f"Variable: {type(variable)}, {variable}"),
            ft.Text(f"Query Variable: {query_variable}"),
            ft.ElevatedButton("Go back", on_click=on_back),
            ft.ElevatedButton("Go to protected page", on_click=on_click),
        ],
    )


async def protected_middleware(
    from_route: fr.Route,
    to_route: fr.Route,
    page: ft.Page,
):
    if page.session.get("allow_access"):
        return True
    else:
        if from_route.name == "home_page":
            return False
        elif from_route.name == "second_page":
            return fr.Location(name="home_page")


@router.route(
    name="protected_page",
    path="/protected",
    middlewares=[protected_middleware],
)
async def protected_page(
    router: fr.Router,
    page: ft.Page,
):

    def on_click(e):
        router.back()

    return ft.View(
        controls=[
            ft.Text(f"Session ID: {page.session_id}"),
            ft.Text("Protected page"),
            ft.ElevatedButton("Go back", on_click=on_click),
        ],
    )


@router.route(
    name="class_route",
    path="/class",
)
class ClassRoute(fr.RouteView):

    def __init__(self):
        # Optional method called when app is started
        print("ClassRoute: __init__")

    async def before_enter(self):
        # Optional method
        print("ClassRoute: before_enter")

    async def before_leave(self):
        # Optional method
        print("ClassRoute: before_leave")

    async def build(
        self,
        router: fr.Router,
    ):
        print("ClassRoute: build")

        def on_click(e):
            router.back()

        return ft.View(
            controls=[
                ft.ElevatedButton("Back", on_click=on_click),
                ft.Text("Class route. Check console output"),
            ],
        )


async def main(page: ft.Page):
    page.theme = ft.Theme(
        page_transitions=ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.NONE,
            ios=ft.PageTransitionTheme.NONE,
            linux=ft.PageTransitionTheme.NONE,
            macos=ft.PageTransitionTheme.NONE,
            windows=ft.PageTransitionTheme.NONE,
        )
    )

    app_router = fr.Router.mount(
        page,
        routes=router.routes,
    )

    app_router.go_root("/app")


app = ft.app(main, export_asgi_app=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8550,
        reload=True,
    )
